"""#71 / G05, T03: równoległe ponowienia start/publish/forward/ACK/diagnostics.

Duplikaty nie dublują zdarzeń, zmiana treści daje 409 bez częściowego zapisu.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.live


def parallel(count, call):
    with ThreadPoolExecutor(count) as pool:
        return list(pool.map(lambda _: call(), range(count)))


def types(stack, owned):
    return [e["type"] for e in stack.events(owned)]


def test_parallel_start_and_cancel_race(make_stack):
    stack = make_stack(nodes=False, env={"CREATE_RATE_BURST": 4})
    for role in ("alice", "bob"):
        stack.node(role).register()
    owned = stack.create()
    responses = parallel(20, lambda: stack.http.post(owned.path + "/start", headers=owned.auth))
    assert {r.status_code for r in responses} == {200}
    assert types(stack, owned) == ["session_created", "session_started"]

    raced = stack.create()
    calls = [lambda: stack.http.post(raced.path + "/start", headers=raced.auth),
             lambda: stack.http.post(raced.path + "/cancel", headers=raced.auth)] * 10
    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda call: call(), calls))
    final = stack.get(raced)
    assert final["status"] in ("running", "cancelled")
    history = types(stack, raced)
    assert history.count("session_started") <= 1 and history.count("session_cancelled") <= 1
    assert all(r.status_code in (200, 409) for r in results)


def test_parallel_protocol_retries_are_idempotent(make_stack):
    stack = make_stack(nodes=False)
    nodes = {role: stack.node(role).register() for role in ("alice", "bob", "mallory")}
    owned = stack.create("mitm", 467, 2)
    stack.start(owned)
    sid, view = owned.session_id, stack.get(owned)
    alice, bob, mallory = nodes["alice"], nodes["bob"], nodes["mallory"]

    assert {r.status_code for r in parallel(16, lambda: alice.publish(sid, view))} == {200}
    assert {r.status_code for r in parallel(16, lambda: bob.publish(sid, view))} == {200}
    conflicting = alice.publish(sid, view, value=(stack.get(owned)["interceptions"][0]["original_value"] % 466) + 1)
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "MESSAGE_ID_CONFLICT"
    for mid, value in (("alice-public", 3), ("bob-public", 5)):
        assert {r.status_code for r in parallel(16, lambda: mallory.forward(sid, mid, value))} == {200}
    assert {r.status_code for r in parallel(16, lambda: alice.ack(sid, "bob-public"))} == {200}
    assert {r.status_code for r in parallel(16, lambda: bob.ack(sid, "alice-public"))} == {200}
    k_alice = pow(5, alice.secrets[sid], 467)
    assert {r.status_code for r in parallel(16, lambda: alice.report(sid, k_alice))} == {204}
    conflict = alice.report(sid, k_alice % 466 + 1)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "DIAGNOSTIC_CONFLICT"

    history = types(stack, owned)
    assert sorted(history) == sorted([
        "session_created", "session_started", "message_intercepted", "message_intercepted",
        "message_forwarded", "message_forwarded", "message_processed", "message_processed",
        "session_completed"])
    final = stack.get(owned)
    assert final["status"] == "completed"
    assert stack.diagnostics(owned) == {"alice": k_alice, "bob": None}
