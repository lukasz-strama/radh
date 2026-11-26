"""Jednostkowe testy granicy HTTP z atrapą ASGI, bez klienta HTTP i socketów."""

import asyncio
import json
import secrets
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.coordinator import digest
from app.coordinator_http import CoordinatorMiddleware, Runtime, bearer, role_credentials
from app.coordinator_limits import CoordinatorError, CryptoAdmission, RateLimiter, Settings
from app.multi_api import assigned, create_session, invoke
from app.multi_models import Create, Publish
from test_coordinator import Clock, create, error, register, start


def scope(path, method="GET", headers=()):
    return {"type": "http", "method": method, "path": path, "headers": headers,
            "client": ("127.0.0.1", 12345), "query_string": b"", "scheme": "http",
            "server": ("localhost", 8000)}


def test_owner_and_role_credentials_cannot_be_interchanged():
    token = secrets.token_urlsafe(32)
    rt = Runtime(role_hashes={"alice": digest(token)})
    owner = secrets.token_urlsafe(32)
    assert rt.authenticate_role(token) == "alice"
    error("UNAUTHORIZED", rt.authenticate_role, owner, status=401)
    for value in (None, "", "Bearer short", "Basic " + token, "Bearer " + token + " "):
        result = error("UNAUTHORIZED", bearer, value, status=401)
        assert result.headers == {"WWW-Authenticate": "Bearer"}


def test_role_files_are_bounded_validated_and_distinct(tmp_path, monkeypatch):
    for role in ("ALICE", "BOB", "MALLORY"):
        monkeypatch.delenv("RADH_" + role + "_TOKEN_FILE", raising=False)
    filename = tmp_path / "alice"
    token = secrets.token_urlsafe(32)
    filename.write_text(token + "\n")
    monkeypatch.setenv("RADH_ALICE_TOKEN_FILE", str(filename))
    assert role_credentials() == {"alice": digest(token)}
    monkeypatch.setenv("RADH_BOB_TOKEN_FILE", str(filename))
    with pytest.raises(ValueError):
        role_credentials()
    monkeypatch.delenv("RADH_BOB_TOKEN_FILE")
    filename.write_text("x" * 129)
    with pytest.raises(ValueError):
        role_credentials()


def test_create_rate_applies_to_retry_and_bucket_storage_is_bounded():
    clock = Clock()
    cfg = replace(Settings(), max_rate_buckets=2)
    limiter = RateLimiter(cfg, clock)
    limiter.check("create", "ip", 6, 2)
    limiter.check("create", "ip", 6, 2)
    exc = error("RATE_LIMITED", limiter.check, "create", "ip", 6, 2)
    assert exc.headers == {"Retry-After": "10"}
    for ip in range(100):
        try:
            limiter.check("create", ip, 6, 2)
        except CoordinatorError:
            pass
    assert len(limiter.buckets) == 2 and len(limiter.overflow) == 1
    clock.now = 600
    limiter.check("create", "new", 6, 2)
    assert len(limiter.buckets) == 1


def test_crypto_capacity_is_released_after_error():
    admission = CryptoAdmission(Settings(max_crypto_jobs=1, max_crypto_waiters=1))
    assert admission.capacity.acquire(blocking=False)
    assert admission.capacity.acquire(blocking=False)
    error("CRYPTO_BUSY", admission.slot().__enter__, status=503)
    admission.capacity.release()
    admission.capacity.release()
    with pytest.raises(RuntimeError):
        with admission.slot():
            raise RuntimeError("atrapa błędu C")
    with admission.slot():
        pass
    assert admission.jobs.acquire(blocking=False)
    admission.jobs.release()


async def call_middleware(rt, request_scope, bodies, response_body=b'{"ok":true}'):
    sent = []
    calls = []

    async def receive():
        return bodies.pop(0)

    async def send(message):
        sent.append(message)

    async def stub(scope, receive, send):
        calls.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": response_body})

    middleware = CoordinatorMiddleware(stub, SimpleNamespace(runtime=rt))
    await middleware(request_scope, receive, send)
    return sent, calls


