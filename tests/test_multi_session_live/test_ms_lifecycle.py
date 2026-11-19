"""#71 / G03, G06, G10: anulowanie, wygasanie, retencja, awarie i restarty.

Kryterium: anulowanie jednej sesji nie przerywa pozostałych; testy wygaszania
przechodzą. Krótkie TTL to wyłącznie konfiguracja testowa (zmienne Settings).
"""

import time

import pytest

from helpers.multi_session_stack import expected_keys

pytestmark = pytest.mark.live

SHORT_TTL = {"SESSION_CREATED_TTL_SECONDS": 2, "SESSION_RETENTION_SECONDS": 3,
             "TOMBSTONE_TTL_SECONDS": 3, "CLEANUP_SECONDS": 1}


def code(response):
    return response.status_code, response.json()["error"]["code"]


def test_cancel_one_running_session_does_not_stop_others(make_stack):
    """Bob wstrzymany (SIGSTOP) — trzy sesje utkną w running; anulujemy środkową."""
    stack = make_stack(env={"CREATE_RATE_BURST": 4})
    sessions = [stack.create("normal", 467, 2), stack.create("mitm", 479, 13),
                stack.create("normal", 487, 3)]
    stack.pause("bob")
    try:
        for owned in sessions:
            stack.start(owned)
        for owned in sessions:
            stack.wait_for(lambda o=owned: stack.get(o), lambda v: v["participants"]["alice"] == "published")
        cancelled = stack.http.post(sessions[1].path + "/cancel", headers=sessions[1].auth)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        # Idempotentne ponowienie anulowania; start po anulowaniu jest odrzucany.
        assert stack.http.post(sessions[1].path + "/cancel", headers=sessions[1].auth).json()["status"] == "cancelled"
        assert code(stack.http.post(sessions[1].path + "/start", headers=sessions[1].auth)) == (
            409, "INVALID_SESSION_STATE")
    finally:
        stack.resume("bob")

    for owned in (sessions[0], sessions[2]):
        view = stack.wait_status(owned, "completed")
        assert stack.wait_diagnostics(owned) == expected_keys(view)
    time.sleep(2)  # czas na ewentualny spóźniony zapis Boba do anulowanej sesji
    view = stack.get(sessions[1])
    assert view["status"] == "cancelled" and view["participants"]["bob"] == "waiting"
    assert stack.events(sessions[1])[-1]["type"] == "session_cancelled"
    assert stack.diagnostics(sessions[1]) == {"alice": None, "bob": None}
    assert stack.diagnostics(sessions[1], mallory=True) == {"shared_with_alice": None, "shared_with_bob": None}
    assert code(stack.http.post(sessions[0].path + "/cancel", headers=sessions[0].auth)) == (
        409, "INVALID_SESSION_STATE")
    # Procesy nadal obsługują nowe sesje po anulowaniu.
    fresh = stack.create("mitm", 503, 5)
    stack.start(fresh)
    assert stack.wait_status(fresh, "completed")["mode"] == "mitm"


def test_created_session_expires_then_tombstone_then_404(make_stack):
    stack = make_stack(env=SHORT_TTL, nodes=False)
    owned = stack.create("normal", 23, 5)
    keep = stack.create("normal", 23, 5)
    view = stack.wait_status(owned, "expired", timeout=8)
    assert view["terminal_at"] is not None
    assert stack.diagnostics(owned) == {"alice": None, "bob": None}
    assert stack.events(owned)[-1]["type"] == "session_expired"
    for action in ("start", "cancel"):
        assert code(stack.http.post(owned.path + "/" + action, headers=owned.auth)) == (
            409, "INVALID_SESSION_STATE")
    # Właściciel może usunąć istniejącą expired (204) — druga sesja to pokazuje.
    stack.wait_status(keep, "expired", timeout=8)
    assert stack.http.delete(keep.path, headers=keep.auth).status_code == 204
    assert code(stack.http.get(keep.path, headers=keep.auth)) == (410, "SESSION_EXPIRED")
    # Odczyt nie przedłuża TTL: po retencji pierwsza znika, zostaje tombstone (410).
    stack.wait_for(lambda: stack.http.get(owned.path, headers=owned.auth).status_code,
                   lambda status: status == 410, timeout=10)
    assert stack.http.delete(owned.path, headers=owned.auth).status_code == 204
    stack.wait_for(lambda: stack.http.get(owned.path, headers=owned.auth).status_code,
                   lambda status: status == 404, timeout=10)
    assert code(stack.http.delete(owned.path, headers=owned.auth)) == (404, "SESSION_NOT_FOUND")


