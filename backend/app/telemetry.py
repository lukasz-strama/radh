"""Ulotna telemetria Inspectora i osobny lokalny nasłuch SSE."""

import asyncio
import hmac
import ipaddress
import json
import logging
import os
import platform
import re
import secrets
import socket
from collections import deque
from contextlib import asynccontextmanager, nullcontext, suppress
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from itertools import islice
from threading import Lock
from time import perf_counter_ns
from uuid import uuid4

from starlette.applications import Starlette
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)
PATH = "/api/v1/debug/events"
TOKEN = re.compile(rb"[A-Za-z0-9_-]{43}")
CURSOR = re.compile(r"([0-9a-f]{32}):([0-9]{1,20})")
RING_CAPACITY = 1024
MAX_SUBSCRIBERS = 8
POLL_SECONDS = 0.15
HEARTBEAT_SECONDS = 5

_request_id = ContextVar("inspector_request_id", default=None)
_text_timing = ContextVar("inspector_text_timing", default=None)
_active = None
_main_ready = None

_DECIMALS = {
    "modulus", "public_exponent", "prime", "generator", "public_value",
    "alice_public", "bob_public",
}
_ENUMS = {
    "method": frozenset("GET HEAD POST PUT PATCH DELETE OPTIONS".split()),
    "scope": {"http", "python", "ffi", "ffi_sum"},
    "protocol": {"v1", "v2"},
    "state": {"created", "running", "completed", "cancelled", "failed", "expired"},
    "mode": {"normal", "mitm"},
    "scenario": {"classic", "authenticated", "unauthenticated"},
    "sender": {"alice", "bob", "mallory"},
    "recipient": {"alice", "bob", "mallory"},
    "role": {"alice", "bob", "mallory"},
    "code": frozenset("""
        INVALID_REQUEST INVALID_MODULUS INVALID_EXPONENT MESSAGE_OUT_OF_RANGE
        CIPHERTEXT_OUT_OF_RANGE INVALID_PRIME INVALID_GENERATOR INVALID_SECRET
        INVALID_P INVALID_Q EQUAL_PRIMES MODULUS_OVERFLOW INVALID_KEYGEN_EXPONENT
        PARAMETER_GENERATION_EXHAUSTED
        EXPONENT_NOT_COPRIME INTERNAL_ERROR CRYPTO_CORE_UNAVAILABLE
        TEXT_MODULUS_TOO_SMALL INVALID_UTF8 EMPTY_TEXT TEXT_TOO_LONG
        DECRYPTED_BYTE_OUT_OF_RANGE
    """.split()),
}
_SESSION_EVENTS = frozenset("""
    session_created session_started session_completed session_cancelled session_expired
    session_failed session_deleted public_value message_intercepted message_forwarded
    message_processed trusted_key_published signature_published signature_verified
    signature_rejected secret_reported rsa_key_parameters
""".split())


def _safe_fields(fields):
    safe = {}
    for key, value in fields.items():
        if key in _DECIMALS and type(value) is int and 0 <= value < 2**32:
            safe[key] = str(value)
        elif key in _ENUMS and type(value) is str and value in _ENUMS[key]:
            safe[key] = value
        elif key in {"status", "return_status"} and type(value) is int and -(2**31) <= value < 2**31:
            safe[key] = value
        elif key == "route" and type(value) is str and len(value) <= 160:
            # Wyłącznie szablon routera lub nazwa grupy, ustalone przez middleware.
            safe[key] = value
        elif key == "session" and type(value) is str and re.fullmatch(r"[0-9a-f]{24}", value):
            safe[key] = value
    return safe


def _event(event_id, level, source, event, duration_ns, data):
    return {
        "schema_version": 1,
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": level,
        "source": source,
        "event": event,
        "request_id": _request_id.get(),
        "duration_ns": duration_ns,
        "data": data,
    }


class EventBuffer:
    """Wspólne okno zdarzeń; tylko odczyt krótkiej partii wymaga blokady."""

    def __init__(self, version, capacity=RING_CAPACITY, max_subscribers=MAX_SUBSCRIBERS):
        self.capacity = capacity
        self.max_subscribers = max_subscribers
        self.version = version
        self.instance = uuid4().hex
        self.salt = secrets.token_bytes(32)
        self.started = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self._events = deque(maxlen=capacity)
        self._last = 0
        self._readers = 0
        self._lock = Lock()
        self._closed = False

    def publish(self, event):
        with self._lock:
            if not self._closed:
                self._last += 1
                event["event_id"] = self._last
                self._events.append(event)

    def subscribe(self, resume):
        with self._lock:
            if self._closed or self._readers >= self.max_subscribers:
                return None
            match = CURSOR.fullmatch(resume)
            cursor = int(match[2]) if match and match[1] == self.instance else None
            if cursor is not None and cursor > self._last:
                cursor = None
            self._readers += 1
            return (self._last if cursor is None else cursor, bool(resume and cursor is None))

    def unsubscribe(self):
        with self._lock:
            self._readers -= 1

    def close(self):
        with self._lock:
            self._closed = True

    def snapshot(self, cursor):
        with self._lock:
            first = self._last - len(self._events) + 1
            lost = max(0, first - cursor - 1)
            offset = max(0, cursor - first + 1)
            return self._closed, lost, tuple(islice(self._events, offset, offset + 64))

    def status(self):
        with self._lock:
            return {"buffer_capacity": self.capacity, "buffer_used": len(self._events)}

    def session(self, protocol, identifier):
        return hmac.digest(self.salt, f"{protocol}:{identifier}".encode(), "sha256").hex()[:24]


