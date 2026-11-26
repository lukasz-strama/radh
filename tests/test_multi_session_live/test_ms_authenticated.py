"""Uwierzytelnione sesje na rzeczywistym backendzie i procesach węzłów."""

import json

import pytest

from helpers.multi_session_stack import ROOT, assert_no_secrets_in

pytestmark = pytest.mark.live
RUNNER = (str(ROOT / "tests/helpers/authenticated_node_process.py"),)


def boot(make_stack, env=None):
    stack = make_stack(nodes=False, env=env)
    stack.start_nodes(runner=RUNNER)
    return stack


def start(stack, scenario="authenticated", mode="normal"):
    owned = stack.create(mode, scenario=scenario)
    assert stack.start(owned)["status"] == "running"
    return owned


def complete(stack, owned):
    view = stack.wait_status(owned, "completed", timeout=25)
    assert all(message["status"] == "processed" for message in view["messages"])
    if view["scenario"] == "authenticated":
        assert view["participants"] == {"alice": "verified", "bob": "verified"}
        authentication = view["authentication"]
        for field in ("trusted_keys", "signatures", "verifications"):
            assert len(authentication[field]) == 2
            assert all(item["session_id"] == owned.session_id for item in authentication[field])
            assert all(item["backend_epoch"] == view["backend_epoch"] for item in authentication[field])
        assert all(report["verified"] and report["transcript_hash"] == report["published_transcript_hash"]
                   for report in authentication["verifications"])
    return view


def assert_no_keys(stack, owned):
    assert stack.diagnostics(owned) == {"alice": None, "bob": None}
    assert stack.diagnostics(owned, mallory=True) == {
        "shared_with_alice": None, "shared_with_bob": None,
    }


@pytest.mark.parametrize(("scenario", "mode", "expected"), [
    ("classic", "normal", {"alice": 2, "bob": 2}),
    ("classic", "mitm", {"alice": 12, "bob": 22}),
    ("authenticated", "normal", {"alice": 2, "bob": 2}),
    ("authenticated", "mitm", None),
])
def test_four_protocol_variants_and_data_exposure(make_stack, scenario, mode, expected):
    stack = boot(make_stack)
    owned = start(stack, scenario, mode)
    if expected is not None:
        view = complete(stack, owned)
        assert stack.wait_diagnostics(owned) == expected
    else:
        view = stack.wait_status(owned, "failed", timeout=25)
        assert view["failure_code"] == "SIGNATURE_VERIFICATION_FAILED"
        assert len(view["interceptions"]) == 2
        assert all(item["delivered_value"] != item["original_value"] for item in view["interceptions"])
        assert all(message["status"] != "processed" for message in view["messages"])
        assert_no_keys(stack, owned)
    forbidden_fields = {"d", "p", "q", "phi", "private_exponent", "private_key",
                        "shared_secret", "role_token", "session_token"}

    def fields(obj):
        if isinstance(obj, dict):
            return set(obj).union(*(fields(value) for value in obj.values()))
        if isinstance(obj, list):
            return set().union(*(fields(value) for value in obj))
        return set()

    events = stack.events(owned)
    logs = stack.all_logs()
    assert not forbidden_fields & fields([view, events])
    assert all(f'"{field}"' not in logs for field in forbidden_fields)
    assert_no_secrets_in(logs + json.dumps([view, events]), owned.token, *stack.tokens.values())


@pytest.mark.parametrize("scenarios", [("classic", "authenticated"), ("authenticated", "authenticated")])
def test_concurrent_sessions_have_separate_authentication(make_stack, scenarios):
    stack = boot(make_stack)
    stack.pause("alice")
    try:
        sessions = [start(stack, scenario) for scenario in scenarios]
        assert all(stack.get(owned)["status"] == "running" for owned in sessions)
    finally:
        stack.resume("alice")
    views = [complete(stack, owned) for owned in sessions]
    assert {view["session_id"] for view in views} == {owned.session_id for owned in sessions}
    for owned in sessions:
        assert stack.wait_diagnostics(owned) == {"alice": 2, "bob": 2}
    assert [len(view["authentication"]["trusted_keys"]) for view in views] == [
        2 if scenario == "authenticated" else 0 for scenario in scenarios
    ]


