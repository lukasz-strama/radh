"""Kontrakt backendu #37: prawdziwe żądania, kolejki i uporządkowane zdarzenia."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import State

from app.main import app
from app.node_presence import PresenceStore
from app.sessions import SessionStore

BASE = "/api/v1/dh/sessions"
A = dict(message_id="alice-public", sender="alice", recipient="bob", type="public_value", public_value=8)
B = dict(message_id="bob-public", sender="bob", recipient="alice", type="public_value", public_value=19)


@pytest.fixture
def api(monkeypatch):
    # State przechowuje atrybuty dynamicznie; podmieniamy zwykły atrybut aplikacji.
    with monkeypatch.context() as isolated:
        isolated.setattr(app, "state", State({
            "dh_sessions": SessionStore(), "dh_presence": PresenceStore(),
        }))
        with TestClient(app) as client:
            yield client


def create(api, session_id="ref", **extra):
    return api.post(BASE, json=dict(session_id=session_id, prime=23, generator=5, **extra))


def start(api):
    assert create(api).status_code == 201
    assert api.post(BASE + "/ref/start").status_code == 200


def send(api, message):
    return api.post(BASE + "/ref/messages", json=message)


def ack(api, message):
    return api.post(BASE + f"/ref/messages/{message['message_id']}/ack", json={"recipient": message["recipient"]})


def test_exchange_log_and_retries(api):
    start(api)
    assert api.get(BASE + "/ref/messages?recipient=bob").json() == []
    for message in (A, B):
        assert send(api, message).status_code == 200
        assert send(api, message).status_code == 200
    for message in (A, B):
        inbox = BASE + "/ref/messages?recipient=" + message["recipient"]
        assert api.get(inbox).json() == api.get(inbox).json() == [{**message, "status": "queued"}]
        assert ack(api, message).json()["status"] == "processed"
        assert ack(api, message).status_code == 200
        assert api.get(inbox).json() == []
    session = api.get(BASE + "/ref").json()
    assert session["status"] == "completed"
    assert session["participants"] == {"alice": "received", "bob": "received"}
    events = session["events"]
    assert [e["sequence"] for e in events] == list(range(1, 8))
    assert [e["type"] for e in events] == ["session_created", "session_started", "public_value", "public_value", "message_processed", "message_processed", "session_completed"]
    assert [(e["sender"], e["recipient"], e["public_value"], e["status"]) for e in events[2:4]] == [("alice", "bob", 8, "queued"), ("bob", "alice", 19, "queued")]
    assert api.get(BASE + "/ref/events?after=4").json() == events[4:]
    assert send(api, A).status_code == 200
    assert api.get(BASE + "/ref/events").json() == events
    assert "secret" not in str(session)


@pytest.mark.parametrize("extra", [{"prime": 9}, {"prime": 2}, {"prime": True}, {"prime": "23"}, {"prime": 2**32}, {"generator": 1}, {"generator": 23}, {"mode": "other"}, {"session_id": ""}, {"session_id": "a/b"}, {"secret": 123}])
def test_invalid_session(api, extra):
    response = api.post(BASE, json={"prime": 23, "generator": 5, **extra})
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert api.get(BASE + "/current").status_code == 404


@pytest.mark.parametrize("extra", [{"sender": "mallory"}, {"recipient": "alice"}, {"public_value": 0}, {"public_value": 23}, {"public_value": True}, {"public_value": "8"}, {"type": "secret"}, {"message_id": ""}, {"shared_key": 123}, {"a": 6}, {"b": 15}, {"x": 1}, {"y": 1}])
def test_invalid_message_preserves_state(api, extra):
    start(api)
    before = api.get(BASE + "/ref").json()
    response = send(api, {**A, **extra})
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert api.get(BASE + "/ref").json() == before


def test_lifecycle_and_stale_identifiers(api):
    assert api.get(BASE + "/missing").status_code == 404
    assert create(api).status_code == 201
    assert send(api, A).status_code == 409
    assert create(api, "next").status_code == 409
    assert api.post(BASE + "/ref/cancel").status_code == 200
    assert api.post(BASE + "/ref/start").status_code == 409
    assert create(api, "next").status_code == 201
    assert api.get(BASE + "/ref").status_code == 404
    assert api.post(BASE + "/next/cancel").status_code == 200
    assert create(api).status_code == 409  # Nigdy nie wykorzystujemy ponownie starego ID.
    assert create(api, "current").status_code == 409


def test_missing_conflicting_and_out_of_order_messages(api):
    start(api)
    assert ack(api, A).status_code == 404
    assert send(api, A).status_code == 200
    assert ack(api, A).status_code == 409  # Bob nie wysłał jeszcze swojej wartości.
    assert send(api, {**A, "public_value": 7}).status_code == 409
    assert send(api, {**A, "message_id": "new"}).status_code == 409
    assert api.post(BASE + "/ref/messages/alice-public/ack", json={"recipient": "alice"}).status_code == 422
    assert api.get(BASE + "/ref/messages?recipient=mallory").status_code == 422
    assert api.get(BASE + "/ref/events?after=-1").status_code == 422
    assert api.get(BASE + "/ref").json()["status"] == "running"
    assert send(api, B).status_code == 200
    assert ack(api, A).status_code == 200
    assert ack(api, B).status_code == 200


def test_mitm_requires_online_mallory(api):
    assert create(api, mode="mitm").status_code == 201
    response = api.post(BASE + "/ref/start")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MALLORY_UNAVAILABLE"
    assert send(api, A).status_code == 409


def test_concurrent_duplicates_are_atomic(api):
    start(api)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: send(api, A), range(20)))
    assert all(r.status_code == 200 for r in responses)
    session = api.get(BASE + "/ref").json()
    assert len(session["messages"]) == 1
    assert len(session["events"]) == 3


def test_openapi_and_strict_fields(api):
    schema = api.get("/openapi.json").json()
    operation = schema["paths"][BASE + "/{session_id}/messages"]["post"]
    for status in ("404", "409", "422"):
        assert operation["responses"][status]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
    assert schema["components"]["schemas"]["PublicMessage"]["additionalProperties"] is False
    start(api)
    assert api.post(BASE + "/ref/messages", json={}).status_code == 422
    assert api.post(BASE + "/ref/messages", content="{", headers={"Content-Type": "application/json"}).status_code == 422


@pytest.mark.live
def test_two_waiting_processes_exchange_over_http(live_server, tmp_path):
    import json
    import subprocess
    import sys
    import time
    from pathlib import Path
    import httpx

    _, url, _ = live_server
    worker = Path(__file__).parent / "helpers" / "session_peer.py"
    processes = []
    try:
        for role in ("alice", "bob"):
            ready = tmp_path / role
            process = subprocess.Popen([sys.executable, str(worker), role, url, str(ready)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            processes.append(process)
        deadline = time.monotonic() + 10
        while not all((tmp_path / role).exists() for role in ("alice", "bob")):
            assert time.monotonic() < deadline, "Procesy nie zgłosiły gotowości"
            time.sleep(0.05)
        assert len({p.pid for p in processes}) == 2
        with httpx.Client(base_url=url, timeout=5) as client:
            assert client.post(BASE, json={"session_id": "ref", "prime": 23, "generator": 5}).status_code == 201
            assert client.post(BASE + "/ref/start").status_code == 200
            results = []
            for process in processes:
                out, err = process.communicate(timeout=20)
                assert process.returncode == 0, err
                results.append(json.loads(out))
            assert results == [{"role": "alice", "received": 19}, {"role": "bob", "received": 8}]
            state = client.get(BASE + "/ref").json()
            assert state["status"] == "completed"
            assert len(state["events"]) == 7
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


def test_transport_retries_lost_send_and_ack_without_restarting_node(api):
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.dh_transport import HttpTransport

    class Node:
        state = SimpleNamespace(session_id=None)
        starts = 0
        values = []

        def start_session(self, session_id, p, g):
            self.starts += 1
            self.state = SimpleNamespace(session_id=session_id, public_value=8)

        def receive_public(self, session_id, value):
            self.values.append(value)

    node = Node()
    transport = HttpTransport("http://unused", "alice", node)
    start(api)
    send(api, B)
    lost = {"/ref/messages", "/ref/messages/bob-public/ack"}

    def request(path, body=None):
        response = api.get(BASE + path) if body is None else api.post(BASE + path, json=body)
        assert response.status_code == 200
        if body is not None and path in lost:
            lost.remove(path)
            raise TimeoutError()
        return response.json()

    transport.request = request
    for _ in range(2):
        with pytest.raises(TimeoutError):
            transport.poll()
    transport.poll()
    assert node.starts == 1
    assert node.values == [19]
    assert len(api.get(BASE + "/ref/events").json()) == 5


@pytest.mark.parametrize("bad_response", [None, [], {"status": "running"}, {"error": "bad"},
    {"prime": 23, "generator": 5, "mode": "normal", "status": "running"},
    {"session_id": "ref", "prime": 23, "generator": 5, "mode": "normal"}])
def test_transport_rejects_invalid_session_before_node_call(bad_response):
    from backend.dh_transport import HttpTransport, InvalidResponse

    class UnusedNode:
        @property
        def state(self):
            pytest.fail("Błędna odpowiedź dotarła do węzła")

    transport = HttpTransport("http://unused", "alice", UnusedNode())
    transport.request = lambda *args: bad_response
    with pytest.raises(InvalidResponse):
        transport.poll()


@pytest.mark.parametrize("messages", [
    None, {}, [B], [{"message_id": "missing-fields"}], [{**B, "status": "queued", "recipient": "bob"}],
    [{**B, "status": "queued", "sender": "alice"}],
    [{**B, "status": "queued", "public_value": 0}],
    [{**B, "status": "queued", "public_value": 23}],
    [{**B, "status": "queued", "message_id": "../../escape"}],
    [{**B, "status": "processed"}],
    [{**B, "status": "queued", "shared_secret": 2}],
    [{**B, "status": "queued"}, {**B, "status": "queued"}],
])
def test_transport_rejects_invalid_inbox_without_ack(api, messages):
    from types import SimpleNamespace
    from backend.dh_transport import HttpTransport, InvalidResponse
    start(api)

    class Node:
        state = SimpleNamespace(session_id="ref", public_value=8)

        def receive_public(self, *args):
            pytest.fail("Błędna kolejka dotarła do obliczeń")

    transport = HttpTransport("http://unused", "alice", Node())
    paths = []

    def request(path, body=None):
        paths.append(path)
        if path == "/current":
            return api.get(BASE + path).json()
        if body is not None:
            return api.post(BASE + path, json=body).json()
        return messages

    transport.request = request
    with pytest.raises(InvalidResponse):
        transport.poll()
    assert not any(path.endswith("/ack") for path in paths)


def test_transport_rejects_invalid_json_and_closes_response(monkeypatch):
    import io
    from backend.dh_transport import HttpTransport, InvalidResponse
    response = io.BytesIO(b'{broken')
    response.status = 200
    monkeypatch.setattr("backend.dh_transport.urlopen", lambda *args, **kwargs: response)
    with pytest.raises(InvalidResponse):
        HttpTransport("http://unused", "alice", None).request("/current")
    assert response.closed


def test_concurrent_acknowledgements_complete_only_once(api):
    start(api)
    send(api, A)
    send(api, B)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda message: ack(api, message), [A, B] * 10))
    assert all(result.status_code == 200 for result in results)
    session = api.get(BASE + "/ref").json()
    assert session["status"] == "completed"
    assert len(session["events"]) == 7
    assert sum(e["type"] == "session_completed" for e in session["events"]) == 1


def test_cancelled_queue_cannot_be_processed(api):
    start(api)
    send(api, A)
    send(api, B)
    assert api.post(BASE + "/ref/cancel").status_code == 200
    before = api.get(BASE + "/ref").json()
    assert ack(api, A).status_code == 409
    assert api.get(BASE + "/ref/messages?recipient=bob").status_code == 409
    assert api.get(BASE + "/ref").json() == before


def test_store_returns_isolated_snapshots():
    from app.sessions import CreateSession
    store = SessionStore()
    snapshot = store.create(CreateSession(session_id="ref", prime=23, generator=5))
    snapshot.events.clear()
    snapshot.participants["alice"] = "received"
    assert len(store.get().events) == 1
    assert store.get().participants["alice"] == "waiting"
