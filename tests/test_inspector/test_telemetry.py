import asyncio
import json
import secrets
import socket
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from app import telemetry


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def debug_server(core, monkeypatch, request):
    token = secrets.token_urlsafe(32)
    port = free_port()
    monkeypatch.setenv("RADH_DEBUG_ENABLED", "true")
    monkeypatch.setenv("RADH_DEBUG_TOKEN", token)
    monkeypatch.setenv("RADH_DEBUG_PORT", str(port))
    _, api, _ = request.getfixturevalue("live_server")
    return api, f"http://127.0.0.1:{port}", token


def read_events(response):
    for line in response.iter_lines():
        if line.startswith("data: "):
            yield json.loads(line[6:])


def until(events, name):
    for _ in range(200):
        event = next(events)
        if event["event"] == name:
            return event
    pytest.fail(f"Brak zdarzenia {name}")


def test_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("RADH_DEBUG_ENABLED", raising=False)

    async def disabled():
        async with telemetry.serving("test"):
            assert telemetry._active is None

    asyncio.run(disabled())
    assert client.get(telemetry.PATH).status_code == 404
    assert telemetry.PATH not in client.get("/openapi.json").json()["paths"]


@pytest.mark.live
def test_authorization_listener_separation_and_multiple_subscribers(debug_server):
    api, debug, token = debug_server
    url = debug + telemetry.PATH
    headers = {"Authorization": "Bearer " + token, "Accept": "text/event-stream"}
    assert httpx.get(api + telemetry.PATH, headers=headers).status_code == 404
    assert httpx.get(debug + "/openapi.json").status_code == 404
    assert httpx.get(url).status_code == 401
    assert httpx.get(url, headers={"Authorization": "Bearer " + secrets.token_urlsafe(32)}).status_code == 401
    assert httpx.get(url, headers=[*headers.items(), ("Authorization", headers["Authorization"])]).status_code == 401
    assert httpx.get(url, params={"token": token}).status_code == 401
    assert httpx.head(url, headers=headers).status_code == 405

    with httpx.stream("GET", url, headers=headers) as first:
        assert first.status_code == 200
        assert first.headers["content-type"].startswith("text/event-stream")
        assert first.headers["cache-control"] == "no-store"
        first_events = read_events(first)
        startup = next(first_events)
        assert startup["event"] == "system.started"
        assert startup["schema_version"] == 1
        assert startup["data"]["buffer_capacity"] == telemetry.RING_CAPACITY
        assert datetime.fromisoformat(startup["timestamp"]).utcoffset().total_seconds() == 0

        with httpx.stream("GET", url, headers=headers) as second:
            second_events = read_events(second)
            assert next(second_events)["data"]["instance"] == startup["data"]["instance"]
            response = httpx.post(api + "/api/v1/rsa/demo/keygen", json={"p": 61, "q": 53, "e": 17})
            assert response.status_code == 200
            contract = response.json()
            assert contract == {"n": 3233, "e": 17, "d": 2753, "phi": 3120}

            for events in (first_events, second_events):
                started = until(events, "rsa.keygen.started")
                native = until(events, "radh_rsa_keygen_u32.completed")
                complete = until(events, "rsa.keygen.completed")
                http = until(events, "http.request.completed")
                assert len({e["request_id"] for e in (started, native, complete, http)}) == 1
                assert complete["data"] == {"modulus": "3233", "public_exponent": "17", "scope": "python"}
                assert native["data"] == {"scope": "ffi", "return_status": 0}
                assert http["data"] == {
                    "scope": "http", "method": "POST", "route": "/api/v1/rsa/demo/keygen", "status": 200,
                }
                assert all(type(e["duration_ns"]) is int and e["duration_ns"] > 0 for e in (native, complete, http))
                assert native["duration_ns"] <= complete["duration_ns"] <= http["duration_ns"]

        sensitive_text = "TEKST NIEJAWNY marker RADH"
        text_url = api + "/api/v1/rsa/demo/text/encrypt"
        response = httpx.post(text_url, json={"text": sensitive_text, "public_exponent": 17, "modulus": 3233})
        assert response.status_code == 200
        assert set(response.json()) == {"ciphertexts"}
        started = until(first_events, "rsa.text.encrypt.started")
        aggregate = next(first_events)
        completed = next(first_events)
        assert completed["event"] == "rsa.text.encrypt.completed"
        assert aggregate["event"] == "radh_rsa_encrypt_u32.completed"
        assert aggregate["data"] == {"scope": "ffi_sum", "return_status": 0}
        assert sensitive_text not in json.dumps([started, completed, aggregate])

        dh = httpx.post(api + "/api/v1/dh/demo/exchange", json={
            "prime": 23, "generator": 5, "alice_secret": 6, "bob_secret": 15,
        })
        assert dh.status_code == 200
        exchange = until(first_events, "dh.exchange.completed")
        assert exchange["data"] == {
            "prime": "23", "generator": "5", "alice_public": "8", "bob_public": "19", "scope": "python",
        }


