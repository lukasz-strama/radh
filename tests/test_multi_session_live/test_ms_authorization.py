"""#71 / G02–G04, G14: dostęp do cudzej sesji i nieautoryzowane operacje węzłów.

Kryterium: nieautoryzowane operacje nie zmieniają stanu aplikacji. Każdy test
porównuje pełny snapshot (SessionView + zdarzenia + diagnostyka) przed i po.
"""

import secrets

import pytest

from helpers.multi_session_stack import ROLES, assert_no_secrets_in, bearer, new_key

pytestmark = pytest.mark.live

OWNER_OPERATIONS = [
    ("GET", ""), ("POST", "/start"), ("POST", "/cancel"), ("DELETE", ""),
    ("GET", "/events"), ("GET", "/diagnostics"), ("GET", "/diagnostics/mallory"),
]


def snapshot(stack, owned):
    return (stack.get(owned), stack.events(owned), stack.diagnostics(owned),
            stack.diagnostics(owned, mallory=True))


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert response.headers["cache-control"] == "no-store"
    assert "x-backend-epoch" in response.headers


@pytest.fixture
def two_users(make_stack):
    """Dwie sesje dwóch właścicieli w stanie created (bez procesów — szybciej)."""
    stack = make_stack(nodes=False)
    return stack, stack.create("normal", 23, 5), stack.create("mitm", 467, 2)


@pytest.mark.parametrize("method,suffix", OWNER_OPERATIONS)
def test_foreign_owner_token_is_404_and_changes_nothing(two_users, method, suffix):
    stack, victim, attacker = two_users
    before = snapshot(stack, victim)
    for token in (attacker.token, secrets.token_urlsafe(32), *stack.tokens.values()):
        response = stack.http.request(method, victim.path + suffix, headers=bearer(token))
        assert_error(response, 404, "SESSION_NOT_FOUND")
        assert victim.session_id not in response.text
    assert snapshot(stack, victim) == before
    # Właściciel nadal steruje własną sesją, a atakujący swoją.
    cancelled = stack.http.post(victim.path + "/cancel", headers=victim.auth)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert stack.get(attacker)["status"] == "created"


@pytest.mark.parametrize("header", [
    None, "", "Bearer", "Basic dXNlcjpwYXNz",
    "Bearer " + "a" * 42, "Bearer " + "a" * 44, "Bearer " + "a" * 42 + "=",
])
def test_missing_or_malformed_bearer_is_401(two_users, header):
    stack, victim, _ = two_users
    before = snapshot(stack, victim)
    headers = {} if header is None else {"Authorization": header}
    for method, suffix in OWNER_OPERATIONS:
        response = stack.http.request(method, victim.path + suffix, headers=headers)
        assert_error(response, 401, "UNAUTHORIZED")
        assert response.headers["www-authenticate"] == "Bearer"
    assert snapshot(stack, victim) == before


def test_unknown_id_and_foreign_id_are_indistinguishable(two_users):
    stack, victim, attacker = two_users
    unknown = "/api/v2/dh/sessions/" + secrets.token_hex(16)
    foreign = stack.http.get(victim.path, headers=attacker.auth)
    missing = stack.http.get(unknown, headers=attacker.auth)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    # Niepoprawny format ID to błąd walidacji, nie wyciek istnienia.
    assert_error(stack.http.get("/api/v2/dh/sessions/NOT-HEX", headers=attacker.auth),
                 422, "INVALID_REQUEST")


def test_tombstone_is_410_only_for_owner(two_users):
    stack, victim, attacker = two_users
    assert stack.http.delete(victim.path, headers=victim.auth).status_code == 204
    assert_error(stack.http.get(victim.path, headers=victim.auth), 410, "SESSION_EXPIRED")
    assert stack.http.delete(victim.path, headers=victim.auth).status_code == 204
    for token in (attacker.token, secrets.token_urlsafe(32)):
        assert_error(stack.http.get(victim.path, headers=bearer(token)), 404, "SESSION_NOT_FOUND")
        assert_error(stack.http.delete(victim.path, headers=bearer(token)), 404, "SESSION_NOT_FOUND")
    assert stack.get(attacker)["status"] == "created"


def test_foreign_origin_rejected_even_with_valid_token(two_users):
    stack, victim, _ = two_users
    before = snapshot(stack, victim)
    evil = {"Origin": "https://evil.example", **victim.auth}
    for method, suffix in OWNER_OPERATIONS:
        assert_error(stack.http.request(method, victim.path + suffix, headers=evil),
                     403, "ORIGIN_NOT_ALLOWED")
    assert_error(stack.create_raw({"prime": 23, "generator": 5}, headers={"Origin": "https://evil.example"}),
                 403, "ORIGIN_NOT_ALLOWED")
    assert snapshot(stack, victim) == before
    allowed = stack.http.get(victim.path, headers={"Origin": "http://localhost:5173", **victim.auth})
    assert allowed.status_code == 200
    assert "access-control-allow-origin" not in allowed.headers or \
        allowed.headers["access-control-allow-origin"] != "*"


