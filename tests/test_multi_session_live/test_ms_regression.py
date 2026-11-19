"""#71: regresja pojedynczych scenariuszy RSA/DH/MITM na backendzie z koordynatorem v2.

Pełna regresja v1 (RSA encrypt/keygen, DH demo, sesje v1, procesy v1) pozostaje
w istniejących katalogach ``tests/`` i jest uruchamiana tym samym ``pytest``.
Tu: te same ścieżki na rzeczywistym serwerze z włączonym rejestrem v2, oraz
tryb po migracji ``RADH_LEGACY_API_ENABLED=false``.
"""

import json
from pathlib import Path

import pytest

from helpers.multi_session_stack import expected_keys

pytestmark = pytest.mark.live

DATA = Path(__file__).resolve().parents[1] / "data"
RSA = json.loads((DATA / "rsa_cases.json").read_text(encoding="utf-8"))["valid"]
DH = json.loads((DATA / "dh_cases.json").read_text(encoding="utf-8"))["valid"]
V1_SESSION_ROUTES = [
    ("POST", "/api/v1/dh/sessions"), ("GET", "/api/v1/dh/sessions/current"),
    ("GET", "/api/v1/dh/nodes"), ("POST", "/api/v1/dh/nodes/alice/heartbeat"),
    ("GET", "/api/v1/dh/sessions/" + "a" * 32),
]


def _rsa_and_dh_demo(stack):
    for case in RSA[:5]:
        response = stack.http.post("/api/v1/rsa/demo/encrypt", json={
            k: case[k] for k in ("message", "public_exponent", "modulus")})
        assert response.status_code == 200, response.text
        assert response.json() == {"ciphertext": case["ciphertext"]}
    keygen = stack.http.post("/api/v1/rsa/demo/keygen", json={"p": 61, "q": 53, "e": 17})
    assert keygen.status_code == 200
    assert keygen.json() == {"n": 3233, "e": 17, "d": 2753, "phi": 3120}
    case = DH[0]
    exchange = stack.http.post("/api/v1/dh/demo/exchange", json={
        k: case[k] for k in ("prime", "generator", "alice_secret", "bob_secret")})
    assert exchange.status_code == 200
    assert exchange.json() == {"alice_public": case["alice_public"], "bob_public": case["bob_public"],
                               "alice_shared_key": case["shared_key"], "bob_shared_key": case["shared_key"]}


def test_single_normal_and_single_mitm_session_v2(stack):
    for mode, prime, generator in (("normal", 23, 5), ("mitm", 23, 5)):
        owned = stack.create(mode, prime, generator)
        stack.start(owned)
        view = stack.wait_status(owned, "completed")
        assert stack.wait_diagnostics(owned) == expected_keys(view)
        if mode == "mitm":
            mallory = stack.wait_diagnostics(owned, mallory=True)
            assert mallory == {"shared_with_alice": expected_keys(view)["alice"],
                               "shared_with_bob": expected_keys(view)["bob"]}


def test_rsa_keygen_and_dh_demo_unchanged_in_migration_mode(make_stack):
    stack = make_stack(nodes=False)
    _rsa_and_dh_demo(stack)
    # Tryb migracji (domyślny): routery v1 nadal działają z własnym magazynem.
    assert stack.http.get("/api/v1/dh/nodes").status_code == 200


def test_without_diagnostics_opt_in_keys_are_never_exposed(make_stack):
    stack = make_stack(allow_diagnostics=False)
    owned = stack.create("mitm", 467, 2, diagnostics=True)
    stack.start(owned)
    stack.wait_status(owned, "completed")
    assert stack.diagnostics(owned) == {"alice": None, "bob": None}
    assert stack.diagnostics(owned, mallory=True) == {"shared_with_alice": None, "shared_with_bob": None}


def test_session_without_owner_opt_in_has_no_keys(stack):
    owned = stack.create("normal", 467, 2, diagnostics=False)
    stack.start(owned)
    stack.wait_status(owned, "completed")
    assert stack.diagnostics(owned) == {"alice": None, "bob": None}


def test_legacy_disabled_removes_v1_session_routes(make_stack):
    stack = make_stack(nodes=False, env={"RADH_LEGACY_API_ENABLED": "false"})
    for method, path in V1_SESSION_ROUTES:
        response = stack.http.request(method, path, json={} if method == "POST" else None)
        assert response.status_code in (404, 405), (method, path, response.status_code)


def test_legacy_disabled_keeps_demo_with_crypto_limiter(make_stack):
    stack = make_stack(env={"RADH_LEGACY_API_ENABLED": "false"})
    # Po wyłączeniu legacy demo C ma limiter 20/min/IP, burst 5 → 6. żądanie 429.
    statuses = [stack.http.post("/api/v1/rsa/demo/encrypt", json={
        "message": 65, "public_exponent": 17, "modulus": 3233}) for _ in range(6)]
    assert [r.status_code for r in statuses] == [200] * 5 + [429]
    assert statuses[0].json() == {"ciphertext": 2790}
    assert statuses[0].headers["cache-control"] == "no-store"
    assert int(statuses[5].headers["retry-after"]) >= 1
    # Ścieżka v2 działa niezależnie od limitu demo.
    owned = stack.create("normal", 23, 5)
    stack.start(owned)
    assert stack.wait_status(owned, "completed")["status"] == "completed"
