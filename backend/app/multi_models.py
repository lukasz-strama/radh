"""Modele publicznego API v2 i transportu internal zgodne z kontraktem #73."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from .models import Uint32
from .session_models import (
    Interception, MalloryDiagnostics, Message, ProtocolModel, SessionDiagnostics,
)

HexId = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{32}$")]
MessageId = Literal["alice-public", "bob-public"]
Status = Literal["created", "running", "completed", "cancelled", "expired", "failed"]
Participant = Literal["waiting", "published", "received"]
Mode = Literal["normal", "mitm"]


class Create(ProtocolModel):
    # Walidacja matematyczna następuje po limitach i sprawdzeniu idempotencji.
    prime: Uint32
    generator: Uint32
    mode: Mode = "normal"
    diagnostics_enabled: Annotated[bool, Field(strict=True)] = False


class Participants(ProtocolModel):
    alice: Participant = "waiting"
    bob: Participant = "waiting"


class SessionView(Create):
    session_id: HexId
    backend_epoch: HexId
    status: Status = "created"
    failure_code: str | None = None
    created_at: datetime
    expires_at: datetime
    terminal_at: datetime | None = None
    revision: int = 0
    participants: Participants = Field(default_factory=Participants)
    messages: list[Message] = Field(default_factory=list)
    interceptions: list[Interception] = Field(default_factory=list)


class Created(ProtocolModel):
    session: SessionView
    session_token: str = Field(repr=False)


class Event(ProtocolModel):
    sequence: int
    type: Literal[
        "session_created", "session_started", "public_value", "message_processed",
        "session_completed", "session_cancelled", "message_intercepted",
        "message_forwarded", "session_failed", "session_expired",
    ]
    created_at: datetime
    sender: Literal["alice", "bob", "mallory"] | None = None
    recipient: Literal["alice", "bob"] | None = None
    public_value: Uint32 | None = None
    message_id: str | None = None
    status: Literal["intercepted", "queued", "processed"] = "processed"


class Events(ProtocolModel):
    session_id: HexId
    backend_epoch: HexId
    events: list[Event]
    next_after: int


class HeartbeatRequest(ProtocolModel):
    instance_id: HexId


class Heartbeat(HeartbeatRequest):
    backend_epoch: HexId
    lease_seconds: int


class NodePresence(ProtocolModel):
    online: bool


class Presence(ProtocolModel):
    alice: NodePresence
    bob: NodePresence
    mallory: NodePresence


class Descriptor(Create):
    session_id: HexId
    backend_epoch: HexId
    status: Status
    revision: int
    expires_at: datetime
    remaining_ttl_seconds: int
    participant_status: Participant | None
    diagnostics_received: bool


class Discovery(ProtocolModel):
    backend_epoch: HexId
    sessions: list[Descriptor]
    retry_after_ms: int = 1000


class Publish(ProtocolModel):
    message_id: MessageId
    type: Literal["public_value"]
    public_value: Uint32


class Inbox(ProtocolModel):
    session_id: HexId
    backend_epoch: HexId
    revision: int
    messages: list[Message]


class Interceptions(ProtocolModel):
    session_id: HexId
    backend_epoch: HexId
    revision: int
    interceptions: list[Interception]


class Report(ProtocolModel):
    shared_secret: Uint32


class MalloryReport(ProtocolModel):
    shared_with_alice: Uint32
    shared_with_bob: Uint32


class Failure(ProtocolModel):
    code: Literal["NODE_CAPACITY", "CRYPTO_CORE_ERROR", "LOCAL_STATE_LOST"]