def test_completed_session_retention_removes_keys(make_stack):
    stack = make_stack(env={"SESSION_RETENTION_SECONDS": 3, "TOMBSTONE_TTL_SECONDS": 3,
                            "CLEANUP_SECONDS": 1})
    owned = stack.create("normal", 467, 2)
    stack.start(owned)
    view = stack.wait_status(owned, "completed")
    assert stack.wait_diagnostics(owned) == expected_keys(view)
    stack.wait_for(lambda: stack.http.get(owned.path + "/diagnostics", headers=owned.auth).status_code,
                   lambda status: status == 410, timeout=10)
    assert code(stack.http.get(owned.path, headers=owned.auth)) == (410, "SESSION_EXPIRED")


def test_participant_timeout_fails_only_stalled_session(make_stack):
    """Pseudo-węzły: sesja bez postępu → failed PARTICIPANT_TIMEOUT, druga trwa."""
    stack = make_stack(env={"PARTICIPANT_TIMEOUT_SECONDS": 3, "CLEANUP_SECONDS": 1}, nodes=False)
    alice, bob = stack.node("alice").register(), stack.node("bob").register()
    stalled, progressing = stack.create("normal", 23, 5), stack.create("normal", 467, 2)
    stack.start(stalled)
    stack.start(progressing)
    sid, view = progressing.session_id, stack.get(progressing)
    # Sesja z postępem co <3 s trwa i kończy się mimo awarii sąsiedniej.
    assert alice.publish(sid, view).status_code == 200
    time.sleep(2)
    assert bob.publish(sid, view).status_code == 200
    failed = stack.wait_status(stalled, "failed", timeout=8)
    assert failed["failure_code"] == "PARTICIPANT_TIMEOUT"
    assert stack.get(progressing)["status"] == "running"
    assert alice.ack(sid, "bob-public").status_code == 200
    assert bob.ack(sid, "alice-public").status_code == 200
    assert stack.get(progressing)["status"] == "completed"
    # Spóźniony zapis do failed nie zmienia stanu.
    assert code(alice.publish(stalled.session_id, failed)) == (409, "INVALID_SESSION_STATE")
    assert stack.get(stalled)["participants"] == {"alice": "waiting", "bob": "waiting"}


def test_running_session_absolute_age_expires_and_erases_keys(make_stack):
    stack = make_stack(env={"SESSION_MAX_AGE_SECONDS": 4, "CLEANUP_SECONDS": 1}, nodes=False)
    alice, bob = stack.node("alice").register(), stack.node("bob").register()
    owned = stack.create("normal", 467, 2)
    stack.start(owned)
    sid, view = owned.session_id, stack.get(owned)
    assert alice.publish(sid, view).status_code == 200
    assert bob.publish(sid, view).status_code == 200
    assert alice.ack(sid, "bob-public").status_code == 200
    bob_value = next(m for m in stack.get(owned)["messages"] if m["sender"] == "bob")["public_value"]
    k_alice = pow(bob_value, alice.secrets[sid], 467)
    assert alice.report(sid, k_alice).status_code == 204
    assert stack.diagnostics(owned)["alice"] == k_alice
    expired = stack.wait_status(owned, "expired", timeout=8)
    assert expired["failure_code"] is None
    assert stack.diagnostics(owned) == {"alice": None, "bob": None}
    assert code(bob.ack(sid, "alice-public")) == (409, "INVALID_SESSION_STATE")
    assert code(alice.report(sid, k_alice)) == (409, "INVALID_SESSION_STATE")
    assert stack.http.delete(owned.path, headers=owned.auth).status_code == 204


