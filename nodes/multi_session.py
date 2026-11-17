"""Rejestr agentów i ograniczony harmonogram internal v2 (#68)."""
from __future__ import annotations

import random
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from pydantic import ValidationError

from backend.app.crypto_core import CryptoCoreCallError, CryptoCoreInputError
from .internal_http import EpochChanged, InternalClient, InternalError
from .internal_models import Descriptor, Discovery, Heartbeat, Inbox, Interception, Interceptions, Message, SessionView
from .mallory import MalloryNode
from .node import DhNode, NodeError


class StaleEntry(Exception):
    """Wynik nie ma już właściciela w aktualnym rejestrze."""


@dataclass(eq=False, repr=False)
class Entry:
    descriptor: Descriptor
    deadline: float
    node: DhNode | MalloryNode | None = None
    published: bool = False
    acked: bool = False
    forwarded: set[str] = field(default_factory=set)
    diagnostics_sent: bool = False
    diagnostics_disabled: bool = False
    completed_at: float | None = None
    failure: str | None = None
    disabled: bool = False
    busy: bool = False
    next_attempt: float = 0
    first_error: float | None = None
    attempts: int = 0


class MultiSessionTransport:
    def __init__(self, client: InternalClient, *, max_agents: int = 128,
                 allow_diagnostics: bool = False,
                 factory: Callable[[], DhNode | MalloryNode] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        if type(max_agents) is not int or not 1 <= max_agents <= 128:
            raise ValueError('MAX_NODE_AGENTS musi należeć do 1..128.')
        self.client, self.role = client, client.role
        self.max_agents, self.allow_diagnostics = max_agents, allow_diagnostics
        self.factory = factory or (MalloryNode if self.role == 'mallory'
                                   else lambda: DhNode(self.role))
        self.clock = clock
        self.entries: OrderedDict[tuple[str, str], Entry] = OrderedDict()
        self.epoch: str | None = None
        self.registered = False
        self.generation = 0
        self.lease_deadline = 0.
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.failed = False
        self.started = clock()

    def invalidate(self) -> None:
        with self.lock:
            self.entries.clear()
            self.registered = False
            self.generation += 1

    def heartbeat(self) -> None:
        # Heartbeat jako jedyny może przyjąć nowy epoch. Stare odpowiedzi innych
        # operacji wyłącznie unieważniają rejestr i wymuszają ponowną rejestrację.
        with self.lock:
            previous, generation = self.epoch, self.generation
        raw, epoch = self.client.request('POST', f'/internal/v1/dh/nodes/{self.role}/heartbeat',
                                         None, {'instance_id': self.client.instance_id})
        response = Heartbeat.model_validate(raw)
        if response.instance_id != self.client.instance_id or response.backend_epoch != epoch:
            raise InternalError(code='INVALID_RESPONSE')
        with self.lock:
            if self.epoch != previous or self.generation != generation:
                return
            if epoch != self.epoch:
                self.entries.clear()
                self.generation += 1
            self.epoch, self.registered = epoch, True
            self.lease_deadline = self.clock() + response.lease_seconds

    def current(self, entry: Entry) -> None:
        with self.lock:
            key = (entry.descriptor.backend_epoch, entry.descriptor.session_id)
            if (self.stop.is_set() or not self.registered or self.clock() >= self.lease_deadline
                    or self.entries.get(key) is not entry or entry.disabled
                    or self.clock() >= entry.deadline
                    or entry.descriptor.status not in ('running', 'completed')):
                raise StaleEntry()

    def _call(self, entry: Entry, method: str, suffix: str, body: dict | None = None):
        self.current(entry)
        d = entry.descriptor
        raw, epoch = self.client.request(method, '/internal/v1/dh/sessions/' + d.session_id + suffix,
                                         d.backend_epoch, body)
        self.current(entry)
        if epoch != d.backend_epoch:
            raise EpochChanged()
        return raw

    def discover(self) -> None:
        with self.lock:
            if not self.registered:
                return
            epoch, generation = self.epoch, self.generation
        try:
            raw, received_epoch = self.client.request('GET', '/internal/v1/dh/sessions', epoch)
        except EpochChanged:
            with self.lock:
                if generation != self.generation:
                    return
            raise
        snapshot = Discovery.model_validate(raw)
        if snapshot.backend_epoch != epoch or received_epoch != epoch:
            raise EpochChanged()
        if any((self.role == 'mallory' and (d.mode != 'mitm' or d.participant_status is not None))
               or (self.role != 'mallory' and d.participant_status is None) for d in snapshot.sessions):
            raise InternalError(code='INVALID_RESPONSE')
        now = self.clock()
        with self.lock:
            if not self.registered or self.epoch != epoch or self.generation != generation:
                return
            keys = {(epoch, d.session_id) for d in snapshot.sessions}
            # Sprawdzenie całego snapshotu przed jego zastosowaniem.
            for d in snapshot.sessions:
                old = self.entries.get((epoch, d.session_id))
                if old and (d.prime != old.descriptor.prime or d.generator != old.descriptor.generator
                            or d.mode != old.descriptor.mode or d.revision < old.descriptor.revision
                            or (old.descriptor.status != 'running' and d.status == 'running')):
                    raise InternalError(code='INVALID_RESPONSE')
            for key in list(self.entries):
                if key not in keys:
                    del self.entries[key]
            for d in snapshot.sessions:
                key = (epoch, d.session_id)
                entry = self.entries.get(key)
                if d.status not in ('running', 'completed') or (d.status == 'running' and not d.remaining_ttl_seconds):
                    if entry:
                        entry.disabled, entry.node = True, None
                    continue
                if entry is None:
                    if d.status != 'running':
                        continue
                    # Metadane nieudanej sesji są ograniczone snapshotem (128),
                    # a rezerwacje agentów dodatkowo konfigurowalnym max_agents.
                    active = sum(not e.disabled and e.failure is None for e in self.entries.values())
                    entry = Entry(d, now + d.remaining_ttl_seconds)
                    if active >= self.max_agents:
                        entry.failure = 'NODE_CAPACITY'
                    self.entries[key] = entry
                entry.descriptor = d
                if d.status == 'running':
                    entry.deadline = min(entry.deadline, now + d.remaining_ttl_seconds)
                else:
                    if entry.completed_at is None:
                        entry.completed_at = now
                    entry.deadline = entry.completed_at + 30
                    if (not self.allow_diagnostics or not d.diagnostics_enabled
                            or d.diagnostics_received or entry.diagnostics_sent):
                        entry.disabled, entry.node = True, None
            self.cleanup()

    def cleanup(self) -> None:
        with self.lock:
            for entry in self.entries.values():
                if self.clock() >= entry.deadline:
                    entry.disabled, entry.node = True, None
            if self.registered and self.clock() >= self.lease_deadline:
                self.entries.clear()
                self.registered = False
                self.failed = True
                self.stop.set()

    def _envelope(self, entry: Entry, envelope) -> None:
        d = entry.descriptor
        if (envelope.session_id != d.session_id or envelope.backend_epoch != d.backend_epoch
                or envelope.revision < d.revision):
            raise InternalError(code='INVALID_RESPONSE')

    def _message(self, entry: Entry, message: Message, *, own: bool = False) -> None:
        sender = self.role if own else ('bob' if self.role == 'alice' else 'alice')
        recipient = ('bob' if self.role == 'alice' else 'alice') if own else self.role
        if (message.message_id != sender + '-public' or message.sender != sender
                or message.recipient != recipient or not 1 <= message.public_value < entry.descriptor.prime
                or (not own and message.status not in ('queued', 'processed'))):
            raise InternalError(code='INVALID_RESPONSE')

    def process(self, entry: Entry) -> None:
        self.current(entry)
        d = entry.descriptor
        if entry.failure:
            result = SessionView.model_validate(self._call(entry, 'POST', '/fail', {'code': entry.failure}))
            self._envelope(entry, result)
            if result.status != 'failed' or result.failure_code != entry.failure:
                raise InternalError(code='INVALID_RESPONSE')
            entry.disabled, entry.node = True, None
            return
        with self.lock:
            self.current(entry)
            node = entry.node
        if node is None:
            if d.status != 'running':
                entry.disabled = True
                return
            node = self.factory()
            node.start_session(d.session_id, d.prime, d.generator)
            with self.lock:
                self.current(entry)
                entry.node = node
        if d.status in ('running', 'completed'):
            if self.role == 'mallory':
                envelope = Interceptions.model_validate(self._call(entry, 'GET', '/interceptions'))
                self._envelope(entry, envelope)
                for item in envelope.interceptions:
                    if (not 1 <= item.original_value < d.prime
                            or (item.delivered_value is not None and not 1 <= item.delivered_value < d.prime)):
                        raise InternalError(code='INVALID_RESPONSE')
                for item in envelope.interceptions:
                    expected = (node.state.substitute_to_alice if item.recipient == 'alice'
                                else node.state.substitute_to_bob)
                    if item.delivered_value is not None and item.delivered_value != expected:
                        entry.failure = 'LOCAL_STATE_LOST'
                        return
                for item in envelope.interceptions:
                    self.current(entry)
                    node.receive_public(d.session_id, item.original_sender, item.original_value)
                    self.current(entry)
                    value = (node.state.substitute_to_alice if item.recipient == 'alice'
                             else node.state.substitute_to_bob)
                    if item.delivered_value is not None and item.delivered_value != value:
                        entry.failure = 'LOCAL_STATE_LOST'
                        return
                    if item.message_id not in entry.forwarded:
                        result = Interception.model_validate(self._call(
                            entry, 'POST', f'/interceptions/{item.message_id}/forward', {'public_value': value}))
                        if (result.model_dump(exclude={'delivered_value', 'actual_sender', 'status'})
                                != item.model_dump(exclude={'delivered_value', 'actual_sender', 'status'})
                                or result.delivered_value != value or result.status == 'pending'):
                            raise InternalError(code='INVALID_RESPONSE')
                        entry.forwarded.add(item.message_id)
            elif d.status == 'running':
                if not entry.published:
                    result = Message.model_validate(self._call(entry, 'POST', '/messages', {
                        'message_id': self.role + '-public', 'type': 'public_value',
                        'public_value': node.state.public_value}))
                    self._message(entry, result, own=True)
                    # W MITM odpowiedź może już zawierać wartość podmienioną.
                    if d.mode == 'normal' and result.public_value != node.state.public_value:
                        raise InternalError(code='INVALID_RESPONSE')
                    entry.published = True
                if not entry.acked:
                    inbox = Inbox.model_validate(self._call(entry, 'GET', '/messages'))
                    self._envelope(entry, inbox)
                    for message in inbox.messages:
                        self._message(entry, message)
                        if message.status != 'queued':
                            raise InternalError(code='INVALID_RESPONSE')
                    for message in inbox.messages:
                        node.receive_public(d.session_id, message.public_value)
                        self.current(entry)
                        result = Message.model_validate(self._call(
                            entry, 'POST', f'/messages/{message.message_id}/ack'))
                        self._message(entry, result)
                        if result.status != 'processed' or result.public_value != message.public_value:
                            raise InternalError(code='INVALID_RESPONSE')
                        entry.acked = True
                # Utrata odpowiedzi ostatniego ACK: kolejka jest już pusta.
                if d.participant_status == 'received' and node.state.phase == 'complete':
                    entry.acked = True
        if self.role != 'mallory' and d.participant_status == 'received' and node.state.phase == 'complete':
            entry.acked = True
        ready = (len(entry.forwarded) == 2 if self.role == 'mallory' else entry.acked)
        if (self.allow_diagnostics and d.diagnostics_enabled and not entry.diagnostics_sent
                and not entry.diagnostics_disabled and ready and node.state.phase == 'complete'):
            report = node.diagnostics()
            keys = ('shared_with_alice', 'shared_with_bob') if self.role == 'mallory' else ('shared_secret',)
            body = {key: report[key] for key in keys}
            suffix = '/diagnostics/mallory' if self.role == 'mallory' else '/diagnostics'
            if self._call(entry, 'POST', suffix, body) is not None:
                raise InternalError(code='INVALID_RESPONSE')
            entry.diagnostics_sent = True

    def handle_error(self, error: Exception, entry: Entry | None = None) -> None:
        if isinstance(error, EpochChanged):
            with self.lock:
                if entry is None or self.entries.get((entry.descriptor.backend_epoch, entry.descriptor.session_id)) is entry:
                    self.invalidate()
            return
        if isinstance(error, InternalError) and (error.status in (401, 403)):
            if entry is not None and error.code == 'DIAGNOSTICS_DISABLED':
                entry.diagnostics_disabled = True
                return
            if entry is not None and error.code == 'ROLE_NOT_ASSIGNED':
                entry.disabled, entry.node = True, None
                return
            self.failed = True
            self.stop.set()
            self.invalidate()
            return
        if isinstance(error, InternalError) and error.code == 'NODE_INSTANCE_MISMATCH':
            self.invalidate()
            return
        if entry is None:
            if isinstance(error, InternalError) and error.code in (
                    'NODE_INSTANCE_CONFLICT', 'NODE_INSTANCE_MISMATCH'):
                self.failed = True
                self.stop.set()
                self.invalidate()
            elif not self.registered and self.clock() - self.started >= 30:
                self.failed = True
                self.stop.set()
            return
        if isinstance(error, StaleEntry):
            return
        if isinstance(error, (NodeError, CryptoCoreCallError, CryptoCoreInputError)):
            entry.failure = 'CRYPTO_CORE_ERROR'
            return
        if isinstance(error, InternalError) and (error.status in (404, 410, 422)
                or (error.status == 409 and error.code not in ('ACK_REQUIRED', 'FORWARD_REQUIRED'))):
            entry.disabled, entry.node = True, None
            return
        now = self.clock()
        entry.first_error = entry.first_error if entry.first_error is not None else now
        if now - entry.first_error >= 30:
            entry.failure = 'LOCAL_STATE_LOST'
            if entry.attempts > 10:
                entry.disabled, entry.node = True, None
        delay = min(8, .5 * 2 ** min(entry.attempts, 4)) * random.uniform(.8, 1.2)
        if isinstance(error, InternalError):
            delay = max(delay, error.retry_after)
        entry.next_attempt = now + min(30, delay)
        entry.attempts += 1

    def work(self, entry: Entry) -> None:
        try:
            self.process(entry)
        except (InternalError, ValidationError, StaleEntry, NodeError,
                CryptoCoreCallError, CryptoCoreInputError) as error:
            self.handle_error(error, entry)
        else:
            entry.attempts, entry.first_error = 0, None
            entry.next_attempt = self.clock() + 2
        finally:
            with self.lock:
                entry.busy = False

    def heartbeat_loop(self) -> None:
        while not self.stop.is_set():
            started = self.clock()
            delay = 0.
            try:
                self.heartbeat()
            except (InternalError, ValidationError) as error:
                self.handle_error(error)
                if isinstance(error, InternalError):
                    delay = max(delay, min(30, error.retry_after))
            self.stop.wait(max(delay, 2 - (self.clock() - started)))

    def run(self) -> None:
        heartbeat = threading.Thread(target=self.heartbeat_loop, name='radh-heartbeat')
        heartbeat.start()
        futures = set()
        next_discovery = 0.
        try:
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix='radh-session') as pool:
                while not self.stop.is_set():
                    self.cleanup()
                    if self.clock() >= next_discovery:
                        delay = random.uniform(.8, 1.2)
                        try:
                            self.discover()
                        except (InternalError, ValidationError) as error:
                            self.handle_error(error)
                            if isinstance(error, InternalError):
                                delay = max(delay, min(30, error.retry_after))
                        next_discovery = self.clock() + delay
                    for future in tuple(futures):
                        if future.done():
                            future.result()
                            futures.remove(future)
                    with self.lock:
                        for key, entry in list(self.entries.items()):
                            if len(futures) >= 2:
                                break
                            if not entry.busy and not entry.disabled and self.clock() >= entry.next_attempt:
                                entry.busy = True
                                self.entries.move_to_end(key)
                                futures.add(pool.submit(self.work, entry))
                    self.stop.wait(.02)
        finally:
            self.stop.set()
            heartbeat.join()
            self.invalidate()
