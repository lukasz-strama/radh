"""#107 / #103: nieautoryzowane i niepoprawne operacje podpisanego DH na koordynatorze.

Pseudo-węzły (klient HTTP z tokenem roli) wykonują kroki protokołu ręcznie. Każda
odrzucona operacja ma zostawić identyczny stan sesji (widok + zdarzenia).
"""

from hashlib import sha256

import pytest

from helpers.multi_session_stack import Stack
from .conftest import RAISED_LIMITS, code

pytestmark = pytest.mark.live

KEYS = {"alice": {"modulus": 3233, "public_exponent": 17},
        "bob": {"modulus": 3127, "public_exponent": 3}}
H1, H2 = sha256(b"one").hexdigest(), sha256(b"two").hexdigest()


def snapshot(stack, owned):
    return stack.get(owned), stack.events(owned)


@pytest.fixture
def env(core, tmp_path):
    stack = Stack(tmp_path, core.path, RAISED_LIMITS)
    stack.start_backend()
    nodes = {r: stack.node(r).register() for r in ("alice", "bob", "mallory")}
    yield stack, nodes
    stack.close()


def started(stack, mode="normal", scenario="authenticated"):
    owned = stack.create(mode, 23, 5, scenario=scenario)
    stack.start(owned)
    return owned


def key(node, sid, body):
    return node.request("POST", f"/sessions/{sid}/trusted-keys", json=body)


def sign(node, sid, h=H1, s=5):
    return node.request("POST", f"/sessions/{sid}/signatures", json={"transcript_hash": h, "signature": s})


def verify(node, sid, signer, h, ok):
    return node.request("POST", f"/sessions/{sid}/verifications",
                        json={"signer": signer, "transcript_hash": h, "verified": ok})


def ready_for_signatures(stack, nodes, owned):
    sid, view = owned.session_id, stack.get(owned)
    for role in ("alice", "bob"):
        assert key(nodes[role], sid, KEYS[role]).status_code == 200
        assert nodes[role].publish(sid, view).status_code == 200


def test_mallory_has_no_access_to_authentication(env):
    stack, nodes = env
    owned = started(stack, "mitm")
    before = snapshot(stack, owned)
    mallory, sid = nodes["mallory"], owned.session_id
    assert code(mallory.request("GET", f"/sessions/{sid}/authentication")) == (403, "ROLE_FORBIDDEN")
    assert code(key(mallory, sid, KEYS["alice"])) == (403, "ROLE_FORBIDDEN")
    assert code(sign(mallory, sid)) == (403, "ROLE_FORBIDDEN")
    assert code(verify(mallory, sid, "alice", H1, True)) == (403, "ROLE_FORBIDDEN")
    assert snapshot(stack, owned) == before


def test_classic_session_rejects_authentication(env):
    stack, nodes = env
    owned = started(stack, scenario="classic")
    before = snapshot(stack, owned)
    assert code(key(nodes["alice"], owned.session_id, KEYS["alice"])) == (409, "AUTHENTICATION_NOT_ENABLED")
    assert snapshot(stack, owned) == before


def test_owner_comes_from_token_not_body(env):
    stack, nodes = env
    owned = started(stack)
    sid = owned.session_id
    forged = key(nodes["bob"], sid, {**KEYS["alice"], "owner": "alice"})
    assert forged.status_code == 422, "pole owner w body jest zabronione"
    published = key(nodes["bob"], sid, KEYS["bob"]).json()
    assert published["owner"] == "bob"
    assert {k["owner"] for k in stack.get(owned)["authentication"]["trusted_keys"]} == {"bob"}


@pytest.mark.parametrize("body,expected", [
    ({"modulus": 255, "public_exponent": 3}, (422, "INVALID_RSA_KEY")),
    ({"modulus": 3233, "public_exponent": 1}, (422, "INVALID_RSA_KEY")),
    ({"modulus": 3233, "public_exponent": 3233}, (422, "INVALID_RSA_KEY")),
    ({"modulus": 2**32, "public_exponent": 3}, (422, "INVALID_REQUEST")),
    ({"modulus": "3233", "public_exponent": 17}, (422, "INVALID_REQUEST")),
])
def test_invalid_trusted_key_changes_nothing(env, body, expected):
    stack, nodes = env
    owned = started(stack)
    before = snapshot(stack, owned)
    assert code(key(nodes["alice"], owned.session_id, body)) == expected
    assert snapshot(stack, owned) == before