def test_mallory_outage_fails_only_mitm_session(make_stack):
    """Wstrzymana Mallory traci lease → MITM failed NODE_UNAVAILABLE; normal działa."""
    stack = make_stack(env={"CREATE_RATE_BURST": 4, "CLEANUP_SECONDS": 1})
    mitm = stack.create("mitm", 467, 2)
    stack.pause("mallory")
    try:
        stack.start(mitm)
        stack.wait_for(lambda: stack.get(mitm),
                       lambda v: all(i["status"] == "pending" for i in v["interceptions"])
                       and len(v["interceptions"]) == 2)
        normal = stack.create("normal", 479, 13)
        stack.start(normal)
        assert stack.wait_status(normal, "completed")["status"] == "completed"
        failed = stack.wait_status(mitm, "failed", timeout=16)
        assert failed["failure_code"] == "NODE_UNAVAILABLE"
        assert stack.presence()["mallory"]["online"] is False
        blocked = stack.create("mitm", 487, 3)
        assert code(stack.http.post(blocked.path + "/start", headers=blocked.auth)) == (
            409, "NODE_UNAVAILABLE")
        assert stack.get(blocked)["status"] == "created"
    finally:
        stack.resume("mallory")


def test_node_restart_fails_old_sessions_and_new_instance_serves_new_ones(make_stack):
    """G10: nowa instancja Alice nie przejmuje running starej instancji.

    Restart w czasie lease (10 s) daje 409 NODE_INSTANCE_CONFLICT i proces #68
    kończy się kodem 1 (zachowanie zachowawcze; restart wykonuje nadzorca).
    """
    stack = make_stack(env={"CLEANUP_SECONDS": 1})
    owned = stack.create("normal", 467, 2)
    stack.pause("alice")
    stack.start(owned)
    stack.wait_for(lambda: stack.get(owned), lambda v: v["participants"]["bob"] == "published")
    stack.stop_node("alice", kill=True)

    duplicate = stack.start_node("alice")
    stack.nodes.pop("alice")
    assert duplicate.wait(timeout=10) == 1
    assert stack.get(owned)["status"] == "running"

    failed = stack.wait_status(owned, "failed", timeout=15)
    assert failed["failure_code"] == "NODE_UNAVAILABLE"
    assert failed["participants"]["alice"] == "waiting"
    stack.start_node("alice")
    stack.wait_online(("alice",), timeout=30)
    fresh = stack.create("normal", 479, 13)
    stack.start(fresh)
    view = stack.wait_status(fresh, "completed", timeout=25)
    assert stack.wait_diagnostics(fresh) == expected_keys(view)
    assert stack.get(owned)["status"] == "failed"


def test_backend_restart_changes_epoch_and_drops_sessions(make_stack):
    """G10: restart backendu → nowy epoch, stare ID 404, stary epoch odrzucany."""
    stack = make_stack(env={"CREATE_RATE_BURST": 4})
    before = stack.create("normal", 467, 2)
    stack.start(before)
    stack.wait_status(before, "completed")
    old_epoch = stack.epoch()
    stack.restart_backend()
    assert stack.epoch() != old_epoch
    assert code(stack.http.get(before.path, headers=before.auth)) == (404, "SESSION_NOT_FOUND")
    stale = stack.create_raw({"prime": 23, "generator": 5}, epoch=old_epoch)
    assert code(stale) == (409, "BACKEND_EPOCH_MISMATCH")
    # Restart gubi cache tworzenia: ten sam klucz z nowym epoch to nowa sesja,
    # nigdy stara odpowiedź/token (#73 §2 — brak obietnicy exactly-once).
    replay = stack.create_raw({"prime": 467, "generator": 2, "mode": "normal",
                               "diagnostics_enabled": True}, key=before.create_key)
    assert replay.status_code == 201
    assert replay.json()["session"]["session_id"] != before.session_id
    assert replay.json()["session_token"] != before.token
    stack.wait_online(timeout=30)
    after = stack.create("mitm", 479, 13)
    stack.start(after)
    view = stack.wait_status(after, "completed", timeout=25)
    assert stack.wait_diagnostics(after) == expected_keys(view)
