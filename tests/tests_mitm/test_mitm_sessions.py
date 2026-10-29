"""Routing #41: oryginały nie trafiają do ofiar przed podmianą."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.main import app
from backend.dh_transport import InvalidResponse, MalloryTransport, TransportError
from tests.test_dh_nodes.test_sessions import A, B, BASE, ack, api, create, send, start

PATH = BASE + "/ref"


def start_mitm(api):
    assert create(api, mode="mitm").status_code == 201
    assert api.post("/api/v1/dh/nodes/mallory/heartbeat").status_code == 204
    assert api.post(PATH + "/start").status_code == 200


def forward(api, message, value):
    return api.post(PATH + f"/interceptions/{message['message_id']}/forward", json={"public_value": value})


@pytest.mark.parametrize("order", [(A, B), (B, A)])
def test_actual_routing_no_bypass_and_retries(api, order):
    start_mitm(api)
    for message in order:
        assert send(api, message).json()["status"] == "intercepted"
        assert api.get(PATH + "/messages", params={"recipient": message["recipient"]}).json() == []
        assert ack(api, message).json()["error"]["code"] == "INTERCEPTION_REQUIRED"
    assert api.get(PATH).json()["status"] == "running"
    for message, value in [(A, 22), (B, 17)]:
        assert forward(api, message, value).status_code == 200
        assert forward(api, message, value).status_code == 200
        assert send(api, message).status_code == 200  # ponowienie oryginału po podmianie
        assert send(api, {**message, "public_value": value}).status_code == 409
        inbox = api.get(PATH + "/messages", params={"recipient": message["recipient"]}).json()
        assert inbox == [{**message, "public_value": value, "status": "queued"}]
        assert ack(api, message).status_code == 200
    session = api.get(PATH).json()
    assert session["status"] == "completed"
    records = {i["original_sender"]: i for i in session["interceptions"]}
    assert (records["alice"]["original_value"], records["alice"]["delivered_value"]) == (8, 22)
    assert (records["bob"]["original_value"], records["bob"]["delivered_value"]) == (19, 17)
    assert all(i["actual_sender"] == i["intercepted_by"] == "mallory" for i in records.values())
    assert all(i["status"] == "processed" for i in records.values())
    assert [e["sequence"] for e in session["events"]] == list(range(1, 10))
    assert sum(e["type"] == "message_forwarded" for e in session["events"]) == 2
    assert "shared_" not in str(session)
    assert forward(api, A, 22).status_code == 200
    assert ack(api, A).status_code == 200
    assert api.get(PATH).json() == session


@pytest.mark.parametrize("value", [0, 23, -1, True, "17", 17.0, None])
def test_bad_replacement_does_not_release_original(api, value):
    start_mitm(api)
    send(api, B)
    before = api.get(PATH).json()
    assert forward(api, B, value).status_code == 422
    assert api.get(PATH).json() == before
    assert api.get(PATH + "/messages?recipient=alice").json() == []


def test_concurrent_replacements_only_one_wins(api):
    start_mitm(api)
    send(api, B)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda v: forward(api, B, v), [17, 18]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert sum(e["type"] == "message_forwarded" for e in api.get(PATH).json()["events"]) == 1


def test_missing_mallory_expiry_and_incomplete_session(api, monkeypatch):
    now = [0]
    monkeypatch.setattr(app.state.dh_presence, "_clock", lambda: now[0])
    create(api, mode="mitm")
    assert api.post(PATH + "/start").json()["error"]["code"] == "MALLORY_UNAVAILABLE"
    api.post("/api/v1/dh/nodes/mallory/heartbeat")
    now[0] = 5
    assert api.post(PATH + "/start").status_code == 409
    api.post("/api/v1/dh/nodes/mallory/heartbeat")
    assert api.post(PATH + "/start").status_code == 200
    send(api, A)
    now[0] = 10
    assert not api.get("/api/v1/dh/nodes").json()["mallory"]["online"]
    assert api.get(PATH + "/messages?recipient=bob").json() == []
    assert api.get(PATH).json()["status"] == "running"
    assert api.post(PATH + "/cancel").status_code == 200
    assert forward(api, A, 22).status_code == 409
    assert api.get(PATH + "/interceptions").status_code == 409
    assert create(api, "next").status_code == 201
    assert api.post(BASE + "/next/start").status_code == 200
    assert forward(api, A, 22).status_code == 404


def test_normal_mode_disallows_mallory_routes(api):
    start(api)
    send(api, A)
    assert forward(api, A, 22).json()["error"]["code"] == "MITM_REQUIRED"
    assert api.get(PATH + "/interceptions").status_code == 409
    assert api.get(PATH + "/messages?recipient=bob").json()[0]["public_value"] == 8


def test_mallory_diagnostics_separate_and_idempotent(api):
    start_mitm(api)
    url = PATH + "/diagnostics/mallory"
    data = dict(shared_with_alice=12, shared_with_bob=22)
    assert api.post(url, json=data).status_code == 409
    assert forward(api, A, 22).status_code == 404
    for message, value in [(A, 22), (B, 17)]:
        send(api, message)
        forward(api, message, value)
        ack(api, message)  # pierwsze ACK czeka na publikację obu stron
    ack(api, A)
    before = api.get(PATH).json()
    assert before["status"] == "completed"
    assert api.post(url, json={**data, "x": 7}).status_code == 422
    assert api.post(url, json={**data, "shared_with_bob": 23}).status_code == 422
    assert api.post(url, json=data).status_code == 204
    assert api.post(url, json=data).status_code == 204
    assert api.post(url, json={**data, "shared_with_bob": 1}).status_code == 409
    assert api.get(url).json() == data
    assert api.get(PATH).json() == before
    assert create(api, "next").status_code == 201
    assert api.get(BASE + "/next/diagnostics/mallory").json() == dict(shared_with_alice=None, shared_with_bob=None)


class PublicMallory:
    """Dubler kontraktu #40: bez obliczeń; testuje wyłącznie transport HTTP."""

    def __init__(self):
        from types import SimpleNamespace
        self.state = SimpleNamespace(session_id=None, phase="idle", substitute_to_alice=17, substitute_to_bob=22)
        self.received = {}
        self.diagnostics_calls = 0

    def start_session(self, session_id, p, g):
        self.state.session_id = session_id
        self.state.phase = "public_ready"

    def receive_public(self, session_id, source, public_value):
        assert session_id == self.state.session_id
        assert source not in self.received or self.received[source] == public_value
        self.received[source] = public_value
        self.state.phase = "complete" if len(self.received) == 2 else "partial"

    def diagnostics(self):
        self.diagnostics_calls += 1
        return dict(participant="mallory", session_id=self.state.session_id, shared_with_alice=12, shared_with_bob=22)