def test_token_only_in_create_response(two_users):
    stack, victim, _ = two_users
    created = victim.created
    assert set(created) == {"session", "session_token"}
    assert "session_token" not in created["session"]
    for response in (stack.http.get(victim.path, headers=victim.auth),
                     stack.http.get(victim.path + "/events", headers=victim.auth)):
        assert_no_secrets_in(response.text, victim.token, victim.create_key)
    assert_no_secrets_in(stack.backend_log(), victim.token, victim.create_key, *stack.tokens.values())


def test_legacy_v1_router_cannot_touch_v2_sessions(two_users):
    """Tryb migracji: niezabezpieczony v1 ma osobny magazyn, nie widzi ID v2."""
    stack, victim, _ = two_users
    before = snapshot(stack, victim)
    v1 = "/api/v1/dh/sessions/" + victim.session_id
    for method, suffix in (("GET", ""), ("POST", "/start"), ("POST", "/cancel"),
                           ("GET", "/diagnostics"), ("GET", "/events")):
        assert stack.http.request(method, v1 + suffix).status_code == 404
    assert snapshot(stack, victim) == before


# --- węzły: role, instancje, epoch ---------------------------------------------------------

@pytest.fixture
def pseudo(make_stack):
    """Backend bez procesów; trzy pseudo-węzły z tokenami ról i znanymi instance_id."""
    stack = make_stack(nodes=False)
    nodes = {role: stack.node(role).register() for role in ROLES}
    normal = stack.create("normal", 23, 5)
    mitm = stack.create("mitm", 467, 2)
    stack.start(normal)
    stack.start(mitm)
    return stack, nodes, normal, mitm


def test_internal_requires_role_token(pseudo):
    stack, nodes, normal, mitm = pseudo
    before = (snapshot(stack, normal), snapshot(stack, mitm))
    alice = nodes["alice"]
    for token in (None, normal.token, secrets.token_urlsafe(32), "x"):
        headers = alice.headers()
        if token is None:
            headers.pop("Authorization")
        else:
            headers["Authorization"] = "Bearer " + token
        for call in (lambda: alice.discover(headers=headers),
                     lambda: alice.publish(normal.session_id, stack.get(normal), headers=headers),
                     lambda: alice.ack(normal.session_id, "bob-public", headers=headers),
                     lambda: nodes["mallory"].forward(mitm.session_id, "alice-public", 2, headers=headers)):
            assert_error(call(), 401, "UNAUTHORIZED")
        hb = stack.http.post("/internal/v1/dh/nodes/alice/heartbeat",
                             json={"instance_id": alice.instance}, headers=headers)
        assert_error(hb, 401, "UNAUTHORIZED")
    assert (snapshot(stack, normal), snapshot(stack, mitm)) == before


def test_role_token_cannot_act_as_other_role(pseudo):
    stack, nodes, normal, mitm = pseudo
    before = (snapshot(stack, normal), snapshot(stack, mitm))
    alice, bob, mallory = nodes["alice"], nodes["bob"], nodes["mallory"]
    view_n, view_m = stack.get(normal), stack.get(mitm)

    assert_error(alice.heartbeat(role="bob"), 403, "ROLE_FORBIDDEN")
    assert_error(mallory.heartbeat(role="alice"), 403, "ROLE_FORBIDDEN")
    # Bob nie może opublikować wiadomości Alice (nadawca wynika z roli).
    assert_error(bob.request("POST", f"/sessions/{normal.session_id}/messages", json={
        "message_id": "alice-public", "type": "public_value", "public_value": 8}),
        422, "INVALID_MESSAGE")
    # Mallory nie publikuje i nie potwierdza; Alice/Bob nie przechwytują ani nie podmieniają.
    for mid in ("alice-public", "bob-public"):
        assert_error(mallory.request("POST", f"/sessions/{mitm.session_id}/messages", json={
            "message_id": mid, "type": "public_value", "public_value": 8}), 403, "ROLE_FORBIDDEN")
        assert_error(mallory.ack(mitm.session_id, mid), 403, "ROLE_FORBIDDEN")
    assert_error(mallory.inbox(mitm.session_id), 403, "ROLE_FORBIDDEN")
    for victim in (alice, bob):
        assert_error(victim.interceptions(mitm.session_id), 403, "ROLE_FORBIDDEN")
        assert_error(victim.forward(mitm.session_id, "alice-public", 2), 403, "ROLE_FORBIDDEN")
        assert_error(victim.report_mallory(mitm.session_id, 2, 2), 403, "ROLE_FORBIDDEN")
    assert_error(mallory.report(mitm.session_id, 2), 403, "ROLE_FORBIDDEN")
    # Mallory nie jest przypisana do sesji normal i jej nie widzi.
    for call in (lambda: mallory.interceptions(normal.session_id),
                 lambda: mallory.forward(normal.session_id, "alice-public", 2),
                 lambda: mallory.fail(normal.session_id)):
        assert_error(call(), 403, "ROLE_NOT_ASSIGNED")
    discovered = {r: {d["session_id"] for d in nodes[r].discover().json()["sessions"]} for r in ROLES}
    assert discovered == {"alice": {normal.session_id, mitm.session_id},
                          "bob": {normal.session_id, mitm.session_id},
                          "mallory": {mitm.session_id}}
    # Odbiorca ACK wynika z roli: Alice nie potwierdzi własnej wiadomości.
    assert alice.publish(normal.session_id, view_n).status_code == 200
    assert_error(alice.ack(normal.session_id, "alice-public"), 403, "ROLE_FORBIDDEN")
    after_n = stack.get(normal)
    assert after_n["participants"] == {"alice": "published", "bob": "waiting"}
    assert snapshot(stack, mitm) == before[1]