def publish(source, event, *, level="DEBUG", duration_ns=None, **fields):
    sink = _active
    if sink is not None:
        with suppress(Exception):
            sink.publish(_event(0, level, source, event, duration_ns, _safe_fields(fields)))


def session_event(protocol, view, event, **fields):
    sink = _active
    if sink is not None and event in _SESSION_EVENTS:
        with suppress(Exception):
            publish("dh.session", "dh." + event.replace("_", "."),
                    level="WARN" if event in {"session_failed", "signature_rejected"} else "INFO",
                    protocol=protocol, session=sink.session(protocol, view.session_id),
                    state=view.status, prime=view.prime, generator=view.generator,
                    mode=view.mode, scenario=getattr(view, "scenario", None),
                    sender=fields.get("sender"), recipient=fields.get("recipient"),
                    public_value=fields.get("public_value"), role=fields.get("role"),
                    modulus=fields.get("modulus"), public_exponent=fields.get("public_exponent"))


def _error_code(error):
    with suppress(Exception):
        code = getattr(error, "code", None)
        if type(code) is str and code in _ENUMS["code"]:
            return code
    return "INTERNAL_ERROR"


def operation(source, name, *, public=None, result=None, text=False):
    """Mierz nakładkę bez odwzorowywania argumentów ani wyniku jako całości."""

    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            if _active is None or _text_timing.get() is not None:
                return function(*args, **kwargs)
            fields = {}
            with suppress(Exception):
                if public is not None:
                    fields = public(*args, **kwargs)
            publish(source, name + ".started", scope="python", **fields)
            timings = {} if text else None
            token = _text_timing.set(timings) if text else None
            start = perf_counter_ns()
            try:
                try:
                    value = function(*args, **kwargs)
                finally:
                    elapsed = perf_counter_ns() - start
                    if token is not None:
                        _text_timing.reset(token)
                        with suppress(Exception):
                            for symbol, (raw_status, total) in timings.items():
                                _ffi_event(symbol, raw_status, total, "ffi_sum")
            except Exception as error:
                publish(source, name + ".failed", level="WARN", scope="python", duration_ns=elapsed,
                        code=_error_code(error), **fields)
                raise
            else:
                with suppress(Exception):
                    if result is not None:
                        fields.update(result(value))
                publish(source, name + ".completed", scope="python", duration_ns=elapsed, **fields)
                return value
        return measured
    return decorate


def _ffi_event(symbol, status, elapsed, scope):
    publish("crypto.core", symbol + (".completed" if status == 0 else ".failed"),
            level="DEBUG" if status == 0 else "WARN", duration_ns=elapsed,
            return_status=status, scope=scope)


def call_c(symbol, function, *args):
    if _active is None:
        return function(*args)
    started = perf_counter_ns()
    status = None
    try:
        status = function(*args)
        return status
    finally:
        elapsed = perf_counter_ns() - started
        with suppress(Exception):
            timings = _text_timing.get()
            if timings is None:
                _ffi_event(symbol, status, elapsed, "ffi")
            else:
                timings[symbol] = (status, elapsed + timings.get(symbol, (0, 0))[1])


class RequestTelemetry:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if _active is None or scope["type"] != "http":
            return await self.app(scope, receive, send)
        if _main_ready is not None and not _main_ready.is_set():
            _main_ready.set()
        path = scope.get("path", "")
        if not path.startswith(("/api/", "/internal/")):
            return await self.app(scope, receive, send)

        request_token = _request_id.set(uuid4().hex)
        started = perf_counter_ns()
        status = None

        async def observed_send(message):
            nonlocal status
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]

        try:
            return await self.app(scope, receive, observed_send)
        except Exception:
            if status is None:
                status = 500
            raise
        finally:
            with suppress(Exception):
                route = getattr(scope.get("route"), "path", None)
                if route is None:
                    route = "/internal/*" if path.startswith("/internal/") else "/api/*"
                level = "ERROR" if status and status >= 500 else "WARN" if status is None or status >= 400 else "INFO"
                publish("http.api", "http.request.completed" if status else "http.request.disconnected",
                        level=level, duration_ns=perf_counter_ns() - started, scope="http",
                        method=scope.get("method"), route=route, status=status)
            _request_id.reset(request_token)


def _frame(event, event_id=None):
    prefix = "" if event_id is None else f"id: {event_id}\n"
    return prefix + "data: " + json.dumps(event, separators=(",", ":")) + "\n\n"