@pytest.mark.parametrize("path", ["/api/v2/dh/nodes", "/internal/v1/dh/sessions"])
def test_epoch_and_no_store_on_auth_errors(path):
    rt = Runtime(role_hashes={})
    headers = [(b"origin", b"https://foreign.example")]
    sent, calls = asyncio.run(call_middleware(rt, scope(path, headers=headers), []))
    assert not calls
    assert sent[0]["status"] == 403
    assert (b"x-backend-epoch", rt.coordinator.epoch.encode()) in [(k.lower(), v) for k, v in sent[0]["headers"]]
    assert (b"cache-control", b"no-store") in [(k.lower(), v) for k, v in sent[0]["headers"]]


@pytest.mark.parametrize("chunks", [[4097], [2048, 2049]])
def test_body_cap_checks_received_bytes_including_chunked(chunks):
    rt = Runtime(role_hashes={})
    messages = [{"type": "http.request", "body": b"x" * size, "more_body": i < len(chunks) - 1}
                for i, size in enumerate(chunks)]
    sent, calls = asyncio.run(call_middleware(rt, scope("/api/v2/dh/sessions", "POST"), messages))
    assert sent[0]["status"] == 413 and calls == []
    assert json.loads(sent[1]["body"])["error"]["code"] == "REQUEST_TOO_LARGE"


def test_response_cap_and_media_type_are_enforced():
    rt = Runtime(role_hashes={})
    body = [{"type": "http.request", "body": b"{}", "more_body": False}]
    sent, calls = asyncio.run(call_middleware(rt, scope("/api/v2/dh/sessions", "POST"), body))
    assert sent[0]["status"] == 415 and not calls
    sent, _ = asyncio.run(call_middleware(
        rt, scope("/api/v2/dh/nodes"), [{"type": "http.request", "body": b""}],
        b"x" * 131073,
    ))
    assert sent[0]["status"] == 503


def test_success_replays_body_and_sets_epoch():
    rt = Runtime(role_hashes={})
    request = scope("/api/v2/dh/sessions", "POST",
                    [(b"content-type", b"application/json")])
    sent, calls = asyncio.run(call_middleware(
        rt, request, [{"type": "http.request", "body": b'{"prime":23}'}],
    ))
    assert calls[0]["body"] == b'{"prime":23}'
    assert sent[0]["status"] == 200
    assert (b"x-backend-epoch", rt.coordinator.epoch.encode()) in [(k.lower(), v) for k, v in sent[0]["headers"]]


def test_assigned_dependency_releases_lock_before_endpoint_thread():
    rt = Runtime(role_hashes={})
    c = rt.coordinator
    instances = register(c)
    created = create(c)
    start(c, created)
    request = Request(scope("/internal/v1/dh/sessions", headers=[
        (b"x-backend-epoch", c.epoch.encode()),
        (b"x-node-instance", instances["alice"].encode()),
    ]))
    grant = assigned(created.session.session_id, request, rt, "alice")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(invoke, rt, grant, "publish", "alice", Publish(
            message_id="alice-public", type="public_value", public_value=8,
        )).result(timeout=2)
    assert result.public_value == 8


def test_openapi_matches_v2_and_preserves_legacy_routes_by_default():
    from app.main import app
    paths = app.openapi()["paths"]
    assert "/api/v2/dh/sessions/{session_id}/diagnostics/mallory" in paths
    assert "/internal/v1/dh/sessions/{session_id}/interceptions/{message_id}/forward" in paths
    assert "/api/v1/dh/sessions/current" in paths
    assert "/api/v1/dh/sessions/{session_id}/messages" in paths
    assert "/api/v1/dh/nodes" in paths
    for path in ("/api/v1/rsa/demo/encrypt", "/api/v1/rsa/demo/keygen", "/api/v1/dh/demo/exchange"):
        assert path in paths
    assert paths["/api/v2/dh/sessions"]["post"]["responses"]["201"]


@pytest.mark.parametrize("name,value", [
    ("max_sessions", 0), ("session_created_ttl_seconds", -1),
    ("max_request_bytes", 4097), ("max_events", 33), ("max_events", 1),
    ("max_running_sessions", 129), ("max_crypto_waiters", True),
])
def test_invalid_configuration_is_rejected(name, value):
    with pytest.raises(ValueError):
        replace(Settings(), **{name: value})


