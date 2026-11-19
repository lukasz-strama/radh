"""Ścisłe modele odpowiedzi internal v2; niezależne od koordynatora v1."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

HexId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$", strict=True)]
UInt = Annotated[int, Field(strict=True, ge=1, le=2**32-1)]
Revision = Annotated[int, Field(strict=True, ge=0)]
Role = Literal['alice', 'bob', 'mallory']


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Descriptor(Model):
    session_id: HexId
    backend_epoch: HexId
    prime: UInt
    generator: UInt
    mode: Literal['normal', 'mitm']
    diagnostics_enabled: bool
    status: Literal['created', 'running', 'completed', 'cancelled', 'expired', 'failed']
    revision: Revision
    expires_at: str
    remaining_ttl_seconds: Annotated[int, Field(strict=True, ge=0, le=600)]
    participant_status: Literal['waiting', 'published', 'received'] | None
    diagnostics_received: bool

    @model_validator(mode='after')
    def parameters(self):
        if not 2 <= self.generator < self.prime:
            raise ValueError('Niepoprawne parametry.')
        date = datetime.fromisoformat(self.expires_at.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError('Wymagana strefa czasowa.')
        return self


class Discovery(Model):
    backend_epoch: HexId
    sessions: Annotated[list[Descriptor], Field(max_length=128)]
    retry_after_ms: Annotated[int, Field(strict=True, ge=1000, le=1000)]

    @model_validator(mode='after')
    def unique(self):
        if (len({d.session_id for d in self.sessions}) != len(self.sessions)
                or any(d.backend_epoch != self.backend_epoch for d in self.sessions)):
            raise ValueError('Niespójny snapshot.')
        return self


class Heartbeat(Model):
    backend_epoch: HexId
    instance_id: HexId
    lease_seconds: Annotated[int, Field(strict=True, ge=10, le=10)]


class Message(Model):
    message_id: Literal['alice-public', 'bob-public']
    sender: Literal['alice', 'bob']
    recipient: Literal['alice', 'bob']
    type: Literal['public_value']
    public_value: UInt
    status: Literal['intercepted', 'queued', 'processed']


class Inbox(Model):
    session_id: HexId
    backend_epoch: HexId
    revision: Revision
    messages: Annotated[list[Message], Field(max_length=1)]


class Interception(Model):
    message_id: Literal['alice-public', 'bob-public']
    original_sender: Literal['alice', 'bob']
    recipient: Literal['alice', 'bob']
    original_value: UInt
    delivered_value: UInt | None
    intercepted_by: Literal['mallory']
    actual_sender: Literal['mallory'] | None
    status: Literal['pending', 'forwarded', 'processed']

    @model_validator(mode='after')
    def routing(self):
        if (self.original_sender == self.recipient
                or self.message_id != self.original_sender + '-public'
                or (self.status == 'pending') != (self.delivered_value is None)
                or (self.status == 'pending') != (self.actual_sender is None)):
            raise ValueError('Niepoprawne przechwycenie.')
        return self


class Interceptions(Model):
    session_id: HexId
    backend_epoch: HexId
    revision: Revision
    interceptions: Annotated[list[Interception], Field(max_length=2)]

    @model_validator(mode='after')
    def unique(self):
        if len({i.message_id for i in self.interceptions}) != len(self.interceptions):
            raise ValueError('Powtórzone przechwycenie.')
        return self


class Participants(Model):
    alice: Literal['waiting', 'published', 'received']
    bob: Literal['waiting', 'published', 'received']


class SessionView(Model):
    session_id: HexId
    backend_epoch: HexId
    prime: UInt
    generator: UInt
    mode: Literal['normal', 'mitm']
    diagnostics_enabled: bool
    status: Literal['created', 'running', 'completed', 'cancelled', 'expired', 'failed']
    failure_code: str | None
    created_at: str
    expires_at: str
    terminal_at: str | None
    revision: Revision
    participants: Participants
    messages: Annotated[list[Message], Field(max_length=2)]
    interceptions: Annotated[list[Interception], Field(max_length=2)]
