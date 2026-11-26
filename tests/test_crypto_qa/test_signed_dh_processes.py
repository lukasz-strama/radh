"""#107 / #20: podpisany DH na rzeczywistych procesach (produkcyjny ``multi_session_cli``).

W odróżnieniu od testów zespołu (deterministyczny runner ze stałymi kluczami) tu
węzły losują sekrety DH i klucze RSA tak jak na produkcji. Każdy opublikowany
podpis i hash sprawdzamy niezależnie: transkrypt z danych sesji wg
``AUTHENTICATED_DH.md`` → ``hashlib.sha256`` → ``pow(s, e, n)``.
"""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import httpx
import pytest

from helpers.multi_session_stack import ROLES, Stack, assert_no_secrets_in, bearer, dlog
from .conftest import RAISED_LIMITS

pytestmark = pytest.mark.live

P, G = 467, 2          # małe p: K da się odtworzyć logarytmem dyskretnym
ORDER = ["session_id", "backend_epoch", "signer", "prime", "generator", "alice_public",
         "bob_public", "alice_rsa_n", "alice_rsa_e", "bob_rsa_n", "bob_rsa_e"]


def transcript(view: dict, signer: str, alice_public: int, bob_public: int) -> bytes:
    keys = {k["owner"]: k for k in view["authentication"]["trusted_keys"]}
    values = {
        "session_id": view["session_id"], "backend_epoch": view["backend_epoch"],
        "signer": signer, "prime": view["prime"], "generator": view["generator"],
        "alice_public": alice_public, "bob_public": bob_public,
        "alice_rsa_n": keys["alice"]["modulus"], "alice_rsa_e": keys["alice"]["public_exponent"],
        "bob_rsa_n": keys["bob"]["modulus"], "bob_rsa_e": keys["bob"]["public_exponent"],
    }
    return "\n".join(["RADH-SIGNED-DH-V1"] + [f"{k}={values[k]}" for k in ORDER]).encode("ascii")


def views_of(view: dict) -> dict:
    """Lokalny widok (A, B) każdego uczestnika: własna oryginalna wartość + otrzymana."""
    sent = {m["sender"]: m["public_value"] for m in view["messages"]}
    if view["mode"] == "normal":
        return {"alice": (sent["alice"], sent["bob"]), "bob": (sent["alice"], sent["bob"])}
    original = {i["original_sender"]: i["original_value"] for i in view["interceptions"]}
    delivered = {i["recipient"]: i["delivered_value"] for i in view["interceptions"]}
    return {"alice": (original["alice"], delivered["alice"]),
            "bob": (delivered["bob"], original["bob"])}


def check_signatures_independently(view: dict) -> dict:
    """Zwraca {signer: podpis poprawny dla JEGO widoku} i sprawdza hash i podpis wprost."""
    keys = {k["owner"]: k for k in view["authentication"]["trusted_keys"]}
    local = views_of(view)
    result = {}
    for sig in view["authentication"]["signatures"]:
        signer = sig["signer"]
        data = transcript(view, signer, *local[signer])
        digest = sha256(data).hexdigest()
        assert sig["transcript_hash"] == digest, f"hash {signer} ≠ referencja z jego widoku"
        key = keys[signer]
        h = int(digest, 16) % key["modulus"]
        assert pow(sig["signature"], key["public_exponent"], key["modulus"]) == h
        assert sig["session_id"] == view["session_id"]
        assert sig["backend_epoch"] == view["backend_epoch"]
        result[signer] = digest
    return result


@pytest.fixture
def stack(core, tmp_path):
    stack = Stack(tmp_path, core.path, RAISED_LIMITS)
    stack.start_backend()
    stack.start_nodes()          # produkcyjny nodes.multi_session_cli, losowe klucze
    yield stack
    stack.close()


def run(stack, mode, scenario="authenticated", client=None):
    owned = stack.create(mode, P, G, scenario=scenario, client=client)
    stack.start(owned, client=client)
    return owned


def test_signed_dh_normal_succeeds_with_independently_valid_signatures(stack):
    owned = run(stack, "normal")
    view = stack.wait_status(owned, "completed", timeout=30)
    assert view["scenario"] == "authenticated"
    assert view["participants"] == {"alice": "verified", "bob": "verified"}
    auth = view["authentication"]
    assert {k["owner"] for k in auth["trusted_keys"]} == {"alice", "bob"}
    assert all(255 < k["modulus"] <= 2**32 - 1 and 1 < k["public_exponent"] < k["modulus"]
               for k in auth["trusted_keys"])
    hashes = check_signatures_independently(view)
    assert hashes["alice"] != hashes["bob"], "transkrypty różnią się polem signer"
    for v in auth["verifications"]:
        assert v["verified"] is True and v["transcript_hash"] == v["published_transcript_hash"]
        assert v["verifier"] != v["signer"]
    # K poprawny, liczony niezależnie (logarytm dyskretny dla małego p).
    sent = {m["sender"]: m["public_value"] for m in view["messages"]}
    k = pow(sent["bob"], dlog(G, sent["alice"], P), P)
    assert stack.wait_diagnostics(owned) == {"alice": k, "bob": k}
    events = [e["type"] for e in stack.events(owned)]
    assert events.count("trusted_key_published") == events.count("signature_published") == 2
    assert events.count("signature_verified") == 2 and events[-1] == "session_completed"
    for k_ in auth["trusted_keys"]:
        assert set(k_) == {"modulus", "public_exponent", "session_id", "backend_epoch", "owner"}