def test_middleware_authenticates_before_reading_internal_body():
    rt = Runtime(role_hashes={})
    sent, calls = asyncio.run(call_middleware(
        rt, scope("/internal/v1/dh/sessions", "POST"), [],
    ))
    assert sent[0]["status"] == 401 and not calls


def test_duplicate_auth_headers_are_rejected_before_dispatch():
    rt = Runtime(role_hashes={})
    sent, calls = asyncio.run(call_middleware(
        rt, scope("/api/v2/dh/nodes", headers=[
            (b"authorization", b"first"), (b"authorization", b"second"),
        ]), [],
    ))
    assert sent[0]["status"] == 400 and not calls


def test_internal_rate_is_bound_to_authenticated_role():
    token = secrets.token_urlsafe(32)
    cfg = replace(Settings(), internal_rate_burst=1)
    rt = Runtime(cfg, role_hashes={"alice": digest(token)})
    request = scope("/internal/v1/dh/sessions")
    headers = {"authorization": "Bearer " + token}
    rt.admit(request, headers)
    assert request["state"]["node_role"] == "alice"
    error("RATE_LIMITED", rt.admit, request, headers)


def test_create_route_checks_required_headers_before_mutation():
    rt = Runtime(role_hashes={})
    request = Request(scope("/api/v2/dh/sessions", "POST"))
    error("BAD_REQUEST", create_session, Create(prime=23, generator=5), request, rt)
    assert not rt.coordinator.records


def test_admission_and_invalid_math_do_not_allocate_sessions():
    rt = Runtime(role_hashes={})
    key = secrets.token_urlsafe(32)
    request_scope = scope("/api/v2/dh/sessions", "POST", headers=[
        (b"idempotency-key", key.encode()),
        (b"x-backend-epoch", rt.coordinator.epoch.encode()),
    ])
    request_scope["state"] = {"client_ip": "127.0.0.1"}
    request = Request(request_scope)
    error("INVALID_PRIME", create_session, Create(prime=21, generator=5), request, rt)
    assert not rt.coordinator.records
    with rt.crypto.slot():
        pass


def test_internal_role_forbidden_and_diagnostic_route_enforce_role():
    from app.multi_api import heartbeat, mallory_report
    from app.multi_models import HeartbeatRequest, MalloryReport
    rt = Runtime(role_hashes={})
    error("ROLE_FORBIDDEN", heartbeat, "bob", HeartbeatRequest(instance_id="a" * 32), "alice", rt)
    assert not rt.coordinator.leases
    error("ROLE_FORBIDDEN", mallory_report, MalloryReport(shared_with_alice=2, shared_with_bob=2),
          {}, "alice", rt)


def test_crypto_routes_use_admission_and_pass_original_arguments(monkeypatch):
    from app import api
    from app.crypto_core import DhExchangeResult, RsaKeygenResult
    from app.models import RsaEncryptRequest, RsaKeygenRequest, DhExchangeRequest
    calls = []

    class FakeCore:
        def encrypt(self, *args):
            calls.append(("encrypt", args))
            return 2790

        def generate_rsa_keys(self, *args):
            calls.append(("keygen", args))
            return RsaKeygenResult(3233, 17, 2753, 3120)

        def exchange(self, *args):
            calls.append(("dh", args))
            return DhExchangeResult(8, 19, 2, 2)

    rt = Runtime(role_hashes={})
    request_scope = scope("/api/v1/rsa/demo/encrypt")
    request_scope["app"] = SimpleNamespace(state=SimpleNamespace(runtime=rt))
    request = Request(request_scope)
    monkeypatch.setattr(api, "get_crypto_core", FakeCore)
    assert api.encrypt_rsa(RsaEncryptRequest(message=65, public_exponent=17, modulus=3233), request, FakeCore()).ciphertext == 2790
    assert api.generate_rsa_keys(RsaKeygenRequest(p=61, q=53, e=17), request).d == 2753
    assert api.exchange_dh(DhExchangeRequest(prime=23, generator=5, alice_secret=6, bob_secret=15), request, FakeCore()).alice_shared_key == 2
    assert calls == [("encrypt", (65, 17, 3233)), ("keygen", (61, 53, 17)), ("dh", (23, 5, 6, 15))]


