"""Ograniczony rejestr sesji DH, uprawnienia i atomowy protokół normal/MITM."""

import hashlib
import hmac
import math
import re
import secrets
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from time import monotonic
from uuid import uuid4

from .coordinator_limits import Settings, reject
from .multi_models import (
    AuthenticationState, Created, Descriptor, Discovery, Event, Events, Heartbeat,
    Inbox, Interceptions, NodePresence, Presence, SessionView, Signature,
    TrustedKey, Verification,
)
from .session_models import (
    CreateSession, Interception, MalloryDiagnostics, Message, SessionDiagnostics,
)

ROLES = ("alice", "bob", "mallory")
ACTIVE = {"created", "running"}
PROTOCOL_STATES = {"running", "completed"}
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def digest(value):
    return hashlib.sha256(value.encode("ascii")).digest()


def credential(value):
    if not isinstance(value, str) or TOKEN.fullmatch(value) is None:
        reject(400, "BAD_REQUEST", "Niepoprawne poświadczenie tworzenia.")
    return value


@dataclass(repr=False)
class Record:
    view: SessionView
    owner_hash: bytes
    create_hash: bytes
    ip_hash: bytes
    deadline: float
    absolute_deadline: float
    progress_at: float
    lock: RLock = field(default_factory=RLock)
    assignments: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    diagnostics: SessionDiagnostics = field(default_factory=SessionDiagnostics)
    mallory_diagnostics: MalloryDiagnostics = field(default_factory=MalloryDiagnostics)
    terminal_time: float | None = None


@dataclass(repr=False)
class Tombstone:
    owner_hash: bytes
    create_hash: bytes
    assignments: dict
    deadline: float


@dataclass(repr=False)
class CreationRetry:
    params: dict
    result: Created
    deadline: float


@dataclass
class Lease:
    instance: str
    deadline: float