def test_epoch_instance_and_duplicate_instance_fencing(pseudo):
    stack, nodes, normal, _ = pseudo
    alice = nodes["alice"]
    view = stack.get(normal)
    before = snapshot(stack, normal)
    assert_error(alice.publish(normal.session_id, view, headers=alice.headers(epoch="0" * 32)),
                 409, "BACKEND_EPOCH_MISMATCH")
    assert_error(alice.publish(normal.session_id, view, headers=alice.headers(instance="f" * 32)),
                 409, "NODE_INSTANCE_MISMATCH")
    missing = alice.headers()
    missing.pop("X-Node-Instance")
    assert_error(alice.discover(headers=missing), 400, "BAD_REQUEST")
    # Druga instancja tej samej roli przy żywym lease nie przejmuje roli po cichu.
    duplicate = stack.node("alice")
    assert_error(duplicate.heartbeat(), 409, "NODE_INSTANCE_CONFLICT")
    assert_error(duplicate.discover(headers=duplicate.headers(epoch=alice.epoch)),
                 409, "NODE_INSTANCE_MISMATCH")
    assert snapshot(stack, normal) == before


def test_owner_cannot_perform_node_operations(pseudo):
    stack, _, normal, mitm = pseudo
    before = (snapshot(stack, normal), snapshot(stack, mitm))
    for owned in (normal, mitm):
        for method, suffix, body in (
            ("POST", "/messages", {"message_id": "alice-public", "type": "public_value", "public_value": 8}),
            ("POST", "/messages/bob-public/ack", None),
            ("POST", "/interceptions/alice-public/forward", {"public_value": 2}),
            ("POST", "/diagnostics", {"shared_secret": 2}),
            ("POST", "/fail", {"code": "LOCAL_STATE_LOST"}),
        ):
            public = stack.http.request(method, owned.path + suffix, json=body, headers=owned.auth)
            assert public.status_code in (404, 405), public.text
            internal = stack.http.request(method, "/internal/v1/dh/sessions/" + owned.session_id + suffix,
                                          json=body, headers=owned.auth)
            assert_error(internal, 401, "UNAUTHORIZED")
    assert (snapshot(stack, normal), snapshot(stack, mitm)) == before


def test_node_token_cannot_create_or_control_sessions(pseudo):
    stack, _, normal, _ = pseudo
    before = snapshot(stack, normal)
    for role, token in stack.tokens.items():
        for method, suffix in OWNER_OPERATIONS:
            assert_error(stack.http.request(method, normal.path + suffix, headers=bearer(token)),
                         404, "SESSION_NOT_FOUND")
    assert snapshot(stack, normal) == before


def test_rejected_attacks_do_not_break_protocol(pseudo):
    """Po nieudanych atakach ta sama sesja MITM kończy się poprawnie (pseudo-węzły)."""
    stack, nodes, _, mitm = pseudo
    alice, bob, mallory = nodes["alice"], nodes["bob"], nodes["mallory"]
    sid = mitm.session_id
    view = stack.get(mitm)
    assert_error(bob.publish(sid, view, value=view["prime"]), 422, "INVALID_MESSAGE")
    assert alice.publish(sid, view).status_code == 200
    assert bob.publish(sid, view).status_code == 200
    # Oryginał nie trafia do ofiary przed forward Mallory.
    assert alice.inbox(sid).json()["messages"] == []
    assert_error(alice.ack(sid, "bob-public"), 409, "INTERCEPTION_REQUIRED")
    assert mallory.forward(sid, "alice-public", 3).status_code == 200
    assert_error(mallory.forward(sid, "alice-public", 4), 409, "REPLACEMENT_CONFLICT")
    assert mallory.forward(sid, "bob-public", 5).status_code == 200
    assert alice.inbox(sid).json()["messages"][0]["public_value"] == 5
    assert alice.ack(sid, "bob-public").status_code == 200
    assert bob.ack(sid, "alice-public").status_code == 200
    final = stack.get(mitm)
    assert final["status"] == "completed"
    assert {i["message_id"]: i["delivered_value"] for i in final["interceptions"]} == {
        "alice-public": 3, "bob-public": 5}