def test_legacy_middleware_preserves_previous_body_and_rate_behavior(monkeypatch):
    monkeypatch.setenv("RADH_LEGACY_API_ENABLED", "true")
    rt = Runtime(role_hashes={})
    for _ in range(7):
        sent, calls = asyncio.run(call_middleware(
            rt, scope("/api/v1/rsa/demo/encrypt", "POST"),
            [{"type": "http.request", "body": b"x" * 5000}],
        ))
        assert sent[0]["status"] == 200
        assert len(calls[0]["body"]) == 5000
    assert not rt.limiter.buckets


def test_disabled_legacy_mode_enforces_demo_limits(monkeypatch):
    monkeypatch.setenv("RADH_LEGACY_API_ENABLED", "false")
    rt = Runtime(role_hashes={})
    sent, calls = asyncio.run(call_middleware(
        rt, scope("/api/v1/rsa/demo/encrypt", "POST"),
        [{"type": "http.request", "body": b"x" * 5000}],
    ))
    assert sent[0]["status"] == 413 and not calls


@pytest.mark.parametrize("legacy", ["true", "false"])
@pytest.mark.parametrize("path", [
    "/api/v1/rsa/demo/parameters",
    "/api/v1/dh/demo/parameters",
    "/api/v1/rsa/demo/decrypt",
    "/api/v1/rsa/demo/text/encrypt",
    "/api/v1/rsa/demo/text/decrypt",
])
def test_parameter_and_new_rsa_routes_always_use_middleware(monkeypatch, legacy, path):
    monkeypatch.setenv("RADH_LEGACY_API_ENABLED", legacy)
    rt = Runtime(role_hashes={})
    for suffix in ("", "/"):
        sent, calls = asyncio.run(call_middleware(
            rt, scope(path + suffix, "POST", [(b"origin", b"https://foreign.example")]), [],
        ))
        assert sent[0]["status"] == 403 and not calls
        assert (b"cache-control", b"no-store") in sent[0]["headers"]
        sent, calls = asyncio.run(call_middleware(
            rt, scope(path + suffix, "POST"), [{"type": "http.request", "body": b"x" * 4097}],
        ))
        assert sent[0]["status"] == 413 and not calls


def test_parameters_and_text_rsa_use_independent_rate_buckets_in_legacy(monkeypatch):
    monkeypatch.setenv("RADH_LEGACY_API_ENABLED", "true")
    monkeypatch.setenv("PARAMETER_RATE_BURST", "1")
    monkeypatch.setenv("RSA_TEXT_RATE_BURST", "2")
    rt = Runtime(clock=Clock(), role_hashes={})

    def post(path):
        sent, _ = asyncio.run(call_middleware(
            rt, scope(path, "POST"), [{"type": "http.request", "body": b""}],
        ))
        if sent[0]["status"] == 429:
            assert (b"retry-after", b"6") in sent[0]["headers"]
        return sent[0]["status"]

    assert post("/api/v1/rsa/demo/parameters") == 200
    assert post("/api/v1/dh/demo/parameters") == 429
    assert post("/api/v1/rsa/demo/text/encrypt") == 200
    assert post("/api/v1/rsa/demo/text/decrypt") == 200
    assert post("/api/v1/rsa/demo/text/encrypt/") == 429
    assert post("/api/v1/rsa/demo/decrypt") == 200


def test_legacy_setting_rejects_typo(monkeypatch):
    from app.coordinator_http import legacy_api_enabled
    monkeypatch.setenv("RADH_LEGACY_API_ENABLED", "maybe")
    with pytest.raises(ValueError):
        legacy_api_enabled()


def test_middleware_resolves_current_app_state():
    first = Runtime(role_hashes={})
    second = Runtime(role_hashes={})
    selected = SimpleNamespace(runtime=first)

    async def scenario():
        sent = []

        async def stub(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            sent.append(message)

        middleware = CoordinatorMiddleware(stub, lambda: selected)
        selected.runtime = second
        await middleware(scope("/api/v2/dh/nodes"), receive, send)
        return sent

    sent = asyncio.run(scenario())
    assert (b"x-backend-epoch", second.coordinator.epoch.encode()) in sent[0]["headers"]