@pytest.mark.parametrize("kind", ["prior_session", "peer"])
def test_context_rejects_a_signature_from_another_session_or_role(make_stack, tmp_path, kind):
    fixture = tmp_path / "published-signature.json"
    stack = boot(make_stack, {"RADH_TEST_SIGNATURE_FIXTURE": str(fixture)})
    config = {"kind": kind}
    if kind == "prior_session":
        prior = start(stack)
        view = complete(stack, prior)
        config["signature"] = next(record for record in view["authentication"]["signatures"]
                                   if record["signer"] == "alice")
    current = stack.create(scenario="authenticated")
    config["session_id"] = current.session_id
    fixture.write_text(json.dumps(config), encoding="ascii")
    stack.start(current)
    failed = stack.wait_status(current, "failed", timeout=25)
    assert failed["failure_code"] == "SIGNATURE_VERIFICATION_FAILED"
    auth = failed["authentication"]
    alice = next(record for record in auth["signatures"] if record["signer"] == "alice")
    original = (config["signature"] if kind == "prior_session"
                else next(record for record in auth["signatures"] if record["signer"] == "bob"))
    assert alice["signature"] == original["signature"]
    assert alice["transcript_hash"] == original["transcript_hash"]
    assert any(report["verified"] is False and report["verifier"] == "bob"
               for report in auth["verifications"])
    assert all(item["status"] != "processed" for item in failed["messages"])
    assert_no_keys(stack, current)


def test_lost_responses_after_real_mutations_are_idempotent(make_stack):
    stack = boot(make_stack, {"RADH_TEST_LOST_RESPONSE_ROLE": "bob"})
    owned = start(stack)
    complete(stack, owned)
    assert stack.wait_diagnostics(owned) == {"alice": 2, "bob": 2}
    log = stack.node_log("bob")
    for stage in ("trusted-keys", "signatures", "verifications", "ack"):
        assert log.count(f"lost response: {stage}") == 1
    types = [event["type"] for event in stack.events(owned)]
    for stage in ("trusted_key_published", "signature_published", "signature_verified", "message_processed"):
        assert types.count(stage) == 2
    assert types.count("session_completed") == 1


def test_participant_restart_cannot_resume_previous_authentication(make_stack):
    stack = boot(make_stack, {"CLEANUP_SECONDS": "1"})
    stack.pause("bob")
    try:
        owned = start(stack)
        stack.wait_for(lambda: stack.get(owned),
                       lambda view: bool(view["authentication"]["trusted_keys"]))
        stack.stop_node("alice", kill=True)
    finally:
        stack.resume("bob")
    failed = stack.wait_status(owned, "failed", timeout=15)
    assert failed["failure_code"] in ("NODE_RESTARTED", "NODE_UNAVAILABLE")
    assert_no_keys(stack, owned)
    stack.start_node("alice", runner=RUNNER)
    stack.wait_online(("alice",))
    complete(stack, start(stack))
    assert stack.get(owned) == failed


def test_epoch_change_drops_previous_authentication(make_stack):
    stack = boot(make_stack)
    stack.pause("bob")
    try:
        owned = start(stack)
        old_epoch = stack.epoch()
        stack.wait_for(lambda: stack.get(owned),
                       lambda view: bool(view["authentication"]["trusted_keys"]))
        stack.restart_backend()
    finally:
        stack.resume("bob")
    assert stack.epoch() != old_epoch
    assert stack.http.get(owned.path, headers=owned.auth).status_code == 404
    stack.wait_online(timeout=25)
    complete(stack, start(stack))


def test_cancel_while_roles_are_authenticating(make_stack):
    stack = boot(make_stack)
    stack.pause("bob")
    try:
        owned = start(stack)
        stack.wait_for(lambda: stack.get(owned),
                       lambda view: bool(view["authentication"]["trusted_keys"]))
        response = stack.http.post(owned.path + "/cancel", headers=owned.auth)
        assert response.status_code == 200
        cancelled = response.json()
    finally:
        stack.resume("bob")
    complete(stack, start(stack))
    assert stack.get(owned) == cancelled
    assert_no_keys(stack, owned)
