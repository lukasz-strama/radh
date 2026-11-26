"""#107 / #20: podpisy RSA nad kanonicznym transkryptem DH — poziom CryptoCore.

Transkrypt budujemy niezależnie według ``backend/AUTHENTICATED_DH.md`` (gałąź #103),
skrót liczymy ``hashlib.sha256``, a podpis weryfikujemy także czystym ``pow``.
Sprawdzamy scenariusze protokołu, zanim powstaną węzły podpisujące:
podmiana pola, replay z innej sesji, zamiana roli, widok po MITM i klucz Mallory.
"""

import ctypes
import random
from hashlib import sha256

import pytest

from native_core import SENTINEL, STATUS
from .conftest import UINT32_MAX, rsa_keys

ALICE = rsa_keys(65_521, 65_519, 65_537)      # duże n: kolizje reprezentantów ~1/n
BOB = rsa_keys(65_497, 65_479, 5)
MALLORY = rsa_keys(65_449, 65_447, 5)

BASE = {
    "session_id": "0123456789abcdef0123456789abcdef",
    "backend_epoch": "fedcba9876543210fedcba9876543210",
    "signer": "alice", "prime": 467, "generator": 2,
    "alice_public": 381, "bob_public": 213,
    "alice_rsa_n": ALICE["n"], "alice_rsa_e": ALICE["e"],
    "bob_rsa_n": BOB["n"], "bob_rsa_e": BOB["e"],
}
ORDER = ["session_id", "backend_epoch", "signer", "prime", "generator", "alice_public",
         "bob_public", "alice_rsa_n", "alice_rsa_e", "bob_rsa_n", "bob_rsa_e"]


def transcript(**fields) -> bytes:
    values = {**BASE, **fields}
    lines = ["RADH-SIGNED-DH-V1"] + [f"{k}={values[k]}" for k in ORDER]
    return "\n".join(lines).encode("ascii")   # LF, bez końcowego LF


def representative(data: bytes, n: int) -> int:
    return int.from_bytes(sha256(data).digest(), "big") % n


@pytest.fixture(scope="module")
def c(core):
    lib = ctypes.CDLL(str(core.path))
    sign, verify = lib.radh_rsa_sign_u32, lib.radh_rsa_verify_u32
    sign.argtypes = [ctypes.c_uint32] * 3 + [ctypes.POINTER(ctypes.c_uint32)]
    verify.argtypes = [ctypes.c_uint32] * 4 + [ctypes.POINTER(ctypes.c_uint32)]
    sign.restype = verify.restype = ctypes.c_int

    def do_sign(h, key):
        out = ctypes.c_uint32(SENTINEL)
        assert sign(h, key["d"], key["n"], ctypes.byref(out)) == STATUS["OK"]
        assert out.value == pow(h, key["d"], key["n"]), "podpis C ≠ referencja pow"
        return out.value

    def do_verify(h, s, key):
        out = ctypes.c_uint32(SENTINEL)
        status = verify(h, s, key["e"], key["n"], ctypes.byref(out))
        assert status == STATUS["OK"]
        assert out.value == int(pow(s, key["e"], key["n"]) == h), "weryfikacja C ≠ referencja"
        return out.value

    return do_sign, do_verify


def test_canonical_transcript_format():
    data = transcript()
    assert data.startswith(b"RADH-SIGNED-DH-V1\nsession_id=")
    assert not data.endswith(b"\n") and b"\r" not in data and b" " not in data
    assert data.count(b"\n") == 11


def test_valid_signature_verifies(c):
    sign, verify = c
    for signer, key in (("alice", ALICE), ("bob", BOB)):
        h = representative(transcript(signer=signer), key["n"])
        assert verify(h, sign(h, key), key) == 1


@pytest.mark.parametrize("field", ORDER)
def test_every_changed_field_is_rejected(c, field):
    """Podmiana dowolnego pola transkryptu (wartość +1 / inny znak) unieważnia podpis."""
    sign, verify = c
    h = representative(transcript(), ALICE["n"])
    s = sign(h, ALICE)
    original = BASE[field]
    if isinstance(original, int):
        changed = original + 1
    elif field == "signer":
        changed = "bob"
    else:
        changed = original[:-1] + ("0" if original[-1] != "0" else "1")
    h2 = representative(transcript(**{field: changed}), ALICE["n"])
    assert h2 != h, "kolizja reprezentantów po redukcji mod n (dla dużego n niemal niemożliwa)"
    assert verify(h2, s, ALICE) == 0


def test_replay_between_sessions_is_rejected(c):
    """Podpis z sesji A przedstawiony w sesji B (inne session_id lub epoch) nie przechodzi."""
    sign, verify = c
    s_a = sign(representative(transcript(), ALICE["n"]), ALICE)
    for other in ({"session_id": "a" * 32}, {"backend_epoch": "b" * 32},
                  {"session_id": "a" * 32, "backend_epoch": "b" * 32}):
        assert verify(representative(transcript(**other), ALICE["n"]), s_a, ALICE) == 0
    # Replay po restarcie backendu z tym samym session_id, ale nowym epoch — też odrzucony.
    assert verify(representative(transcript(backend_epoch="c" * 32), ALICE["n"]), s_a, ALICE) == 0


