"""Ulotna dostępność procesów, niezależna od sesji i jej zdarzeń."""

from collections.abc import Callable
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from .models import ErrorResponse
from .session_models import Role

HEARTBEAT_TTL = 5.0


class NodePresence(BaseModel):
    online: bool
    last_seen: datetime | None


class PresenceStore:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._seen: dict[Role, tuple[float, datetime]] = {}

    def heartbeat(self, role: Role) -> None:
        with self._lock:
            self._seen[role] = (self._clock(), datetime.now(timezone.utc))

    def snapshot(self) -> dict[Role, NodePresence]:
        with self._lock:
            now = self._clock()
            return {
                role: NodePresence(
                    online=role in self._seen and now - self._seen[role][0] < HEARTBEAT_TTL,
                    last_seen=self._seen[role][1] if role in self._seen else None,
                ) for role in ("alice", "bob")
            }


def get_presence(request: Request) -> PresenceStore:
    return request.app.state.dh_presence


Presence = Annotated[PresenceStore, Depends(get_presence)]
router = APIRouter(prefix="/api/v1/dh/nodes", tags=["Dostępność węzłów DH"],
                   responses={422: {"model": ErrorResponse}})


@router.post("/{role}/heartbeat", status_code=204, summary="Zgłoś aktywność procesu węzła")
def heartbeat(role: Role, presence: Presence) -> Response:
    presence.heartbeat(role)
    return Response(status_code=204)


@router.get("", response_model=dict[Role, NodePresence], summary="Odczytaj dostępność węzłów (TTL 5 s)")
def get_nodes(presence: Presence):
    return presence.snapshot()