def test_signature_order_bounds_and_format(env):
    stack, nodes = env
    owned = started(stack)
    sid, alice = owned.session_id, nodes["alice"]
    assert code(sign(alice, sid)) == (409, "TRUSTED_KEYS_REQUIRED")
    for role in ("alice", "bob"):
        key(nodes[role], sid, KEYS[role])
    assert code(sign(alice, sid)) == (409, "PUBLIC_VALUES_REQUIRED")
    view = stack.get(owned)
    nodes["alice"].publish(sid, view)
    nodes["bob"].publish(sid, view)
    before = snapshot(stack, owned)
    assert code(sign(alice, sid, s=3233)) == (422, "INVALID_SIGNATURE")       # s ≥ n_alice
    for bad in (H1.upper(), H1[:-1], H1 + "0", "z" * 64):
        assert code(sign(alice, sid, h=bad))[0] == 422
    assert snapshot(stack, owned) == before


def test_conflicts_and_idempotent_retries(env):
    stack, nodes = env
    owned = started(stack)
    sid, alice = owned.session_id, nodes["alice"]
    ready_for_signatures(stack, nodes, owned)
    assert code(key(alice, sid, {"modulus": 3233, "public_exponent": 7})) == (409, "TRUSTED_KEY_CONFLICT")
    first = sign(alice, sid).json()
    events = len(stack.events(owned))
    assert sign(alice, sid).json() == first, "identyczne ponowienie zwraca zapisany podpis"
    assert len(stack.events(owned)) == events, "…bez nowego zdarzenia"
    assert code(sign(alice, sid, h=H2)) == (409, "SIGNATURE_CONFLICT")
    assert code(sign(alice, sid, s=6)) == (409, "SIGNATURE_CONFLICT")


def test_verification_rules(env):
    stack, nodes = env
    owned = started(stack)
    sid, alice, bob = owned.session_id, nodes["alice"], nodes["bob"]
    ready_for_signatures(stack, nodes, owned)
    sign(alice, sid, h=H1)
    assert code(verify(alice, sid, "bob", H2, True)) == (409, "SIGNATURE_REQUIRED")
    sign(bob, sid, h=H2)
    before = snapshot(stack, owned)
    assert code(verify(alice, sid, "alice", H2, True)) == (403, "ROLE_FORBIDDEN")   # nie siebie
    assert code(verify(alice, sid, "bob", H1, True)) == (422, "TRANSCRIPT_MISMATCH")
    assert code(alice.report(sid, 2)) == (409, "VERIFICATION_REQUIRED")
    assert snapshot(stack, owned) == before
    assert verify(alice, sid, "bob", H2, True).status_code == 200
    assert stack.get(owned)["participants"]["alice"] == "verified"


def test_negative_verification_fails_session_and_zeroes_keys(env):
    stack, nodes = env
    owned = started(stack)
    sid, alice, bob = owned.session_id, nodes["alice"], nodes["bob"]
    ready_for_signatures(stack, nodes, owned)
    sign(alice, sid, h=H1)
    sign(bob, sid, h=H2)
    assert verify(bob, sid, "alice", H2, False).status_code == 200
    view = stack.get(owned)
    assert (view["status"], view["failure_code"]) == ("failed", "SIGNATURE_VERIFICATION_FAILED")
    assert stack.diagnostics(owned) == {"alice": None, "bob": None}
    # Po porażce nic już nie przechodzi.
    assert code(verify(alice, sid, "bob", H2, True)) == (409, "INVALID_SESSION_STATE")
    assert code(alice.ack(sid, "bob-public")) == (409, "INVALID_SESSION_STATE")


def test_foreign_epoch_and_instance_rejected(env):
    stack, nodes = env
    owned = started(stack)
    sid, alice = owned.session_id, nodes["alice"]
    before = snapshot(stack, owned)
    assert code(alice.request("POST", f"/sessions/{sid}/trusted-keys", json=KEYS["alice"],
                              headers=alice.headers(epoch="0" * 32))) == (409, "BACKEND_EPOCH_MISMATCH")
    assert code(alice.request("POST", f"/sessions/{sid}/trusted-keys", json=KEYS["alice"],
                              headers=alice.headers(instance="f" * 32))) == (409, "NODE_INSTANCE_MISMATCH")
    owner = stack.http.post(f"/internal/v1/dh/sessions/{sid}/trusted-keys", json=KEYS["alice"],
                            headers={"Authorization": "Bearer " + owned.token})
    assert owner.status_code == 401, "token właściciela nie działa na API węzłów"
    assert snapshot(stack, owned) == before
