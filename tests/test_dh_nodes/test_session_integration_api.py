"""Uzgodnione rozszerzenia #37 dla #38, bez zmiany publicznego protokołu."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from app.main import app
from backend.dh_transport import HttpTransport
from tests.test_dh_nodes.test_sessions import api, start, send, ack, create, A, B, BASE

NODES = "/api/v1/dh/nodes"
DIAG = BASE + "/ref/diagnostics"


def complete(api):
    start(api)
    send(api, A)
    send(api, B)
    ack(api, A)
    ack(api, B)


def test_presence_expires_without_mutating_session(api, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(app.state.dh_presence, "_clock", lambda: now[0])
    empty = {role: {"online": False, "last_seen": None} for role in ("alice", "bob", "mallory")}
    assert api.get(NODES).json() == empty
    response = api.post(NODES + "/alice/heartbeat")
    assert response.status_code == 204 and response.content == b""
    first = api.get(NODES).json()
    assert first["alice"]["online"] and first["alice"]["last_seen"].endswith("Z")
    assert first["bob"] == empty["bob"]
    start(api)
    before = api.get(BASE + "/ref").json()
    now[0] = 4.99
    assert api.get(NODES).json()["alice"]["online"]
    now[0] = 5
    assert not api.get(NODES).json()["alice"]["online"]
    assert api.get(NODES).json()["alice"]["last_seen"] == first["alice"]["last_seen"]
    assert api.post(NODES + "/alice/heartbeat").status_code == 204
    assert api.get(NODES).json()["alice"]["online"]
    assert api.post(NODES + "/unknown/heartbeat").status_code == 422
    assert api.get(BASE + "/ref").json() == before


def test_diagnostics_are_separate_idempotent_and_cleared(api):
    complete(api)
    before = api.get(BASE + "/ref").json()
    assert api.get(DIAG).json() == {"alice": None, "bob": None}
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: api.post(DIAG, json={"participant": "alice", "shared_secret": 2}), range(12)))
    assert all(r.status_code == 204 and r.content == b"" for r in replies)
    assert api.post(DIAG, json={"participant": "alice", "shared_secret": 3}).status_code == 409
    assert api.get(DIAG).json() == {"alice": 2, "bob": None}
    assert api.post(DIAG, json={"participant": "bob", "shared_secret": 2}).status_code == 204
    assert api.get(DIAG).json() == {"alice": 2, "bob": 2}
    assert api.get(BASE + "/ref").json() == before
    assert create(api, "new").status_code == 201
    assert api.get(BASE + "/new/diagnostics").json() == {"alice": None, "bob": None}
    assert api.get(DIAG).status_code == 404
    assert api.post(DIAG, json={"participant": "alice", "shared_secret": 2}).status_code == 404


def test_diagnostics_require_own_ack_and_survive_peer_wait(api):
    start(api)
    report = {"participant": "alice", "shared_secret": 2}
    assert api.post(DIAG, json=report).status_code == 409
    send(api, A)
    send(api, B)
    ack(api, B)
    assert api.get(BASE + "/ref").json()["status"] == "running"
    assert api.post(DIAG, json=report).status_code == 204
    assert api.post(DIAG, json={**report, "participant": "bob"}).status_code == 409
    api.post(BASE + "/ref/cancel")
    assert api.post(DIAG, json=report).status_code == 409


@pytest.mark.parametrize("extra", [{"participant": "mallory"}, {"shared_secret": True},
    {"shared_secret": "2"}, {"shared_secret": 2.0}, {"shared_secret": 0},
    {"shared_secret": 23}, {"shared_secret": 2**32}, {"secret": 6}])
def test_diagnostics_reject_invalid_data(api, extra):
    complete(api)
    response = api.post(DIAG, json={"participant": "alice", "shared_secret": 2, **extra})
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert api.get(DIAG).json() == {"alice": None, "bob": None}


@pytest.mark.parametrize("extra,code", [
    ({"prime": 24}, "INVALID_PRIME"), ({"prime": -1}, "INVALID_PRIME"),
    ({"generator": 1}, "INVALID_GENERATOR"), ({"generator": 23}, "INVALID_GENERATOR"),
    ({"generator": 2**32}, "INVALID_GENERATOR"),
    ({"prime": True}, "INVALID_REQUEST"), ({"prime": "24"}, "INVALID_REQUEST"),
    ({"prime": 24.0}, "INVALID_REQUEST"), ({"secret": 6}, "INVALID_REQUEST"),
])
def test_specific_parameter_errors(api, extra, code):
    response = api.post(BASE, json={"prime": 23, "generator": 5, **extra})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"]


class LocalNode:
    def __init__(self):
        self.state = SimpleNamespace(session_id="ref", public_value=8)
        self.received = None
        self.diagnostic_reads = 0

    def receive_public(self, session_id, public_value):
        self.received = public_value

    def diagnostics(self):
        assert self.received == 19
        self.diagnostic_reads += 1
        return {"participant": "alice", "session_id": "ref", "shared_secret": 2}


def bind(api, transport):
    def request(path, body=None):
        response = api.get(BASE + path) if body is None else api.post(BASE + path, json=body)
        assert response.status_code in (200, 204), response.text
        return response.json() if response.content else None
    transport.request = request
    return request


@pytest.mark.parametrize("lost_path", ["/ref/messages/bob-public/ack", "/ref/diagnostics"])
@pytest.mark.parametrize("after_accept", [False, True])
def test_retry_diagnostics_after_last_ack_and_completed(api, lost_path, after_accept):
    start(api)
    send(api, A)
    send(api, B)
    ack(api, A)  # Bob już potwierdził; ACK Alice zakończy sesję.
    node = LocalNode()
    transport = HttpTransport("http://unused", "alice", node, allow_diagnostics=True)
    request = bind(api, transport)
    lost = False

    def unreliable(path, body=None):
        nonlocal lost
        if path == lost_path and not lost:
            lost = True
            if after_accept:
                request(path, body)
            raise TimeoutError()
        return request(path, body)

    transport.request = unreliable
    with pytest.raises(TimeoutError):
        transport.poll()
    transport.poll()
    assert api.get(BASE + "/ref").json()["status"] == "completed"
    assert api.get(DIAG).json() == {"alice": 2, "bob": None}
    reads = node.diagnostic_reads
    transport.poll()
    assert node.diagnostic_reads == reads
    assert len(api.get(BASE + "/ref/events").json()) == 7


def test_diagnostics_disabled_by_default(api):
    complete(api)
    node = LocalNode()
    transport = HttpTransport("http://unused", "alice", node)
    bind(api, transport)
    transport.poll()
    assert node.diagnostic_reads == 0
    assert api.get(DIAG).json() == {"alice": None, "bob": None}


def test_heartbeat_continues_while_exchange_waits_and_recovers(api):
    node = LocalNode()
    transport = HttpTransport("http://unused", "alice", node)
    stop = Event()
    exchange_started = Event()
    release_exchange = Event()
    seen = Event()
    attempts = []

    def heartbeat():
        attempts.append(1)
        if len(attempts) == 1:
            raise URLError("offline")
        seen.set()

    def blocked_request(*args):
        exchange_started.set()
        release_exchange.wait(timeout=5)
        return {"session_id": "ref", "prime": 23, "generator": 5,
                "mode": "normal", "status": "created"}

    transport.heartbeat = heartbeat
    transport.request = blocked_request
    heart = Thread(target=transport.heartbeat_loop, args=(stop,))
    exchange = Thread(target=transport.poll)
    try:
        exchange.start()
        assert exchange_started.wait(timeout=1)
        heart.start()
        assert seen.wait(timeout=3)
        assert exchange.is_alive()
    finally:
        stop.set()
        release_exchange.set()
        heart.join(timeout=3)
        exchange.join(timeout=3)
    assert not heart.is_alive() and not exchange.is_alive()


def test_heartbeat_sends_post_without_body_and_reads_204(monkeypatch):
    import io
    response = io.BytesIO(b"")
    response.status = 204
    def urlopen(request, timeout):
        assert request.full_url == "http://unused/api/v1/dh/nodes/alice/heartbeat"
        assert request.method == "POST" and request.data is None
        assert timeout == 2
        return response
    monkeypatch.setattr("backend.dh_transport.urlopen", urlopen)
    HttpTransport("http://unused", "alice", LocalNode()).heartbeat()
    assert response.closed
