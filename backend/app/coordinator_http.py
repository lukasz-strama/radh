"""Uwierzytelnianie, limity HTTP i cykl życia koordynatora."""

import asyncio
import hmac
import ipaddress
import logging
import os
import re
from contextlib import asynccontextmanager, nullcontext, suppress
from pathlib import Path

from fastapi import Request
from starlette.responses import JSONResponse

from .coordinator import Coordinator, ROLES, digest
from .coordinator_limits import CoordinatorError, CryptoAdmission, RateLimiter, Settings, reject

logger = logging.getLogger(__name__)

BEARER = re.compile(r"Bearer ([A-Za-z0-9_-]{43})")
LEGACY_V1_PATHS = frozenset({
    "/api/v1/rsa/demo/encrypt",
    "/api/v1/rsa/demo/keygen",
    "/api/v1/dh/demo/exchange",
    "/api/v1/dh/sessions",
    "/api/v1/dh/nodes",
})
LEGACY_V1_PREFIXES = ("/api/v1/dh/sessions/", "/api/v1/dh/nodes/")
RSA_TEXT_PATHS = frozenset({
    "/api/v1/rsa/demo/text/encrypt",
    "/api/v1/rsa/demo/text/decrypt",
})
PARAMETER_GENERATION_PATHS = frozenset({
    "/api/v1/rsa/demo/parameters",
    "/api/v1/dh/demo/parameters",
})


def bearer(value):
    match = BEARER.fullmatch(value or "")
    if match is None:
        raise CoordinatorError(401, "UNAUTHORIZED", "Wymagany token Bearer.",
                               {"WWW-Authenticate": "Bearer"})
    return match[1]


def legacy_api_enabled():
    value = os.environ.get("RADH_LEGACY_API_ENABLED", "true").lower()
    if value not in {"true", "false"}:
        raise ValueError("RADH_LEGACY_API_ENABLED wymaga true lub false.")
    return value == "true"


def role_credentials():
    hashes = {}
    for role in ROLES:
        filename = os.environ.get("RADH_" + role.upper() + "_TOKEN_FILE")
        if filename:
            try:
                with Path(filename).open("rb") as stream:
                    raw = stream.read(129)
                token = raw.decode("ascii").strip()
                if len(raw) > 128 or re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
                    raise ValueError()
                hashes[role] = digest(token)
            except (OSError, UnicodeError, ValueError):
                raise ValueError("Niepoprawny plik poświadczenia roli " + role) from None
    if len(set(hashes.values())) != len(hashes):
        raise ValueError("Role wymagają różnych poświadczeń.")
    return hashes


class Runtime:
    def __init__(self, settings=None, *, clock=None, role_hashes=None):
        self.settings = settings or Settings.from_env()
        self.legacy_api_enabled = legacy_api_enabled()
        clock_args = {} if clock is None else {"clock": clock}
        self.coordinator = Coordinator(self.settings, **clock_args)
        self.limiter = RateLimiter(self.settings, **clock_args)
        self.crypto = CryptoAdmission(self.settings)
        self.role_hashes = role_credentials() if role_hashes is None else role_hashes
        self.origins = frozenset(os.environ.get(
            "RADH_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
        ).split(","))

    def demo_slot(self):
        # Tryb migracji zachowuje dotychczasowe zachowanie demo v1.
        return nullcontext() if self.legacy_api_enabled else self.crypto.slot()

    def new_crypto_slot(self):
        """Losowanie parametrów i nowe operacje RSA zawsze zajmują slot kolejki."""

        return self.crypto.slot()

    def authenticate_role(self, token):
        candidate = digest(token)
        role = None
        for name, expected in self.role_hashes.items():
            if hmac.compare_digest(candidate, expected):
                role = name
        if role is None:
            raise CoordinatorError(401, "UNAUTHORIZED", "Niepoprawny token roli.",
                                   {"WWW-Authenticate": "Bearer"})
        return role

    def admit(self, scope, headers):
        path = scope["path"].rstrip("/")
        cfg = self.settings
        origin = headers.get("origin")
        if origin is not None and origin not in self.origins:
            reject(403, "ORIGIN_NOT_ALLOWED")
        host = (scope.get("client") or ("unknown", 0))[0]
        try:
            host = ipaddress.ip_address(host).compressed
        except ValueError:
            host = "unknown"
        ip_hash = self.coordinator.ip_identity(host)
        state = scope.setdefault("state", {})
        state["client_ip"] = host
        if path.startswith("/internal/v1/dh/"):
            token = bearer(headers.get("authorization"))
            role = self.authenticate_role(token)
            state["node_role"] = role
            self.limiter.check("internal", role, cfg.internal_rate_per_minute, cfg.internal_rate_burst)
        elif path == "/api/v2/dh/sessions" and scope["method"] == "POST":
            self.limiter.check("create", ip_hash, cfg.create_rate_per_minute, cfg.create_rate_burst)
        elif path.startswith("/api/v2/dh/"):
            self.limiter.check("read-ip", ip_hash, cfg.read_ip_rate_per_minute, cfg.read_ip_rate_per_minute)
            if path.startswith("/api/v2/dh/sessions/"):
                token = bearer(headers.get("authorization"))
                self.limiter.check("read-token", digest(token),
                                   cfg.read_token_rate_per_minute, cfg.read_token_rate_per_minute)
        elif path in RSA_TEXT_PATHS:
            self.limiter.check(
                "rsa-text", ip_hash,
                cfg.rsa_text_rate_per_minute, cfg.rsa_text_rate_burst,
            )
        elif path in PARAMETER_GENERATION_PATHS:
            self.limiter.check(
                "parameters", ip_hash,
                cfg.parameter_rate_per_minute, cfg.parameter_rate_burst,
            )
        elif path.startswith("/api/v1/"):
            self.limiter.check("crypto", ip_hash, cfg.crypto_rate_per_minute, cfg.crypto_rate_burst)