class Coordinator:
    """Blokada rejestru poprzedza blokadę rekordu. Operacje protokołu blokują własną sesję."""

    def __init__(self, settings=None, *, clock=monotonic, utc=None):
        self.settings = settings or Settings()
        self.clock = clock
        self.utc = utc or (lambda: datetime.now(timezone.utc))
        self.epoch = uuid4().hex
        self.ip_key = secrets.token_bytes(32)
        self.lock = RLock()
        self.records = {}
        self.tombstones = OrderedDict()
        self.retries = {}
        self.leases = {}

    def ip_identity(self, ip):
        return hmac.digest(self.ip_key, ip.encode(), "sha256")

    def _reserve_events(self, record, count):
        if len(record.events) + count > self.settings.max_events:
            reject(409, "EVENT_LIMIT_REACHED")

    def _event(self, record, event_type, **fields):
        record.events.append(Event(
            sequence=len(record.events) + 1, type=event_type, created_at=self.utc(), **fields,
        ))
        record.view.revision += 1

    def _terminal(self, record, status, code=None, *, at=None):
        record.view.status = status
        record.view.failure_code = code
        record.terminal_time = self.clock() if at is None else at
        elapsed = max(0, self.clock() - record.terminal_time)
        record.view.terminal_at = self.utc() - timedelta(seconds=elapsed)
        if status in {"expired", "failed", "cancelled"}:
            record.diagnostics = SessionDiagnostics()
            record.mallory_diagnostics = MalloryDiagnostics()
        # Rezerwa na terminalizację jest sprawdzana przed każdą mutacją protokołu.
        self._event(record, "session_" + status)

    def _remove(self, sid, record, now):
        self.records.pop(sid)
        self.retries.pop(record.create_hash, None)
        self.tombstones[sid] = Tombstone(
            record.owner_hash, record.create_hash, record.assignments.copy(),
            now + self.settings.tombstone_ttl_seconds,
        )
        while len(self.tombstones) > self.settings.max_tombstones:
            self.tombstones.popitem(last=False)

    def _cleanup_locked(self):
        now = self.clock()
        for key, retry in list(self.retries.items()):
            if now >= retry.deadline:
                del self.retries[key]
        for sid, tombstone in list(self.tombstones.items()):
            if now >= tombstone.deadline:
                del self.tombstones[sid]
        for sid, record in list(self.records.items()):
            with record.lock:
                if record.view.status in ACTIVE and now >= record.deadline:
                    self._terminal(record, "expired", at=record.deadline)
                elif record.view.status == "running":
                    offline = any(
                        role not in self.leases or now >= self.leases[role].deadline
                        for role in record.assignments
                    )
                    if offline:
                        self._terminal(record, "failed", "NODE_UNAVAILABLE")
                    elif now - record.progress_at >= self.settings.participant_timeout_seconds:
                        self._terminal(record, "failed", "PARTICIPANT_TIMEOUT",
                                       at=record.progress_at + self.settings.participant_timeout_seconds)
                if (record.terminal_time is not None
                        and now >= record.terminal_time + self.settings.session_retention_seconds):
                    self._remove(sid, record, now)

    def cleanup(self):
        with self.lock:
            self._cleanup_locked()

    def _owner(self, sid, token):
        record = self.records.get(sid)
        tombstone = self.tombstones.get(sid)
        expected = record.owner_hash if record else tombstone.owner_hash if tombstone else b""
        if not hmac.compare_digest(expected, digest(token)):
            reject(404, "SESSION_NOT_FOUND", "Nie znaleziono sesji.")
        if record is None:
            reject(410, "SESSION_EXPIRED", "Sesja wygasła.")
        return record

    def _instance(self, role, epoch, instance):
        if epoch != self.epoch:
            reject(409, "BACKEND_EPOCH_MISMATCH")
        lease = self.leases.get(role)
        if lease is None or lease.instance != instance or self.clock() >= lease.deadline:
            reject(409, "NODE_INSTANCE_MISMATCH")

    @contextmanager
    def access(self, sid, *, token=None, role=None, epoch=None, instance=None, registry=False):
        """Autoryzacja przed odczytem, snapshoty i mutacje pod tą samą blokadą."""
        self.lock.acquire()
        record = None
        registry_held = True
        record_held = False
        try:
            self._cleanup_locked()
            if role is None:
                record = self._owner(sid, token)
            else:
                self._instance(role, epoch, instance)
                record = self.records.get(sid)
                tombstone = self.tombstones.get(sid)
                if record is None and tombstone is None:
                    reject(404, "SESSION_NOT_FOUND")
                assignments = record.assignments if record else tombstone.assignments
                if assignments.get(role) != instance:
                    reject(403, "ROLE_NOT_ASSIGNED")
                if record is None:
                    reject(410, "SESSION_EXPIRED")
            record.lock.acquire()
            record_held = True
            if not registry:
                self.lock.release()
                registry_held = False
            yield record
        finally:
            if record_held:
                record.lock.release()
            if registry_held:
                self.lock.release()

    def create(self, request, key, epoch, ip):
        credential(key)
        if epoch != self.epoch:
            reject(409, "BACKEND_EPOCH_MISMATCH")
        key_hash, ip_hash = digest(key), self.ip_identity(ip)
        params = request.model_dump()
        # Matematyczna walidacja jest bezstanowa i odbywa się poza blokadami.
        # Idempotencję sprawdzamy przed nią, ponownie także przed zapisem.
        with self.lock:
            self._cleanup_locked()
            existing = self._creation_retry(key_hash, params)
            if existing is not None:
                return existing
        CreateSession(prime=request.prime, generator=request.generator, mode=request.mode)
        with self.lock:
            self._cleanup_locked()
            existing = self._creation_retry(key_hash, params)
            if existing is not None:
                return existing
            cfg = self.settings
            if len(self.records) >= cfg.max_sessions or len(self.retries) >= cfg.max_create_retries:
                reject(503, "SESSION_CAPACITY", retry=5)
            active_for_ip = sum(
                record.ip_hash == ip_hash and record.view.status in ACTIVE
                for record in self.records.values()
            )
            if active_for_ip >= cfg.max_sessions_per_ip:
                reject(429, "RATE_LIMITED", retry=cfg.session_created_ttl_seconds)
            now, date = self.clock(), self.utc()
            sid = uuid4().hex
            while sid in self.records or sid in self.tombstones:
                sid = uuid4().hex
            token = secrets.token_urlsafe(32)
            ttl = min(cfg.session_created_ttl_seconds, cfg.session_max_age_seconds)
            view = SessionView(
                **params, session_id=sid, backend_epoch=self.epoch,
                created_at=date, expires_at=date + timedelta(seconds=ttl),
                authentication=AuthenticationState(
                    session_id=sid, backend_epoch=self.epoch,
                ),
            )
            record = Record(view, digest(token), key_hash, ip_hash,
                            now + ttl, now + cfg.session_max_age_seconds, now)
            self._event(record, "session_created")
            self.records[sid] = record
            result = Created(session=view.model_copy(deep=True), session_token=token)
            self.retries[key_hash] = CreationRetry(params, result, now + cfg.create_retry_ttl_seconds)
            return result.model_copy(deep=True)

    def _creation_retry(self, key_hash, params):
        if any(t.create_hash == key_hash for t in self.tombstones.values()):
            reject(410, "CREATION_GONE")
        cached = self.retries.get(key_hash)
        if cached:
            if cached.params != params:
                reject(409, "IDEMPOTENCY_CONFLICT")
            return cached.result.model_copy(deep=True)
        if any(r.create_hash == key_hash for r in self.records.values()):
            reject(409, "CREATE_RETRY_EXPIRED")
        return None

    def get(self, sid, token):
        with self.access(sid, token=token) as record:
            return record.view.model_copy(deep=True)

    def transition(self, sid, token, action):
        with self.access(sid, token=token, registry=True) as record:
            view = record.view
            if action == "start":
                if view.status in PROTOCOL_STATES:
                    return view.model_copy(deep=True)
                if view.status != "created":
                    reject(409, "INVALID_SESSION_STATE")
                roles = ROLES if view.mode == "mitm" else ROLES[:2]
                if any(role not in self.leases or self.clock() >= self.leases[role].deadline
                       for role in roles):
                    reject(409, "NODE_UNAVAILABLE")
                running = sum(r.view.status == "running" for r in self.records.values())
                if running >= self.settings.max_running_sessions:
                    reject(503, "RUNNING_CAPACITY", retry=5)
                self._reserve_events(record, 2)
                record.assignments = {role: self.leases[role].instance for role in roles}
                record.deadline = record.absolute_deadline
                view.expires_at = view.created_at + timedelta(seconds=self.settings.session_max_age_seconds)
                view.status = "running"
                record.progress_at = self.clock()
                self._event(record, "session_started")
            elif action == "cancel":
                if view.status == "cancelled":
                    return view.model_copy(deep=True)
                if view.status not in ACTIVE:
                    reject(409, "INVALID_SESSION_STATE")
                self._reserve_events(record, 1)
                self._terminal(record, "cancelled")
            else:
                raise ValueError("Nieznana operacja przejścia.")
            return view.model_copy(deep=True)

    def delete(self, sid, token):
        with self.lock:
            self._cleanup_locked()
            tombstone = self.tombstones.get(sid)
            if tombstone and hmac.compare_digest(tombstone.owner_hash, digest(token)):
                return
            record = self._owner(sid, token)
            with record.lock:
                self._remove(sid, record, self.clock())

    def events(self, sid, token, after=0, limit=32):
        with self.access(sid, token=token) as record:
            events = [e.model_copy(deep=True) for e in record.events if e.sequence > after][:limit]
            return Events(session_id=sid, backend_epoch=self.epoch, events=events,
                          next_after=events[-1].sequence if events else after)

    def diagnostics(self, sid, token, mallory=False):
        with self.access(sid, token=token) as record:
            source = record.mallory_diagnostics if mallory else record.diagnostics
            return source.model_copy(deep=True)

    def heartbeat(self, role, instance):
        with self.lock:
            now = self.clock()
            old = self.leases.get(role)
            if old and old.instance != instance:
                if now < old.deadline:
                    reject(409, "NODE_INSTANCE_CONFLICT")
                for record in self.records.values():
                    with record.lock:
                        if (record.view.status == "running"
                                and record.assignments.get(role) == old.instance):
                            self._terminal(record, "failed", "NODE_RESTARTED")
            # Ta sama instancja po utracie lease nie może ożywić starej sesji.
            self._cleanup_locked()
            self.leases[role] = Lease(instance, now + self.settings.node_lease_seconds)
            return Heartbeat(backend_epoch=self.epoch, instance_id=instance,
                             lease_seconds=self.settings.node_lease_seconds)

    def presence(self):
        with self.lock:
            self._cleanup_locked()
            now = self.clock()
            return Presence(**{
                role: NodePresence(online=role in self.leases and now < self.leases[role].deadline)
                for role in ROLES
            })

    def discover(self, role, epoch, instance):
        with self.lock:
            self._cleanup_locked()
            self._instance(role, epoch, instance)
            descriptors = []
            for record in self.records.values():
                with record.lock:
                    if record.assignments.get(role) != instance:
                        continue
                    view = record.view
                    # Dla completed TTL deskryptora wskazuje pozostałe okno diagnostyki.
                    deadline = record.deadline
                    if view.status == "completed":
                        deadline = min(deadline, record.terminal_time + self.settings.diagnostics_retry_seconds)
                    received = (record.mallory_diagnostics.shared_with_alice is not None if role == "mallory"
                                else getattr(record.diagnostics, role) is not None)
                    descriptors.append(Descriptor(
                        **view.model_dump(include={
                            "session_id", "backend_epoch", "prime", "generator", "mode",
                            "scenario", "diagnostics_enabled", "status", "revision",
                            "expires_at",
                        }),
                        remaining_ttl_seconds=max(0, math.floor(deadline - self.clock())),
                        participant_status=None if role == "mallory" else getattr(view.participants, role),
                        diagnostics_received=received,
                    ))
            return Discovery(backend_epoch=self.epoch, sessions=descriptors)

    @staticmethod
    def _protocol(record):
        if record.view.status not in PROTOCOL_STATES:
            reject(409, "INVALID_SESSION_STATE")

    def publish(self, record, role, request):
        self._protocol(record)
        if role not in ROLES[:2]:
            reject(403, "ROLE_FORBIDDEN")
        view = record.view
        if view.scenario == "authenticated" and not any(
            key.owner == role for key in view.authentication.trusted_keys
        ):
            reject(409, "TRUSTED_KEY_REQUIRED")
        if request.message_id != role + "-public" or not 1 <= request.public_value < view.prime:
            reject(422, "INVALID_MESSAGE")
        for message in view.messages:
            if message.message_id == request.message_id:
                interception = next((i for i in view.interceptions if i.message_id == message.message_id), None)
                original = interception.original_value if interception else message.public_value
                if original != request.public_value:
                    reject(409, "MESSAGE_ID_CONFLICT")
                return message.model_copy(deep=True)
        if view.status != "running":
            reject(409, "INVALID_SESSION_STATE")
        if len(view.messages) >= self.settings.max_messages:
            reject(409, "PUBLIC_VALUE_ALREADY_SENT")
        if view.mode == "mitm" and len(view.interceptions) >= self.settings.max_interceptions:
            reject(409, "EVENT_LIMIT_REACHED")
        self._reserve_events(record, 2)
        recipient = "bob" if role == "alice" else "alice"
        message = Message(
            **request.model_dump(), sender=role, recipient=recipient,
            status="intercepted" if view.mode == "mitm" else "queued",
        )
        if view.mode == "mitm":
            view.interceptions.append(Interception(
                message_id=message.message_id, original_sender=role,
                recipient=recipient, original_value=message.public_value,
            ))
        view.messages.append(message)
        setattr(view.participants, role, "published")
        self._event(record, "message_intercepted" if view.mode == "mitm" else "public_value",
                    **message.model_dump(exclude={"type"}))
        record.progress_at = self.clock()
        return message.model_copy(deep=True)

    def inbox(self, record, role):
        self._protocol(record)
        if role not in ROLES[:2]:
            reject(403, "ROLE_FORBIDDEN")
        return Inbox(
            session_id=record.view.session_id, backend_epoch=self.epoch,
            revision=record.view.revision,
            messages=[m.model_copy(deep=True) for m in record.view.messages
                      if m.recipient == role and m.status == "queued"],
        )

    def interceptions(self, record, role):
        self._protocol(record)
        self._mallory(record, role)
        return Interceptions(
            session_id=record.view.session_id, backend_epoch=self.epoch,
            revision=record.view.revision,
            interceptions=[i.model_copy(deep=True) for i in record.view.interceptions],
        )

    @staticmethod
    def _mallory(record, role):
        if role != "mallory":
            reject(403, "ROLE_FORBIDDEN")
        if record.view.mode != "mitm":
            reject(409, "MITM_REQUIRED")

    def forward(self, record, role, mid, value):
        self._protocol(record)
        self._mallory(record, role)
        view = record.view
        interception = next((i for i in view.interceptions if i.message_id == mid), None)
        if interception is None:
            reject(404, "MESSAGE_NOT_FOUND")
        if not 1 <= value < view.prime:
            reject(422, "INVALID_MESSAGE")
        if interception.delivered_value is not None:
            if interception.delivered_value != value:
                reject(409, "REPLACEMENT_CONFLICT")
            return interception.model_copy(deep=True)
        if view.status != "running":
            reject(409, "INVALID_SESSION_STATE")
        self._reserve_events(record, 2)
        message = next(m for m in view.messages if m.message_id == mid)
        interception.delivered_value = value
        interception.actual_sender = "mallory"
        interception.status = "forwarded"
        message.public_value, message.status = value, "queued"
        self._event(record, "message_forwarded", sender="mallory", recipient=message.recipient,
                    public_value=value, message_id=mid, status="queued")
        record.progress_at = self.clock()
        return interception.model_copy(deep=True)

    def acknowledge(self, record, role, mid):
        self._protocol(record)
        if role not in ROLES[:2]:
            reject(403, "ROLE_FORBIDDEN")
        view = record.view
        message = next((m for m in view.messages if m.message_id == mid), None)
        if message is None:
            reject(404, "MESSAGE_NOT_FOUND")
        if message.recipient != role:
            reject(403, "ROLE_FORBIDDEN")
        if message.status == "processed":
            return message.model_copy(deep=True)
        if message.status == "intercepted":
            reject(409, "INTERCEPTION_REQUIRED")
        if getattr(view.participants, role) == "waiting":
            reject(409, "PUBLIC_VALUE_REQUIRED")
        if view.scenario == "authenticated" and not any(
            verification.verifier == role and verification.verified
            for verification in view.authentication.verifications
        ):
            reject(409, "VERIFICATION_REQUIRED")
        completing = all(m.message_id == mid or m.status == "processed" for m in view.messages)
        authenticated = (
            view.scenario == "authenticated"
            and len(view.authentication.verifications) == 2
            and all(item.verified for item in view.authentication.verifications)
        )
        terminal = completing and len(view.messages) == 2 and (
            view.scenario == "classic" or authenticated
        )
        self._reserve_events(record, 2 if terminal else 1)
        message.status = "processed"
        for interception in view.interceptions:
            if interception.message_id == mid:
                interception.status = "processed"
        setattr(
            view.participants,
            role,
            "verified" if view.scenario == "authenticated" else "received",
        )
        self._event(record, "message_processed", **message.model_dump(exclude={"type", "status"}))
        record.progress_at = self.clock()
        if terminal:
            self._terminal(record, "completed")
        return message.model_copy(deep=True)

    @staticmethod
    def _authentication(record, role):
        if role not in ROLES[:2]:
            reject(403, "ROLE_FORBIDDEN")
        if record.view.scenario != "authenticated":
            reject(409, "AUTHENTICATION_NOT_ENABLED")
        return record.view.authentication

    def authentication(self, record, role):
        state = self._authentication(record, role)
        return state.model_copy(deep=True)

    def publish_trusted_key(self, record, role, request):
        state = self._authentication(record, role)
        existing = next((key for key in state.trusted_keys if key.owner == role), None)
        proposed = request.model_dump()
        if existing is not None:
            if existing.model_dump(include=set(proposed)) != proposed:
                reject(409, "TRUSTED_KEY_CONFLICT")
            return existing.model_copy(deep=True)
        self._protocol(record)
        if record.view.status != "running":
            reject(409, "INVALID_SESSION_STATE")
        if not 255 < request.modulus <= 2**32 - 1:
            reject(422, "INVALID_RSA_KEY")
        if not 1 < request.public_exponent < request.modulus:
            reject(422, "INVALID_RSA_KEY")
        if len(state.trusted_keys) >= 2:
            reject(409, "TRUSTED_KEY_LIMIT_REACHED")
        self._reserve_events(record, 1)
        key = TrustedKey(
            **proposed,
            session_id=record.view.session_id,
            backend_epoch=self.epoch,
            owner=role,
        )
        state.trusted_keys.append(key)
        self._event(record, "trusted_key_published", sender=role)
        record.progress_at = self.clock()
        return key.model_copy(deep=True)

    def publish_signature(self, record, role, request):
        state = self._authentication(record, role)
        existing = next((item for item in state.signatures if item.signer == role), None)
        proposed = request.model_dump()
        if existing is not None:
            if existing.model_dump(include=set(proposed)) != proposed:
                reject(409, "SIGNATURE_CONFLICT")
            return existing.model_copy(deep=True)
        self._protocol(record)
        view = record.view
        if view.status != "running":
            reject(409, "INVALID_SESSION_STATE")
        if len(state.trusted_keys) != 2:
            reject(409, "TRUSTED_KEYS_REQUIRED")
        if len(view.messages) != 2 or any(message.status == "intercepted" for message in view.messages):
            reject(409, "PUBLIC_VALUES_REQUIRED")
        key = next(item for item in state.trusted_keys if item.owner == role)
        if request.signature >= key.modulus:
            reject(422, "INVALID_SIGNATURE")
        if len(state.signatures) >= 2:
            reject(409, "SIGNATURE_LIMIT_REACHED")
        self._reserve_events(record, 1)
        signature = Signature(
            **proposed,
            session_id=view.session_id,
            backend_epoch=self.epoch,
            signer=role,
        )
        state.signatures.append(signature)
        self._event(record, "signature_published", sender=role)
        record.progress_at = self.clock()
        return signature.model_copy(deep=True)

    def verify_signature(self, record, role, request):
        state = self._authentication(record, role)
        peer = "bob" if role == "alice" else "alice"
        if request.signer != peer:
            reject(403, "ROLE_FORBIDDEN")
        existing = next(
            (item for item in state.verifications if item.verifier == role), None
        )
        proposed = request.model_dump()
        if existing is not None:
            comparable = existing.model_dump(include=set(proposed))
            if comparable != proposed:
                reject(409, "VERIFICATION_CONFLICT")
            return existing.model_copy(deep=True)
        self._protocol(record)
        if record.view.status != "running":
            reject(409, "INVALID_SESSION_STATE")
        signature = next(
            (item for item in state.signatures if item.signer == request.signer), None
        )
        if signature is None:
            reject(409, "SIGNATURE_REQUIRED")
        if request.verified and request.transcript_hash != signature.transcript_hash:
            reject(422, "TRANSCRIPT_MISMATCH")
        terminal = not request.verified or (
            len(state.verifications) == 1
            and state.verifications[0].verified
            and len(record.view.messages) == 2
            and all(message.status == "processed" for message in record.view.messages)
        )
        self._reserve_events(record, 2 if terminal else 1)
        verification = Verification(
            **proposed,
            session_id=record.view.session_id,
            backend_epoch=self.epoch,
            verifier=role,
            published_transcript_hash=signature.transcript_hash,
        )
        state.verifications.append(verification)
        self._event(
            record,
            "signature_verified" if request.verified else "signature_rejected",
            sender=role,
            recipient=request.signer,
            verified=request.verified,
        )
        record.progress_at = self.clock()
        if request.verified:
            setattr(record.view.participants, role, "verified")
            if terminal:
                self._terminal(record, "completed")
        else:
            self._terminal(record, "failed", "SIGNATURE_VERIFICATION_FAILED")
        return verification.model_copy(deep=True)

    def report(self, record, role, report):
        self._protocol(record)
        view = record.view
        if not view.diagnostics_enabled:
            reject(403, "DIAGNOSTICS_DISABLED")
        if (record.terminal_time is not None
                and self.clock() >= record.terminal_time + self.settings.diagnostics_retry_seconds):
            reject(409, "INVALID_SESSION_STATE")
        if role == "mallory":
            self._mallory(record, role)
            if len(view.interceptions) != 2 or any(i.delivered_value is None for i in view.interceptions):
                reject(409, "FORWARD_REQUIRED")
            proposed = report.model_dump()
            target = record.mallory_diagnostics
        else:
            accepted = getattr(view.participants, role)
            if view.scenario == "authenticated" and view.status != "completed":
                reject(409, "VERIFICATION_REQUIRED")
            if accepted not in {"received", "verified"}:
                reject(409, "ACK_REQUIRED")
            proposed = {role: report.shared_secret}
            target = record.diagnostics
        if any(not 1 <= value < view.prime for value in proposed.values()):
            reject(422, "INVALID_DIAGNOSTIC")
        if any(getattr(target, key) not in (None, value) for key, value in proposed.items()):
            reject(409, "DIAGNOSTIC_CONFLICT")
        if any(getattr(target, key) != value for key, value in proposed.items()):
            for key, value in proposed.items():
                setattr(target, key, value)
            view.revision += 1

    def fail(self, record, code):
        if record.view.status == "failed" and record.view.failure_code == code:
            return record.view.model_copy(deep=True)
        if record.view.status != "running":
            reject(409, "INVALID_SESSION_STATE")
        self._reserve_events(record, 1)
        self._terminal(record, "failed", code)
        return record.view.model_copy(deep=True)