def connect(transport, api):
    def request(path, body=None):
        response = api.get(BASE + path) if body is None else api.post(BASE + path, json=body)
        if response.status_code >= 400:
            raise TransportError(response.status_code)
        return response.json() if response.status_code != 204 else None
    transport.request = request
    return request


@pytest.mark.parametrize("lost_path", ["/forward", "/diagnostics/mallory"])
@pytest.mark.parametrize("accepted", [False, True])
def test_lost_forward_or_diagnostics_retries_after_completed(api, lost_path, accepted):
    start_mitm(api)
    send(api, A)
    send(api, B)
    node = PublicMallory()
    transport = MalloryTransport("http://test", node, allow_diagnostics=True)
    request = connect(transport, api)
    lost = [False]
    def flaky(path, body=None):
        if path.endswith(lost_path) and not lost[0]:
            lost[0] = True
            if accepted:
                request(path, body)
            raise OSError("lost response")
        return request(path, body)
    transport.request = flaky
    with pytest.raises(OSError):
        transport.poll()
    # Doręczenie i ACK mogą wyprzedzić ponowienie diagnostyki.
    if lost_path == "/diagnostics/mallory":
        ack(api, A)
        ack(api, B)
    transport.poll()
    ack(api, A)
    ack(api, B)
    transport.poll()
    assert api.get(PATH + "/diagnostics/mallory").json() == dict(shared_with_alice=12, shared_with_bob=22)
    assert api.get(PATH).json()["status"] == "completed"
    assert node.received == {"alice": 8, "bob": 19}
    assert sum(e["type"] == "message_forwarded" for e in api.get(PATH).json()["events"]) == 2


def test_diagnostics_off_does_not_call_agent(api):
    start_mitm(api)
    send(api, A)
    send(api, B)
    node = PublicMallory()
    transport = MalloryTransport("http://test", node)
    connect(transport, api)
    transport.poll()
    assert node.diagnostics_calls == 0
    assert api.get(PATH + "/diagnostics/mallory").json() == dict(shared_with_alice=None, shared_with_bob=None)


@pytest.mark.parametrize("mutate", [
    lambda records: [{**records[0], "original_value": 23}],
    lambda records: [{**records[0], "recipient": "alice"}],
    lambda records: [{k: v for k, v in records[0].items() if k != "status"}],
    lambda records: [records[0], records[0]],
    lambda records: [{**records[0], "status": "forwarded"}],
])
def test_invalid_interceptions_do_not_reach_agent(api, mutate):
    start_mitm(api)
    send(api, A)
    node = PublicMallory()
    transport = MalloryTransport("http://test", node)
    request = connect(transport, api)
    transport.request = lambda path, body=None: (mutate(request(path)) if path.endswith("/interceptions")
                                                 else request(path, body))
    with pytest.raises(InvalidResponse):
        transport.poll()
    assert node.state.session_id is None
    assert node.received == {}
    assert api.get(PATH + "/messages?recipient=bob").json() == []


def test_restart_conflict_blocks_all_new_substitutions(api):
    start_mitm(api)
    send(api, A)
    send(api, B)
    # Drugi wpis ma podmianę wyliczoną przez poprzedni proces Mallory.
    assert forward(api, B, 18).status_code == 200
    node = PublicMallory()
    transport = MalloryTransport("http://test", node)
    connect(transport, api)
    before = api.get(PATH).json()
    with pytest.raises(InvalidResponse):
        transport.poll()
    assert node.received == {}
    assert api.get(PATH).json() == before
    assert api.get(PATH + "/messages?recipient=bob").json() == []
