"""Wspólny, publiczny kontrakt sesji dla API i klienta HTTP."""

from math import isqrt
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Uint32

Role = Literal["alice", "bob"]
Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSession(ProtocolModel):
    session_id: Identifier = Field(default_factory=lambda: uuid4().hex)
    prime: Uint32
    generator: Uint32
    mode: Literal["normal", "mitm"] = "normal"

    @model_validator(mode="after")
    def validate_parameters(self):
        # Walidacja publicznych parametrów; koordynator nie wykonuje wymiany DH.
        p = self.prime
        if p < 2 or (p != 2 and (p % 2 == 0 or any(
            p % d == 0 for d in range(3, isqrt(p) + 1, 2)
        ))):
            raise ValueError("prime musi być liczbą pierwszą")
        if not 2 <= self.generator < p:
            raise ValueError("generator musi należeć do zakresu 2..prime-1")
        return self


class PublicMessage(ProtocolModel):
    message_id: Identifier
    sender: Role
    recipient: Role
    type: Literal["public_value"]
    public_value: Uint32


class Message(PublicMessage):
    status: Literal["queued", "processed"] = "queued"


class Acknowledge(ProtocolModel):
    recipient: Role


class Event(ProtocolModel):
    sequence: int
    type: Literal["session_created", "session_started", "public_value", "message_processed", "session_completed", "session_cancelled"]
    sender: Role | None = None
    recipient: Role | None = None
    public_value: Uint32 | None = None
    message_id: str | None = None
    status: Literal["queued", "processed"] = "processed"


class Session(CreateSession):
    status: Literal["created", "running", "completed", "cancelled"] = "created"
    participants: dict[Role, Literal["waiting", "published", "received"]] = Field(
        default_factory=lambda: {"alice": "waiting", "bob": "waiting"}
    )
    messages: list[Message] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