def test_signed_dh_mitm_is_rejected_and_hides_keys(stack):
    owned = run(stack, "mitm")
    view = stack.wait_status(owned, "failed", timeout=30)
    assert view["failure_code"] == "SIGNATURE_VERIFICATION_FAILED"
    auth = view["authentication"]
    # Każdy podpis jest poprawny dla WŁASNEGO widoku podpisującego…
    check_signatures_independently(view)
    # …ale weryfikator, licząc transkrypt partnera ze swojego (podmienionego) widoku, dostaje inny hash.
    rejected = [v for v in auth["verifications"] if v["verified"] is False]
    assert rejected, "co najmniej jedna strona musi odrzucić podpis"
    for v in rejected:
        assert v["transcript_hash"] != v["published_transcript_hash"]
    assert stack.diagnostics(owned) == {"alice": None, "bob": None}
    assert stack.diagnostics(owned, mallory=True) == {"shared_with_alice": None, "shared_with_bob": None}
    assert "signature_rejected" in [e["type"] for e in stack.events(owned)]


def test_two_parallel_signed_sessions_are_isolated(stack):
    """Dwóch użytkowników równolegle: podpisany normal i podpisany MITM.
    Klucze RSA są świeże w każdej sesji, a podpis z jednej nie pasuje do drugiej."""
    users = [httpx.Client(base_url=stack.url, timeout=10) for _ in range(2)]
    try:
        with ThreadPoolExecutor(2) as pool:
            normal, mitm = pool.map(lambda a: run(stack, a[0], client=a[1]),
                                    [("normal", users[0]), ("mitm", users[1])])
        v_normal = stack.wait_status(normal, "completed", timeout=30)
        v_mitm = stack.wait_status(mitm, "failed", timeout=30)
    finally:
        for user in users:
            user.close()
    assert v_mitm["failure_code"] == "SIGNATURE_VERIFICATION_FAILED"
    for v in (v_normal, v_mitm):
        for field in ("trusted_keys", "signatures", "verifications"):
            assert all(item["session_id"] == v["session_id"] for item in v["authentication"][field])
    keys_n = {(k["modulus"], k["public_exponent"]) for k in v_normal["authentication"]["trusted_keys"]}
    keys_m = {(k["modulus"], k["public_exponent"]) for k in v_mitm["authentication"]["trusted_keys"]}
    assert not keys_n & keys_m, "klucze RSA nie mogą być współdzielone między sesjami"
    # Replay: podpis Alice z sesji normal nie weryfikuje się w transkrypcie sesji MITM
    # (inne session_id, inne klucze) — sprawdzenie niezależne, bez backendu.
    sig = next(s for s in v_normal["authentication"]["signatures"] if s["signer"] == "alice")
    key_m = next(k for k in v_mitm["authentication"]["trusted_keys"] if k["owner"] == "alice")
    a, b = views_of(v_mitm)["alice"]
    h_m = int(sha256(transcript(v_mitm, "alice", a, b)).hexdigest(), 16) % key_m["modulus"]
    assert pow(sig["signature"] % key_m["modulus"], key_m["public_exponent"], key_m["modulus"]) != h_m
    # Właściciel A nie widzi sesji B.
    assert stack.http.get(mitm.path, headers=normal.auth).status_code == 404


def test_classic_and_signed_sessions_side_by_side(stack):
    """Regresja: klasyczny DH (normal i MITM) działa obok podpisanego, bez pól uwierzytelnienia."""
    classic_n, classic_m, signed = run(stack, "normal", "classic"), run(stack, "mitm", "classic"), \
        run(stack, "normal")
    assert stack.wait_status(classic_n, "completed")["participants"] == {"alice": "received", "bob": "received"}
    assert stack.wait_status(classic_m, "completed")["status"] == "completed"
    assert stack.wait_status(signed, "completed", timeout=30)["participants"]["alice"] == "verified"
    for owned in (classic_n, classic_m):
        auth = stack.get(owned)["authentication"]
        assert auth["trusted_keys"] == auth["signatures"] == auth["verifications"] == []


def test_cancel_signed_session_does_not_affect_other(stack):
    """Reset/anulowanie w trakcie uwierzytelniania: druga podpisana sesja kończy się normalnie."""
    stack.pause("bob")
    try:
        first, second = run(stack, "normal"), run(stack, "normal")
        stack.wait_for(lambda: stack.get(first),
                       lambda v: any(k["owner"] == "alice" for k in v["authentication"]["trusted_keys"]))
        cancelled = stack.http.post(first.path + "/cancel", headers=first.auth)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    finally:
        stack.resume("bob")
    assert stack.wait_status(second, "completed", timeout=30)["participants"]["bob"] == "verified"
    final = stack.get(first)
    assert final["status"] == "cancelled"
    assert len(final["authentication"]["verifications"]) == 0
    assert stack.diagnostics(first) == {"alice": None, "bob": None}
    # DELETE (Reset w UI) usuwa sesję — potem 410 dla właściciela.
    assert stack.http.delete(first.path, headers=first.auth).status_code == 204
    assert stack.http.get(first.path, headers=first.auth).status_code == 410


def test_no_private_material_in_responses_or_logs(stack):
    owned = run(stack, "normal")
    view = stack.wait_status(owned, "completed", timeout=30)
    text = stack.http.get(owned.path, headers=owned.auth).text + str(stack.events(owned))
    for forbidden in ('"d"', "private_exponent", '"phi"', '"p":', '"q":', "secret\""):
        assert forbidden not in text, forbidden
    assert_no_secrets_in(stack.all_logs(), owned.token, *stack.tokens.values())
    assert view["status"] == "completed"