@pytest.mark.live
def test_rsa_errors_and_dh_session_metadata(debug_server):
    api, debug, token = debug_server
    with httpx.stream("GET", debug + telemetry.PATH, headers={"Authorization": "Bearer " + token}) as stream:
        events = read_events(stream)
        assert next(events)["event"] == "system.started"
        response = httpx.post(api + "/api/v1/rsa/demo/encrypt", json={
            "message": 38, "public_exponent": 17, "modulus": 33,
        })
        assert response.status_code == 422
        crypto = until(events, "rsa.encrypt.failed")
        assert crypto["data"] == {"scope": "python", "code": "MESSAGE_OUT_OF_RANGE",
                                   "modulus": "33", "public_exponent": "17"}
        error = until(events, "http.error")
        assert error["request_id"] == crypto["request_id"]
        secret_identifier = "owner_password_marker"
        root = api + "/api/v1/dh/sessions"
        request = {"session_id": secret_identifier, "prime": 23, "generator": 5, "mode": "normal"}
        assert httpx.post(root, json=request).status_code == 201
        created = until(events, "dh.session.created")
        assert created["data"]["state"] == "created"
        assert created["data"]["prime"] == "23"
        assert created["data"]["generator"] == "5"
        assert len(created["data"]["session"]) == 24
        assert secret_identifier not in json.dumps(created)
        assert httpx.post(root + "/" + secret_identifier + "/start").status_code == 200
        started = until(events, "dh.session.started")
        http = until(events, "http.request.completed")
        assert started["data"]["session"] == created["data"]["session"]
        assert started["data"]["state"] == "running"
        assert http["data"]["route"] == "/api/v1/dh/sessions/{session_id}/start"
        assert secret_identifier not in json.dumps(http)


def test_nonlocal_peer_cannot_spoof_loopback():
    token = secrets.token_urlsafe(32)
    debug = telemetry.debug_app(telemetry.EventBuffer("test"), token.encode())
    with TestClient(debug, client=("192.0.2.7", 50000)) as client:
        response = client.get(telemetry.PATH, headers={
            "Authorization": "Bearer " + token, "X-Forwarded-For": "127.0.0.1",
        })
    assert response.status_code == 403


def test_allowlist_and_failures_leave_api_contract_intact(client, monkeypatch):
    ring = telemetry.EventBuffer("test", capacity=30)
    monkeypatch.setattr(telemetry, "_active", ring)
    telemetry.publish("test", "test.event", modulus=3233, plaintext="secret", cookies="secret",
                      password="secret", code="secret", session_token="secret", d=2753,
                      private_exponent=2753, shared_secret=8)
    assert ring.snapshot(0)[2][0]["data"] == {"modulus": "3233"}

    def failed(_event):
        raise RuntimeError("Błąd zapisu celowo wymuszony w teście")

    monkeypatch.setattr(ring, "publish", failed)
    response = client.post("/api/v1/rsa/demo/encrypt", json={
        "message": 65, "public_exponent": 17, "modulus": 3233,
    })
    assert response.status_code == 200
    assert response.json() == {"ciphertext": 2790}


