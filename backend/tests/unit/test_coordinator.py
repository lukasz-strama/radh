"""Testy jednostkowe rejestru z zegarem i bez sieci, procesów oraz biblioteki C."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from pydantic import ValidationError

from app.coordinator import Coordinator
from app.coordinator_limits import CoordinatorError, Settings
from app.multi_models import Create, Publish, Report, MalloryReport


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def utc(self):
        return datetime(2026, 11, 18, tzinfo=timezone.utc) + timedelta(seconds=self.now)


@pytest.fixture
def system():
    clock = Clock()
    return Coordinator(clock=clock, utc=clock.utc), clock


def create(c, mode="normal", diagnostics=True, key=None, ip="127.0.0.1"):
    return c.create(Create(prime=23, generator=5, mode=mode,
                           diagnostics_enabled=diagnostics),
                    key or secrets.token_urlsafe(32), c.epoch, ip)


def register(c):
    instances = {role: ("%032x" % (index + 1)) for index, role in enumerate(("alice", "bob", "mallory"))}
    for role, instance in instances.items():
        c.heartbeat(role, instance)
    return instances


def start(c, created):
    return c.transition(created.session.session_id, created.session_token, "start")


def node(c, created, instances, role, method, *args):
    with c.access(created.session.session_id, role=role, epoch=c.epoch,
                  instance=instances[role]) as record:
        return getattr(c, method)(record, role, *args)


def publish(c, created, instances, role, value):
    return node(c, created, instances, role, "publish", Publish(
        message_id=role + "-public", type="public_value", public_value=value,
    ))


def error(code, fn, *args, status=None):
    with pytest.raises(CoordinatorError) as caught:
        fn(*args)
    assert caught.value.code == code
    if status:
        assert caught.value.status == status
    return caught.value


@pytest.mark.parametrize("field", ["prime", "generator", "diagnostics_enabled"])
@pytest.mark.parametrize("value", [None, "5", 5.0, [], {}])
def test_strict_create_types(field, value):
    with pytest.raises(ValidationError):
        Create(**{**dict(prime=23, generator=5), field: value})


def test_parallel_normal_and_mitm_are_independent(system):
    c, _ = system
    instances = register(c)
    normal, attack = create(c), create(c, "mitm")
    start(c, normal)
    start(c, attack)
    for created in (normal, attack):
        publish(c, created, instances, "alice", 8)
        publish(c, created, instances, "bob", 19)
    assert node(c, attack, instances, "alice", "inbox").messages == []
    node(c, attack, instances, "mallory", "forward", "alice-public", 22)
    node(c, attack, instances, "mallory", "forward", "bob-public", 17)
    assert node(c, normal, instances, "alice", "inbox").messages[0].public_value == 19
    assert node(c, attack, instances, "alice", "inbox").messages[0].public_value == 17
    for created in (normal, attack):
        node(c, created, instances, "alice", "acknowledge", "bob-public")
        node(c, created, instances, "bob", "acknowledge", "alice-public")
        assert c.get(created.session.session_id, created.session_token).status == "completed"
    node(c, normal, instances, "alice", "report", Report(shared_secret=2))
    node(c, attack, instances, "alice", "report", Report(shared_secret=12))
    node(c, attack, instances, "mallory", "report", MalloryReport(shared_with_alice=12, shared_with_bob=22))
    assert c.diagnostics(normal.session.session_id, normal.session_token).alice == 2
    assert c.diagnostics(attack.session.session_id, attack.session_token).alice == 12
    assert all("shared_secret" not in e.model_dump() for e in c.events(
        attack.session.session_id, attack.session_token).events)


def test_foreign_owner_cannot_read_start_cancel_delete_or_diagnostics(system):
    c, _ = system
    target, other = create(c), create(c)
    sid = target.session.session_id
    for operation in (c.get, c.delete, c.events, c.diagnostics):
        error("SESSION_NOT_FOUND", operation, sid, other.session_token, status=404)
    for action in ("start", "cancel"):
        error("SESSION_NOT_FOUND", c.transition, sid, other.session_token, action)
    assert c.get(sid, target.session_token).status == "created"


def test_create_retry_conflict_expiry_delete_and_secret_isolation(system):
    c, clock = system
    key = secrets.token_urlsafe(32)
    request = Create(prime=23, generator=5)
    first = c.create(request, key, c.epoch, "ip")
    second = c.create(request, key, c.epoch, "ip")
    assert first == second
    assert len(c.records) == 1
    assert first.session_token not in repr(first)
    changed = request.model_copy(update={"generator": 2})
    error("IDEMPOTENCY_CONFLICT", c.create, changed, key, c.epoch, "ip")
    second.session.messages.clear()
    assert not c.get(first.session.session_id, first.session_token).messages
    clock.now = 60
    error("CREATE_RETRY_EXPIRED", c.create, request, key, c.epoch, "ip")
    c.delete(first.session.session_id, first.session_token)
    error("CREATION_GONE", c.create, request, key, c.epoch, "ip")
    c.delete(first.session.session_id, first.session_token)
    error("SESSION_EXPIRED", c.get, first.session.session_id, first.session_token)
    error("SESSION_NOT_FOUND", c.get, first.session.session_id, secrets.token_urlsafe(32))
    clock.now += 600
    error("SESSION_NOT_FOUND", c.get, first.session.session_id, first.session_token)


def test_cancel_does_not_touch_other_sessions_and_late_retry_is_rejected(system):
    c, _ = system
    instances = register(c)
    first, second = create(c), create(c)
    start(c, first)
    start(c, second)
    publish(c, first, instances, "alice", 8)
    c.transition(first.session.session_id, first.session_token, "cancel")
    error("INVALID_SESSION_STATE", publish, c, first, instances, "alice", 8)
    assert publish(c, second, instances, "alice", 8).status == "queued"


def test_idempotent_protocol_and_conflicts_are_atomic(system):
    c, _ = system
    instances = register(c)
    created = create(c, "mitm")
    start(c, created)
    publish(c, created, instances, "alice", 8)
    publish(c, created, instances, "bob", 19)
    node(c, created, instances, "mallory", "forward", "alice-public", 22)
    # Retry publikacji odpowiada stanem wiadomości doręczanej po podmianie.
    assert publish(c, created, instances, "alice", 8).public_value == 22
    error("MESSAGE_ID_CONFLICT", publish, c, created, instances, "alice", 9)
    error("REPLACEMENT_CONFLICT", node, c, created, instances, "mallory", "forward", "alice-public", 21)
    node(c, created, instances, "mallory", "forward", "bob-public", 17)
    for role, mid in (("alice", "bob-public"), ("bob", "alice-public")):
        node(c, created, instances, role, "acknowledge", mid)
    before = c.get(created.session.session_id, created.session_token)
    node(c, created, instances, "alice", "acknowledge", "bob-public")
    node(c, created, instances, "mallory", "forward", "alice-public", 22)
    publish(c, created, instances, "alice", 8)
    assert c.get(created.session.session_id, created.session_token) == before
    node(c, created, instances, "alice", "report", Report(shared_secret=12))
    node(c, created, instances, "alice", "report", Report(shared_secret=12))
    error("DIAGNOSTIC_CONFLICT", node, c, created, instances, "alice", "report", Report(shared_secret=13))


def test_restart_epoch_role_assignment_and_lease_fencing(system):
    c, clock = system
    instances = register(c)
    created = create(c)
    start(c, created)
    error("NODE_INSTANCE_CONFLICT", c.heartbeat, "alice", "a" * 32)
    error("BACKEND_EPOCH_MISMATCH", c.discover, "alice", "f" * 32, instances["alice"])
    error("NODE_INSTANCE_MISMATCH", c.discover, "alice", c.epoch, "f" * 32)
    error("ROLE_NOT_ASSIGNED", node, c, created, instances, "mallory", "interceptions")
    clock.now = 10
    c.heartbeat("alice", "a" * 32)
    view = c.get(created.session.session_id, created.session_token)
    assert (view.status, view.failure_code) == ("failed", "NODE_RESTARTED")
    error("NODE_INSTANCE_MISMATCH", c.discover, "alice", c.epoch, instances["alice"])
    assert Coordinator().epoch != c.epoch


def test_polling_and_retries_do_not_extend_progress_deadline(system):
    c, clock = system
    instances = register(c)
    created = create(c)
    start(c, created)
    publish(c, created, instances, "alice", 8)
    for time in (9, 18, 27):
        clock.now = time
        register(c)
        c.get(created.session.session_id, created.session_token)
        publish(c, created, instances, "alice", 8)
    clock.now = 30
    c.cleanup()
    view = c.get(created.session.session_id, created.session_token)
    assert (view.status, view.failure_code) == ("failed", "PARTICIPANT_TIMEOUT")


def test_expired_retention_and_delete_use_monotonic_clock(system):
    c, clock = system
    created = create(c)
    sid, token = created.session.session_id, created.session_token
    clock.now = 120
    assert c.get(sid, token).status == "expired"
    assert c.diagnostics(sid, token).model_dump() == {"alice": None, "bob": None}
    for action in ("start", "cancel"):
        error("INVALID_SESSION_STATE", c.transition, sid, token, action)
    clock.now = 419
    assert c.get(sid, token).status == "expired"
    clock.now = 420
    error("SESSION_EXPIRED", c.get, sid, token)
    error("SESSION_NOT_FOUND", c.get, sid, secrets.token_urlsafe(32))
    c.delete(sid, token)


def test_completed_diagnostics_deadline_is_visible_to_nodes(system):
    c, clock = system
    instances = register(c)
    created = create(c)
    start(c, created)
    for role, value in (("alice", 8), ("bob", 19)):
        publish(c, created, instances, role, value)
    node(c, created, instances, "alice", "acknowledge", "bob-public")
    node(c, created, instances, "bob", "acknowledge", "alice-public")
    clock.now = 5
    register(c)
    assert c.discover("alice", c.epoch, instances["alice"]).sessions[0].remaining_ttl_seconds == 25
    clock.now = 30
    register(c)
    error("INVALID_SESSION_STATE", node, c, created, instances, "alice", "report", Report(shared_secret=2))


def test_event_capacity_rejects_before_partial_mutation():
    c = Coordinator(Settings(max_events=4))
    instances = register(c)
    created = create(c)
    start(c, created)
    publish(c, created, instances, "alice", 8)
    before = c.get(created.session.session_id, created.session_token)
    error("EVENT_LIMIT_REACHED", publish, c, created, instances, "bob", 19)
    assert c.get(created.session.session_id, created.session_token) == before
    c.transition(created.session.session_id, created.session_token, "cancel")
    assert len(c.events(created.session.session_id, created.session_token).events) == 4


def test_session_running_ip_and_retry_capacities():
    c = Coordinator(Settings(max_sessions=2, max_running_sessions=1, max_sessions_per_ip=1))
    instances = register(c)
    first = create(c, ip="one")
    error("RATE_LIMITED", create, c, "normal", True, None, "one")
    second = create(c, ip="two")
    error("SESSION_CAPACITY", create, c, "normal", True, None, "three")
    start(c, first)
    error("RUNNING_CAPACITY", start, c, second)
    c.transition(first.session.session_id, first.session_token, "cancel")
    assert start(c, second).status == "running"
    limited = Coordinator(Settings(max_create_retries=1))
    create(limited)
    error("SESSION_CAPACITY", create, limited)


def test_concurrent_creation_and_publication_are_idempotent(system):
    c, _ = system
    key = secrets.token_urlsafe(32)
    barrier = Barrier(4)

    def concurrent_create(_):
        barrier.wait()
        return create(c, key=key)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(concurrent_create, range(4)))
    assert len({r.session.session_id for r in results}) == 1
    assert len({r.session_token for r in results}) == 1
    instances = register(c)
    created = results[0]
    start(c, created)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: publish(c, created, instances, "alice", 8), range(4)))
    assert len(c.events(created.session.session_id, created.session_token).events) == 3


def test_discovery_excludes_normal_sessions_from_mallory(system):
    c, _ = system
    instances = register(c)
    normal, attack = create(c), create(c, "mitm")
    start(c, normal)
    start(c, attack)
    result = c.discover("mallory", c.epoch, instances["mallory"])
    assert [d.session_id for d in result.sessions] == [attack.session.session_id]
    assert result.sessions[0].participant_status is None
    assert "session_token" not in result.model_dump_json()


@pytest.mark.parametrize("mode", ["normal", "mitm"])
def test_ack_requires_own_public_value_and_routing(mode, system):
    c, _ = system
    instances = register(c)
    created = create(c, mode)
    start(c, created)
    publish(c, created, instances, "alice", 8)
    error("ROLE_FORBIDDEN", node, c, created, instances, "alice", "acknowledge", "alice-public")
    if mode == "mitm":
        error("INTERCEPTION_REQUIRED", node, c, created, instances, "bob", "acknowledge", "alice-public")
        node(c, created, instances, "mallory", "forward", "alice-public", 22)
    error("PUBLIC_VALUE_REQUIRED", node, c, created, instances, "bob", "acknowledge", "alice-public")
    assert c.get(created.session.session_id, created.session_token).participants.bob == "waiting"


def test_absolute_expiry_clears_completed_data_only_after_retention(system):
    c, clock = system
    instances = register(c)
    created = create(c)
    start(c, created)
    for role, value in (("alice", 8), ("bob", 19)):
        publish(c, created, instances, role, value)
    node(c, created, instances, "alice", "acknowledge", "bob-public")
    node(c, created, instances, "bob", "acknowledge", "alice-public")
    node(c, created, instances, "alice", "report", Report(shared_secret=2))
    clock.now = 299
    assert c.diagnostics(created.session.session_id, created.session_token).alice == 2
    clock.now = 300
    error("SESSION_EXPIRED", c.get, created.session.session_id, created.session_token)
    assert not c.records and not c.retries


def test_timeout_of_lease_fails_only_assigned_running_sessions(system):
    c, clock = system
    instances = register(c)
    first, second = create(c), create(c)
    start(c, first)
    clock.now = 10
    c.cleanup()
    assert c.get(first.session.session_id, first.session_token).failure_code == "NODE_UNAVAILABLE"
    assert c.get(second.session.session_id, second.session_token).status == "created"


def test_failure_retries_and_snapshot_mutation_are_safe(system):
    c, _ = system
    instances = register(c)
    created = create(c)
    start(c, created)
    snapshot = c.get(created.session.session_id, created.session_token)
    snapshot.participants.alice = "received"
    assert c.get(snapshot.session_id, created.session_token).participants.alice == "waiting"
    with c.access(snapshot.session_id, role="alice", epoch=c.epoch, instance=instances["alice"]) as record:
        first = c.fail(record, "CRYPTO_CORE_ERROR")
        assert c.fail(record, "CRYPTO_CORE_ERROR") == first
        error("INVALID_SESSION_STATE", c.fail, record, "LOCAL_STATE_LOST")


def test_event_pagination_is_per_session_and_returns_copies(system):
    c, _ = system
    created = create(c)
    result = c.events(created.session.session_id, created.session_token, 0, 1)
    assert result.next_after == 1 and result.events[0].sequence == 1
    result.events[0].type = "session_failed"
    assert c.events(created.session.session_id, created.session_token).events[0].type == "session_created"
    empty = c.events(created.session.session_id, created.session_token, 9, 1)
    assert empty.next_after == 9 and not empty.events


def test_tombstones_are_bounded(system):
    c, _ = system
    c.settings = Settings(max_tombstones=1)
    first, second = create(c), create(c)
    c.delete(first.session.session_id, first.session_token)
    c.delete(second.session.session_id, second.session_token)
    assert len(c.tombstones) == 1
    error("SESSION_NOT_FOUND", c.get, first.session.session_id, first.session_token)
    error("SESSION_EXPIRED", c.get, second.session.session_id, second.session_token)


def test_disabled_diagnostics_never_accept_secret(system):
    c, _ = system
    instances = register(c)
    created = create(c, diagnostics=False)
    start(c, created)
    error("DIAGNOSTICS_DISABLED", node, c, created, instances, "alice", "report", Report(shared_secret=2))
    assert c.diagnostics(created.session.session_id, created.session_token).alice is None