async def _stream(buffer, cursor, reset):
    system = {"backend_version": buffer.version, "python_version": platform.python_version(),
              "platform": platform.system(), "instance": buffer.instance,
              "started_at": buffer.started, **buffer.status()}
    yield _frame(_event(0, "INFO", "system.backend", "system.started", None, system),
                 f"{buffer.instance}:{cursor}")
    if reset:
        yield _frame(_event(0, "WARN", "system.telemetry", "telemetry.reset", None, {}))
    loop = asyncio.get_running_loop()
    heartbeat_at = loop.time() + HEARTBEAT_SECONDS
    while True:
        closed, lost, batch = buffer.snapshot(cursor)
        if closed:
            return
        if lost:
            cursor += lost
            gap = _event(cursor, "WARN", "system.telemetry", "telemetry.gap", None, {"dropped": lost})
            yield _frame(gap, f"{buffer.instance}:{cursor}")
        for item in batch:
            cursor = item["event_id"]
            yield _frame(item, f"{buffer.instance}:{cursor}")
        if loop.time() >= heartbeat_at:
            status = _event(0, "DEBUG", "system.telemetry", "telemetry.status", None, buffer.status())
            yield ": heartbeat\n\n" + _frame(status)
            heartbeat_at = loop.time() + HEARTBEAT_SECONDS
        await asyncio.sleep(0 if len(batch) == 64 else POLL_SECONDS)


class EventStream(StreamingResponse):
    # Starlette obsługuje anulowanie generatora i rozłączenia ASGI. Licznik ma
    # ten sam cykl życia także przy zerwaniu przed pierwszym wysłaniem danych.
    def __init__(self, buffer, resume):
        self.buffer = buffer
        self.resume = resume
        super().__init__(iter(()), media_type="text/event-stream",
                         headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    async def __call__(self, scope, receive, send):
        subscription = self.buffer.subscribe(self.resume)
        if subscription is None:
            return await Response(status_code=503, headers={"Retry-After": "5"})(scope, receive, send)
        cursor, reset = subscription

        self.body_iterator = _stream(self.buffer, cursor, reset)
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await self.body_iterator.aclose()
            finally:
                self.buffer.unsubscribe()


def debug_app(buffer, token, *, local_only=True):
    async def connect(request):
        peer = request.client
        if local_only:
            try:
                loopback = peer is not None and ipaddress.ip_address(peer.host).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                return Response(status_code=403)
        # Nie przyjmujemy poświadczeń z URL, ciasteczek ani nagłówków proxy.
        credentials = [value for name, value in request.scope["headers"] if name == b"authorization"]
        if (len(credentials) != 1 or not credentials[0].startswith(b"Bearer ")
                or TOKEN.fullmatch(credentials[0][7:]) is None
                or not hmac.compare_digest(credentials[0][7:], token)):
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})
        if request.method != "GET":
            return Response(status_code=405, headers={"Allow": "GET"})
        return EventStream(buffer, request.headers.get("last-event-id", ""))

    app = Starlette(routes=[Route(PATH, connect, methods=["GET"])])
    app.router.redirect_slashes = False
    return app


@asynccontextmanager
async def serving(version):
    global _active, _main_ready
    if os.environ.get("RADH_DEBUG_ENABLED", "false").lower() != "true":
        yield
        return

    import uvicorn

    class DebugServer(uvicorn.Server):
        # Główny serwer zachowuje obsługę sygnałów i steruje tym nasłuchem.
        def capture_signals(self):
            return nullcontext()

    try:
        token = os.environ.get("RADH_DEBUG_TOKEN", "").encode("ascii")
        host = os.environ.get("RADH_DEBUG_BIND", "127.0.0.1")
        port = int(os.environ.get("RADH_DEBUG_PORT", "8001"))
        if TOKEN.fullmatch(token) is None or host not in {"127.0.0.1", "0.0.0.0"} or not 1 <= port <= 65535:
            raise ValueError()
        buffer = EventBuffer(version)
        server = DebugServer(uvicorn.Config(
            debug_app(buffer, token, local_only=host == "127.0.0.1"),
            log_config=None, access_log=False, proxy_headers=False, ws="none",
            lifespan="off", limit_concurrency=32, timeout_graceful_shutdown=1,
        ))
    except Exception:
        logger.warning("Inspector telemetry unavailable: invalid debug configuration")
        yield
        return

    main_ready = asyncio.Event()
    _main_ready = main_ready
    _active = buffer

    async def listen():
        global _active
        await main_ready.wait()
        if server.should_exit:
            return
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((host, port))
                listener.listen(16)
                listener.setblocking(False)
                logger.info("Inspector telemetry enabled on port %s", port)
                await server.serve(sockets=[listener])
        except Exception:
            logger.warning("Inspector telemetry unavailable: debug listener failed")
        finally:
            _active = None
            buffer.close()

    # Pierwsze żądanie potwierdza, że główny serwer już zajął swój port.
    task = asyncio.create_task(listen())
    try:
        yield
    finally:
        _main_ready = None
        _active = None
        buffer.close()
        server.should_exit = True
        main_ready.set()
        await task