def test_signature_cannot_be_reused_for_other_role(c):
    sign, verify = c
    s = sign(representative(transcript(signer="alice"), ALICE["n"]), ALICE)
    assert verify(representative(transcript(signer="bob"), ALICE["n"]), s, ALICE) == 0
    # Podpis Alice nie jest też podpisem Boba pod jego kluczem.
    h_bob = representative(transcript(signer="bob"), BOB["n"])
    assert verify(h_bob, s % BOB["n"], BOB) == 0


def test_mitm_view_mismatch_fails_verification(c):
    """Normal: obie strony widzą te same A/B → weryfikacja OK.
    MITM: Mallory podmienia B u Alice; Bob podpisał swój widok, Alice weryfikuje swój → 0."""
    sign, verify = c
    bob_view = transcript(signer="bob", alice_public=381, bob_public=213)
    s_bob = sign(representative(bob_view, BOB["n"]), BOB)
    alice_view_normal = transcript(signer="bob", alice_public=381, bob_public=213)
    assert verify(representative(alice_view_normal, BOB["n"]), s_bob, BOB) == 1
    alice_view_mitm = transcript(signer="bob", alice_public=381, bob_public=99)  # X Mallory
    assert verify(representative(alice_view_mitm, BOB["n"]), s_bob, BOB) == 0


def test_mallory_key_cannot_impersonate(c):
    """Mallory podpisuje podmieniony transkrypt własnym kluczem; zaufany klucz Boba go odrzuca.
    Podmiana samego klucza w transkrypcie też zmienia h (klucze są częścią transkryptu)."""
    sign, verify = c
    forged = transcript(signer="bob", bob_public=99)
    s_mallory = sign(representative(forged, MALLORY["n"]), MALLORY)
    assert verify(representative(forged, BOB["n"]), s_mallory % BOB["n"], BOB) == 0
    with_mallory_key = transcript(signer="bob", bob_rsa_n=MALLORY["n"], bob_rsa_e=MALLORY["e"])
    assert representative(with_mallory_key, BOB["n"]) != representative(
        transcript(signer="bob"), BOB["n"])


def test_random_tampering_detection_rate(c):
    """1000 losowych zmian jednego pola: przy n ≈ 2^32 każda musi zostać wykryta."""
    sign, verify = c
    rng = random.Random(107)
    h = representative(transcript(), ALICE["n"])
    s = sign(h, ALICE)
    numeric = [f for f in ORDER if isinstance(BASE[f], int)]
    missed = 0
    for _ in range(1000):
        field = rng.choice(numeric)
        value = rng.randrange(1, UINT32_MAX)
        if value == BASE[field]:
            continue
        missed += verify(representative(transcript(**{field: value}), ALICE["n"]), s, ALICE)
    assert missed == 0


def test_small_modulus_collision_is_educational_limit(c):
    """Obserwacja (nie defekt): przy n = 3233 reprezentant ma tylko 3233 wartości, więc
    po ~3233 próbach zwykle da się znaleźć inny transkrypt z tym samym h. Dokumentujemy
    to jako ograniczenie wersji edukacyjnej 32-bitowej."""
    sign, verify = c
    small = rsa_keys(61, 53, 17)
    h = representative(transcript(), small["n"])
    s = sign(h, small)
    collision = next((v for v in range(1, 20_000)
                      if representative(transcript(alice_public=v), small["n"]) == h), None)
    assert collision is not None
    assert verify(representative(transcript(alice_public=collision), small["n"]), s, small) == 1


@pytest.mark.parametrize(("h", "s", "e", "n", "status"), [
    (5, 5, 17, 0, "INVALID_MODULUS"), (5, 5, 17, 1, "INVALID_MODULUS"),
    (5, 5, 0, 3233, "INVALID_EXPONENT"), (3233, 5, 17, 3233, "INVALID_MESSAGE"),
    (5, 3233, 17, 3233, "INVALID_MESSAGE"), (UINT32_MAX, 1, 3, UINT32_MAX, "INVALID_MESSAGE"),
])
def test_verify_invalid_input_keeps_output(core, h, s, e, n, status):
    lib = ctypes.CDLL(str(core.path))
    verify = lib.radh_rsa_verify_u32
    verify.argtypes = [ctypes.c_uint32] * 4 + [ctypes.POINTER(ctypes.c_uint32)]
    verify.restype = ctypes.c_int
    out = ctypes.c_uint32(SENTINEL)
    assert verify(h, s, e, n, ctypes.byref(out)) == STATUS[status]
    assert out.value == SENTINEL, "błąd nie może zmienić bufora wyjściowego"


def test_random_keys_from_api_sign_and_verify(c, api):
    """Klucze z wylosowanych parametrów (#108) działają z podpisami (#113)."""
    sign, verify = c
    for _ in range(25):
        s = api.http.post("/api/v1/rsa/demo/parameters").json()
        key = rsa_keys(s["p"], s["q"], s["e"])
        h = representative(transcript(alice_rsa_n=key["n"], alice_rsa_e=key["e"]), key["n"])
        sig = sign(h, key)
        assert verify(h, sig, key) == 1
        assert verify((h + 1) % key["n"], sig, key) == 0
