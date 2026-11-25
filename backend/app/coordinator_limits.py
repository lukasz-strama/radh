"""Konfiguracja, ograniczone limitery i kontrola przyjęcia kosztownych wywołań."""

import math
import os
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, fields
from threading import BoundedSemaphore, Lock
from time import monotonic

from .sessions import SessionError


class CoordinatorError(SessionError):
    def __init__(self, status, code, message="Nie można wykonać operacji.", headers=None):
        super().__init__(status, code, message)
        self.headers = headers or {}


def reject(status, code, message="Nie można wykonać operacji.", retry=None):
    headers = {"Retry-After": str(retry)} if retry is not None else {}
    raise CoordinatorError(status, code, message, headers)


@dataclass(frozen=True)
class Settings:
    max_sessions: int = 128
    max_running_sessions: int = 32
    max_sessions_per_ip: int = 8
    session_created_ttl_seconds: int = 120
    session_max_age_seconds: int = 600
    session_retention_seconds: int = 300
    tombstone_ttl_seconds: int = 600
    max_tombstones: int = 256
    create_retry_ttl_seconds: int = 60
    max_create_retries: int = 128
    max_events: int = 32
    max_messages: int = 2
    max_interceptions: int = 2
    max_request_bytes: int = 4096
    max_response_bytes: int = 131072
    node_lease_seconds: int = 10
    participant_timeout_seconds: int = 30
    diagnostics_retry_seconds: int = 30
    cleanup_seconds: int = 5
    max_crypto_jobs: int = 2
    max_crypto_waiters: int = 8
    crypto_wait_seconds: int = 2
    create_rate_per_minute: int = 6
    create_rate_burst: int = 2
    crypto_rate_per_minute: int = 20
    crypto_rate_burst: int = 5
    rsa_text_rate_per_minute: int = 10
    rsa_text_rate_burst: int = 2
    read_token_rate_per_minute: int = 120
    read_ip_rate_per_minute: int = 240
    internal_rate_per_minute: int = 3000
    internal_rate_burst: int = 128
    max_rate_buckets: int = 4096
    rate_bucket_ttl_seconds: int = 600

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or value < 1:
                raise ValueError(f"Niepoprawna konfiguracja {field.name.upper()}.")
        caps = {
            "max_sessions": 128, "max_running_sessions": 32, "max_create_retries": 128,
            "max_events": 32, "max_messages": 2, "max_interceptions": 2,
            "max_request_bytes": 4096, "max_response_bytes": 131072,
            "session_max_age_seconds": 600,
        }
        if any(getattr(self, key) > limit for key, limit in caps.items()):
            raise ValueError("Konfiguracja przekracza ograniczenia kontraktu.")
        if self.max_events < 2:
            raise ValueError("Historia wymaga miejsca na utworzenie i terminalizację.")
        if self.max_running_sessions > self.max_sessions:
            raise ValueError("Limit running przekracza pojemność rejestru.")

    @classmethod
    def from_env(cls):
        values = {f.name: int(os.environ.get(f.name.upper(), f.default)) for f in fields(cls)}
        return cls(**values)


class RateLimiter:
    """Token bucket z ograniczoną pamięcią i osobnym wspólnym bucketem nadmiaru."""

    def __init__(self, settings, clock=monotonic):
        self.settings, self.clock = settings, clock
        self.lock = Lock()
        self.buckets = OrderedDict()
        self.overflow = {}

    def check(self, category, identity, rate, burst):
        now = self.clock()
        with self.lock:
            ttl = self.settings.rate_bucket_ttl_seconds
            while self.buckets and now - next(iter(self.buckets.values()))[2] >= ttl:
                self.buckets.popitem(last=False)
            key = (category, identity)
            storage = self.buckets
            if key not in storage and len(storage) >= self.settings.max_rate_buckets:
                # Kategorie pochodzą wyłącznie z kodu, nigdy z danych klienta.
                storage, key = self.overflow, category
            tokens, last, _ = storage.get(key, (float(burst), now, now))
            tokens = min(float(burst), tokens + (now - last) * rate / 60)
            if tokens < 1:
                storage[key] = (tokens, now, now)
                if storage is self.buckets:
                    storage.move_to_end(key)
                reject(429, "RATE_LIMITED", retry=max(1, math.ceil((1 - tokens) * 60 / rate)))
            storage[key] = (tokens - 1, now, now)
            if storage is self.buckets:
                storage.move_to_end(key)


class CryptoAdmission:
    """Ograniczona pula C i oczekujących, także przy nieudanym ładowaniu biblioteki."""

    def __init__(self, settings):
        self.wait_seconds = settings.crypto_wait_seconds
        self.capacity = BoundedSemaphore(settings.max_crypto_jobs + settings.max_crypto_waiters)
        self.jobs = BoundedSemaphore(settings.max_crypto_jobs)

    @contextmanager
    def slot(self):
        if not self.capacity.acquire(blocking=False):
            reject(503, "CRYPTO_BUSY", retry=2)
        acquired = False
        try:
            acquired = self.jobs.acquire(timeout=self.wait_seconds)
            if not acquired:
                reject(503, "CRYPTO_BUSY", retry=2)
            yield
        finally:
            if acquired:
                self.jobs.release()
            self.capacity.release()