@asynccontextmanager
async def lifespan(app):
    runtime = Runtime()
    app.state.runtime = runtime

    async def cleanup_loop():
        while True:
            await asyncio.sleep(runtime.settings.cleanup_seconds)
            await asyncio.to_thread(runtime.coordinator.cleanup)

    task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def runtime(request: Request):
    return request.app.state.runtime


class CoordinatorMiddleware:
    """Ogranicza body przed parsowaniem, także dla chunked i bez Content-Length."""

    def __init__(self, app, app_state):
        self.app, self.app_state = app, app_state

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "").rstrip("/")
        if scope["type"] != "http" or not path.startswith(("/api/", "/internal/")):
            return await self.app(scope, receive, send)
        state = self.app_state() if callable(self.app_state) else self.app_state
        rt = state.runtime
        # Tryb zgodności obejmuje historyczne demo i routery sesji/obecności v1.
        if rt.legacy_api_enabled and (path in LEGACY_V1_PATHS or path.startswith(LEGACY_V1_PREFIXES)):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        response_headers = {"Cache-Control": "no-store"}
        if path.startswith(("/api/v2/", "/internal/")):
            response_headers["X-Backend-Epoch"] = rt.coordinator.epoch
        try:
            sensitive = {b"authorization", b"idempotency-key", b"x-backend-epoch",
                         b"x-node-instance", b"origin", b"content-type"}
            seen = set()
            for key, _ in scope["headers"]:
                name = key.lower()
                if name in sensitive and name in seen:
                    reject(400, "BAD_REQUEST")
                seen.add(name)
            rt.admit(scope, headers)
            data = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(data) + len(chunk) > rt.settings.max_request_bytes:
                    reject(413, "REQUEST_TOO_LARGE")
                data.extend(chunk)
                if not message.get("more_body", False):
                    break
            if data and headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                reject(415, "UNSUPPORTED_MEDIA_TYPE")
        except CoordinatorError as error:
            response = JSONResponse(
                {"error": {"code": error.code, "message": error.message}},
                status_code=error.status, headers={**error.headers, **response_headers},
            )
            return await response(scope, receive, send)

        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(data), "more_body": False}
            return await receive()

        start = None
        chunks = bytearray()
        oversized = False

        async def bounded_send(message):
            nonlocal start, oversized
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                if len(chunks) + len(message.get("body", b"")) > rt.settings.max_response_bytes:
                    oversized = True
                elif not oversized:
                    chunks.extend(message.get("body", b""))

        try:
            await self.app(scope, replay, bounded_send)
        except Exception:
            logger.error("Unhandled coordinator request error")
            response = JSONResponse(
                {"error": {"code": "INTERNAL_ERROR", "message": "Nieoczekiwany błąd serwera."}},
                status_code=500, headers=response_headers,
            )
            return await response(scope, receive, send)
        if oversized:
            response = JSONResponse(
                {"error": {"code": "SERVICE_UNAVAILABLE", "message": "Odpowiedź przekracza limit."}},
                status_code=503, headers={**response_headers, "Retry-After": "5"},
            )
            return await response(scope, receive, send)
        if start is not None:
            replaced = {key.lower().encode() for key in response_headers}
            start["headers"] = [(k, v) for k, v in start["headers"] if k.lower() not in replaced]
            start["headers"].extend((k.lower().encode(), v.encode()) for k, v in response_headers.items())
            await send(start)
            await send({"type": "http.response.body", "body": bytes(chunks)})
