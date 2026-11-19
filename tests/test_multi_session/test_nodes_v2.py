"""Komponentowy koordynator internal; matematyka pozostaje w rzeczywistym C."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from nodes.internal_http import EpochChanged, InternalError
from nodes.multi_session import MultiSessionTransport, StaleEntry
from nodes.testing import DeterministicDhNode, DeterministicMalloryNode

EPOCH = 'a' * 32
SID = '1' * 32


def descriptor(sid=SID, mode='normal', **changes):
    result = dict(session_id=sid, backend_epoch=EPOCH, prime=23, generator=5,
                  mode=mode, diagnostics_enabled=True, status='running', revision=1,
                  expires_at='2030-01-01T00:00:00Z', remaining_ttl_seconds=600,
                  participant_status='waiting', diagnostics_received=False)
    result.update(changes)
    return result


class Coordinator:
    def __init__(self, role='alice', sessions=None):
        self.role, self.instance_id = role, 'c' * 32
        self.epoch = EPOCH
        self.sessions = sessions or [descriptor()]
        if role == 'mallory':
            for d in self.sessions:
                d.update(mode='mitm', participant_status=None)
        self.calls = []
        self.lost = set()
        self.mutate = None
        self.diagnostics = {}
        self.acks = set()
        self.publications = {}
        self.forwards = {}

    def request(self, method, path, epoch, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if self.mutate:
            callback, self.mutate = self.mutate, None
            callback()
        if path.endswith('/heartbeat'):
            return dict(backend_epoch=self.epoch, instance_id=self.instance_id, lease_seconds=10), self.epoch
        if epoch != self.epoch:
            raise EpochChanged()
        if path == '/internal/v1/dh/sessions':
            return dict(backend_epoch=self.epoch, sessions=deepcopy(self.sessions), retry_after_ms=1000), self.epoch
        sid = path.split('/')[5]
        base = dict(session_id=sid, backend_epoch=self.epoch, revision=1)
        if '/diagnostics' in path:
            self.diagnostics[(self.role, sid)] = deepcopy(body)
            result = None
        elif path.endswith('/fail'):
            result = dict(**base, prime=23, generator=5, mode='normal',
                          diagnostics_enabled=True, status='failed', failure_code=body['code'],
                          created_at='2030-01-01T00:00:00Z', expires_at='2030-01-01T00:00:00Z',
                          terminal_at='2030-01-01T00:00:01Z', participants={'alice':'waiting','bob':'waiting'},
                          messages=[], interceptions=[])
        elif '/interceptions' in path:
            def item(sender):
                mid = sender + '-public'
                value = self.forwards.get((sid, mid))
                return dict(message_id=mid, original_sender=sender,
                            recipient='bob' if sender == 'alice' else 'alice',
                            original_value=8 if sender == 'alice' else 19,
                            delivered_value=value, intercepted_by='mallory',
                            actual_sender='mallory' if value else None,
                            status='forwarded' if value else 'pending')
            if method == 'GET':
                result = dict(**base, interceptions=[item('bob'), item('alice')])
            else:
                mid = path.split('/')[-2]
                self.forwards[(sid, mid)] = body['public_value']
                result = item(mid.split('-')[0])
        else:
            peer = 'bob' if self.role == 'alice' else 'alice'
            own = method == 'POST' and path.endswith('/messages')
            sender = self.role if own else peer
            value = body['public_value'] if own else (19 if peer == 'bob' else 8)
            message = dict(message_id=sender+'-public', sender=sender,
                           recipient=peer if own else self.role, type='public_value', public_value=value,
                           status='processed' if path.endswith('/ack') else 'queued')
            if own:
                self.publications[(sid, self.role)] = body['public_value']
                result = message
            elif path.endswith('/ack'):
                self.acks.add(sid)
                for d in self.sessions:
                    if d['session_id'] == sid:
                        d['participant_status'] = 'received'
                result = message
            else:
                result = dict(**base, messages=[] if sid in self.acks else [message])
        suffix = next((s for s in self.lost if path.endswith(s)), None)
        if suffix:
            self.lost.remove(suffix)
            raise InternalError()
        return result, self.epoch


def transport(role='alice', sessions=None, **options):
    mock = Coordinator(role, sessions)
    factory = (lambda: DeterministicMalloryNode(7, 11)) if role == 'mallory' else (
        lambda: DeterministicDhNode(role, 6 if role == 'alice' else 15))
    node = MultiSessionTransport(mock, factory=factory, allow_diagnostics=True, **options)
    node.heartbeat()
    node.discover()
    return node, mock


def entry(node, sid=SID):
    return node.entries[(node.epoch, sid)]


@pytest.mark.parametrize('role', ['alice', 'bob', 'mallory'])
def test_two_parallel_sessions_real_c(role):
    node, mock = transport(role, [descriptor(), descriptor('2'*32)])
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(node.work, list(node.entries.values())))
    agents = [e.node for e in node.entries.values()]
    assert agents[0] is not agents[1]
    assert len(mock.diagnostics) == 2
    for report in mock.diagnostics.values():
        assert report == (dict(shared_with_alice=12, shared_with_bob=22)
                          if role == 'mallory' else dict(shared_secret=2))
    assert len(mock.forwards) == 4 if role == 'mallory' else len(mock.publications) == 2
    for _, _, body in mock.calls:
        assert not (set(body or {}) & {'secret', 'x', 'y', 'alice_secret', 'bob_secret'})


def test_normal_and_mitm_discovery_keeps_agents():
    node, mock = transport(sessions=[descriptor(), descriptor('2'*32, 'mitm')])
    for e in node.entries.values():
        node.work(e)
    original = entry(node).node
    node.discover()
    assert entry(node).node is original
    assert len(node.entries) == 2
    mock.sessions = [mock.sessions[1]]
    node.discover()
    assert len(node.entries) == 1
    assert entry(node, '2'*32).node is not original


@pytest.mark.parametrize('role,suffix', [('alice','/messages'), ('alice','/ack'), ('mallory','/forward'), ('alice','/diagnostics')])
def test_lost_response_retry_preserves_secret(role, suffix):
    node, mock = transport(role)
    mock.lost.add(suffix)
    e = entry(node)
    node.work(e)
    original = e.node
    node.discover()
    node.work(e)
    assert e.node is original
    assert len(mock.diagnostics) == 1
    assert e.diagnostics_sent


def test_lost_last_ack_after_completion():
    node, mock = transport()
    mock.lost.add('/ack')
    node.work(entry(node))
    mock.sessions[0].update(status='completed', participant_status='received')
    node.discover()
    node.work(entry(node))
    assert entry(node).diagnostics_sent


def test_capacity_no_overwrite():
    node, mock = transport(sessions=[descriptor(), descriptor('2'*32)], max_agents=1)
    first, second = node.entries.values()
    node.work(first)
    original = first.node
    assert second.failure == 'NODE_CAPACITY'
    node.work(second)
    assert first.node is original and second.node is None
    assert any(path.endswith('/fail') and body == {'code': 'NODE_CAPACITY'} for _,path,body in mock.calls)


def test_epoch_and_late_response():
    node, mock = transport()
    old = entry(node)
    mock.mutate = lambda: (setattr(mock, 'epoch', 'b'*32))
    node.work(old)
    assert not node.entries and not node.registered
    mock.sessions = [descriptor(backend_epoch='b'*32)]
    node.heartbeat()
    node.discover()
    assert entry(node) is not old


def test_removed_during_request_does_not_ack():
    node, mock = transport()
    old = entry(node)
    mock.mutate = lambda: node.entries.clear()
    node.work(old)
    assert not node.entries and not mock.acks


def test_removed_during_c_does_not_publish():
    node, mock = transport()
    def factory():
        agent = DeterministicDhNode('alice', 6)
        original = agent._core.modexp
        def compute(*args):
            node.entries.clear()
            return original(*args)
        agent._core.modexp = compute
        return agent
    node.factory = factory
    node.work(entry(node))
    assert not node.entries and not mock.publications


@pytest.mark.parametrize('status,code,fatal', [(401,'UNAUTHORIZED',True), (403,'ROLE_FORBIDDEN',True), (403,'ROLE_NOT_ASSIGNED',False), (403,'DIAGNOSTICS_DISABLED',False), (422,'INVALID_REQUEST',False), (404,'SESSION_NOT_FOUND',False)])
def test_error_scopes(status, code, fatal):
    node, _ = transport()
    e = entry(node)
    node.handle_error(InternalError(status, code), e)
    assert node.stop.is_set() is fatal
    if code == 'DIAGNOSTICS_DISABLED':
        assert e.diagnostics_disabled and not e.disabled


@pytest.mark.parametrize('field,value', [('prime', True), ('prime', 23.), ('prime','23'), ('revision',-1), ('mode','evil'), ('session_id','bad'), ('expires_at','bad')])
def test_invalid_discovery_atomic(field,value):
    node, mock = transport()
    old = entry(node)
    mock.sessions[0][field] = value
    with pytest.raises((ValueError, InternalError)):
        node.discover()
    assert entry(node) is old


def test_timeout_backoff_and_ttl():
    now = [0.]
    node, _ = transport(clock=lambda: now[0])
    e = entry(node)
    node.handle_error(InternalError(429,'RATE_LIMITED',20),e)
    assert e.next_attempt == 20
    now[0] = 31
    node.handle_error(InternalError(),e)
    assert e.failure == 'LOCAL_STATE_LOST'
    now[0] = 601
    node.cleanup()
    assert not node.entries


@pytest.mark.parametrize('status', ['completed','cancelled','expired','failed','created'])
def test_no_terminal_agent_recreation(status):
    node, _ = transport(sessions=[descriptor(status=status)])
    assert not node.entries


def test_diagnostic_retention_never_extended():
    now = [0.]
    node, mock = transport(clock=lambda: now[0])
    node.work(entry(node))
    e = entry(node)
    e.diagnostics_sent = False
    mock.sessions[0].update(status='completed', participant_status='received')
    node.discover()
    now[0] = 9
    node.lease_deadline = 100
    node.discover()
    assert e.deadline == 30
    now[0] = 31
    node.cleanup()
    assert e.node is None and e.disabled


@pytest.mark.parametrize('limit', [0,129,True,'2'])
def test_invalid_capacity(limit):
    with pytest.raises(ValueError):
        MultiSessionTransport(Coordinator(),max_agents=limit)


def test_scheduler_two_jobs_no_overlap_and_independent_heartbeat():
    from threading import Lock, Thread
    node, mock = transport(sessions=[descriptor(f'{i:032x}') for i in range(1,11)])
    entered, release = Event(), Event()
    mutex = Lock()
    active = set()
    maximum = [0]
    visited = set()
    def blocked(e):
        with mutex:
            assert e not in active
            active.add(e)
            maximum[0] = max(maximum[0], len(active))
            visited.add(e.descriptor.session_id)
            if len(active) == 2:
                entered.set()
        assert release.wait(3)
        with mutex:
            active.remove(e)
    node.process = blocked
    runner = Thread(target=node.run)
    runner.start()
    try:
        assert entered.wait(2)
        assert maximum[0] == 2 and len(active) == 2
        assert sum(path.endswith('/heartbeat') for _,path,_ in mock.calls) >= 2
        release.set()
        import time
        deadline = time.monotonic()+3
        while len(visited) < 10 and time.monotonic() < deadline:
            time.sleep(.01)
        assert len(visited) == 10
    finally:
        release.set()
        node.stop.set()
        runner.join(3)
    assert not runner.is_alive() and not node.entries


def test_both_diagnostic_opt_ins_required():
    node, mock = transport()
    node.allow_diagnostics = False
    node.work(entry(node))
    assert not mock.diagnostics
    node, mock = transport(sessions=[descriptor(diagnostics_enabled=False)])
    node.work(entry(node))
    assert not mock.diagnostics


def test_old_epoch_error_does_not_clear_new_registry():
    node, mock = transport()
    old = entry(node)
    mock.epoch = 'b'*32
    mock.sessions = [descriptor(backend_epoch=mock.epoch)]
    node.heartbeat()
    node.discover()
    new = entry(node)
    node.handle_error(EpochChanged(),old)
    assert entry(node) is new


def test_invalid_inbox_before_c_and_ack():
    node, mock = transport()
    original = mock.request
    def broken(method,path,epoch,body=None):
        result, epoch = original(method,path,epoch,body)
        if method == 'GET' and path.endswith('/messages'):
            result['session_id'] = '2'*32
        return result,epoch
    mock.request = broken
    node.work(entry(node))
    assert entry(node).node.state.phase == 'public_ready'
    assert not mock.acks


def test_reference_mitm_two_sessions_matches_real_mallory_substitutes():
    sessions = [descriptor(),descriptor('2'*32)]
    mallory, coordinator = transport('mallory',sessions)
    for e in mallory.entries.values():
        mallory.work(e)
    for role in ('alice','bob'):
        node, mock = transport(role,[descriptor(),descriptor('2'*32)])
        original = mock.request
        def routed(method,path,epoch,body=None):
            result, epoch = original(method,path,epoch,body)
            if '/messages' in path and (method == 'GET' or path.endswith('/ack')):
                sid = path.split('/')[5]
                sender = 'bob' if role == 'alice' else 'alice'
                value = coordinator.forwards[(sid,sender+'-public')]
                if method == 'GET':
                    for message in result['messages']:
                        message['public_value'] = value
                else:
                    result['public_value'] = value
            return result,epoch
        mock.request = routed
        for e in node.entries.values():
            node.work(e)
        for sid in (SID,'2'*32):
            key = 'shared_with_'+role
            assert mock.diagnostics[(role,sid)]['shared_secret'] == coordinator.diagnostics[('mallory',sid)][key]


def test_c_failure_preserves_other_session_and_reports_failure():
    from backend.app.crypto_core import CryptoCoreCallError
    node, mock = transport(sessions=[descriptor(),descriptor('2'*32)])
    node.work(entry(node,'2'*32))
    other = entry(node,'2'*32).node
    def factory():
        agent = DeterministicDhNode('alice',6)
        def fail(*args):
            raise CryptoCoreCallError(99,'INTERNAL_ERROR','Nie ujawniać szczegółów.')
        agent._core.modexp = fail
        return agent
    node.factory = factory
    node.work(entry(node))
    assert entry(node).node is None and entry(node).failure == 'CRYPTO_CORE_ERROR'
    node.work(entry(node))
    assert entry(node).disabled and other is entry(node,'2'*32).node
    assert any(path.endswith('/fail') and body == {'code':'CRYPTO_CORE_ERROR'} for _,path,body in mock.calls)


def test_stale_heartbeat_cannot_reregister_invalidated_generation():
    node, mock = transport()
    mock.mutate = node.invalidate
    node.heartbeat()
    assert not node.registered and not node.entries
    node.heartbeat()
    assert node.registered


def test_stale_discovery_cannot_restore_removed_agents():
    node, mock = transport()
    def reset():
        node.invalidate()
        node.heartbeat()
    mock.mutate = reset
    node.discover()
    assert not node.entries