def test_bounded_ring_independent_cursors_and_reader_limit(monkeypatch):
    ring = telemetry.EventBuffer("test", capacity=3, max_subscribers=2)
    monkeypatch.setattr(telemetry, "_active", ring)
    first = ring.subscribe("")
    for _ in range(4):
        telemetry.publish("test", "observed")
    second = ring.subscribe("")
    assert ring.subscribe("") is None
    for _ in range(4):
        telemetry.publish("test", "observed")
    _, lost, events = ring.snapshot(first[0])
    assert lost == 5
    assert [e["event_id"] for e in events] == [6, 7, 8]
    assert ring.snapshot(second[0])[1] == 1
    ring.unsubscribe()
    assert ring.subscribe(f"{ring.instance}:7") == (7, False)
    ring.unsubscribe()
    assert ring.subscribe("0" * 32 + ":7") == (8, True)
    ring.close()
    assert ring.snapshot(8)[0]
    assert ring.subscribe("") is None


def test_slow_subscriber_and_disconnect_release_slot(monkeypatch):
    ring = telemetry.EventBuffer("test", capacity=2, max_subscribers=1)
    monkeypatch.setattr(telemetry, "_active", ring)
    monkeypatch.setattr(telemetry, "POLL_SECONDS", 0.001)
    monkeypatch.setattr(telemetry, "HEARTBEAT_SECONDS", 0.001)

    async def exercise():
        stalled = asyncio.Event()
        release = asyncio.Event()
        heartbeat = asyncio.Event()
        connection_lost = asyncio.Event()
        messages = []

        async def receive():
            await connection_lost.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            raw = message.get("body", b"")
            messages.append(raw)
            if b"system.started" in raw:
                stalled.set()
                await release.wait()
            if b": heartbeat" in raw:
                heartbeat.set()

        stream = telemetry.EventStream(ring, "")
        task = asyncio.create_task(stream({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send))
        await asyncio.wait_for(stalled.wait(), 1)
        for _ in range(8):
            await asyncio.wait_for(asyncio.to_thread(telemetry.publish, "test", "observed"), 1)
        assert ring.status()["buffer_used"] == 2
        release.set()
        await asyncio.wait_for(heartbeat.wait(), 1)
        assert b'"dropped":6' in b"".join(messages)
        connection_lost.set()
        await asyncio.wait_for(task, 1)
        assert ring.subscribe("") == (8, False)

    asyncio.run(exercise())


@pytest.mark.live
def test_failed_debug_bind_does_not_stop_backend(core, monkeypatch, request):
    monkeypatch.setenv("RADH_DEBUG_ENABLED", "true")
    monkeypatch.setenv("RADH_DEBUG_TOKEN", secrets.token_urlsafe(32))
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        monkeypatch.setenv("RADH_DEBUG_PORT", str(occupied.getsockname()[1]))
        _, api, _ = request.getfixturevalue("live_server")
        response = httpx.post(api + "/api/v1/rsa/demo/encrypt", json={
            "message": 65, "public_exponent": 17, "modulus": 3233,
        })
        assert response.json() == {"ciphertext": 2790}


def test_public_proxy_only_targets_main_listener():
    deploy = Path(__file__).resolve().parents[2] / "deploy"
    nginx = (deploy / "nginx.conf").read_text()
    upstream = (deploy / "proxy-backend.conf").read_text()
    assert "location /api/" in nginx
    assert "http://backend:8000;" in upstream
    assert ":8001" not in nginx + upstream


@pytest.mark.live
def test_resume_delivers_events_since_disconnect(debug_server):
    api, debug, token = debug_server
    url = debug + telemetry.PATH
    headers = {"Authorization": "Bearer " + token}
    with httpx.stream("GET", url, headers=headers) as stream:
        frame = stream.iter_lines()
        cursor = next(frame)
        assert cursor.startswith("id: ")
        assert json.loads(next(frame)[6:])["event"] == "system.started"

    response = httpx.post(api + "/api/v1/rsa/demo/encrypt", json={
        "message": 65, "public_exponent": 17, "modulus": 3233,
    })
    assert response.status_code == 200
    with httpx.stream("GET", url, headers={**headers, "Last-Event-ID": cursor[4:]}) as stream:
        events = read_events(stream)
        assert next(events)["event"] == "system.started"
        completed = until(events, "rsa.encrypt.completed")
        assert completed["event_id"] > int(cursor.rsplit(":", 1)[1])
