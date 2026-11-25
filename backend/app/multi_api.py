"""Publiczny kontrakt właściciela i oddzielne uwierzytelnione operacje węzłów."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, Security
from fastapi.security import HTTPBearer
from pydantic import ValidationError

from .api import get_crypto_core
from .coordinator_http import Runtime, bearer, runtime
from .coordinator_limits import reject
from .models import ErrorResponse
from .multi_models import (
    AuthenticationState, Create, Created, Discovery, Events, Failure, Heartbeat,
    HeartbeatRequest, HexId, Inbox, Interceptions, MalloryReport, MessageId,
    Presence, Publish, Report, SessionView, Signature, SignatureRequest, TrustedKey,
    TrustedKeyRequest, Verification, VerificationRequest,
)
from .session_models import (
    MalloryDiagnostics, Message, Interception, Replacement, SessionDiagnostics, NodeRole,
)

ERRORS = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "Niepoprawne żądanie", 401: "Wymagane uwierzytelnienie",
        403: "Brak uprawnień", 404: "Nie znaleziono zasobu",
        405: "Niedozwolona metoda", 409: "Konflikt stanu",
        410: "Sesja została usunięta", 413: "Przekroczony rozmiar żądania",
        415: "Wymagany JSON", 422: "Niepoprawne dane wejściowe",
        429: "Przekroczony limit", 500: "Błąd serwera", 503: "Usługa niedostępna",
    }.items()
}
public = APIRouter(prefix="/api/v2/dh", tags=["Sesje DH v2"], responses=ERRORS)
internal = APIRouter(prefix="/internal/v1/dh", tags=["Wewnętrzny transport DH"], responses=ERRORS)
health = APIRouter(prefix="/internal/health", tags=["Stan backendu"], responses=ERRORS)
RT = Annotated[Runtime, Depends(runtime)]
owner_scheme = HTTPBearer(auto_error=False, scheme_name="SessionOwner")
node_scheme = HTTPBearer(auto_error=False, scheme_name="NodeRole")


def owner(request: Request, _security=Security(owner_scheme)):
    return bearer(request.headers.get("authorization"))


Owner = Annotated[str, Depends(owner)]


def node_role(request: Request, rt: RT, _security=Security(node_scheme)):
    # Ponowna kontrola umożliwia bezpieczne użycie zależności także poza middleware.
    return rt.authenticate_role(bearer(request.headers.get("authorization")))


Node = Annotated[NodeRole, Depends(node_role)]


def assigned(
    session_id: HexId, request: Request, rt: RT, role: Node,
    epoch: Annotated[str | None, Header(alias="X-Backend-Epoch")] = None,
    instance: Annotated[str | None, Header(alias="X-Node-Instance")] = None,
):
    epoch = epoch or request.headers.get("x-backend-epoch")
    instance = instance or request.headers.get("x-node-instance")
    if epoch is None or instance is None:
        reject(400, "BAD_REQUEST", "Wymagane nagłówki epoch i instancji.")
    grant = dict(sid=session_id, role=role, epoch=epoch, instance=instance)
    with rt.coordinator.access(**grant):
        pass
    return grant


Assigned = Annotated[dict, Depends(assigned)]


def invoke(rt, grant, method, *args):
    # Całe przejęcie i zwolnienie RLock odbywa się w wątku operacji.
    with rt.coordinator.access(**grant) as record:
        return getattr(rt.coordinator, method)(record, *args)


@public.post("/sessions", status_code=201, response_model=Created,
             summary="Utwórz sesję DH albo uwierzytelnioną RSA + DH")
def create_session(
    body: Create, request: Request, rt: RT,
    key: Annotated[str | None, Header(alias="Idempotency-Key",
        description="Wymagane poświadczenie 32 losowych bajtów base64url.")] = None,
    epoch: Annotated[str | None, Header(alias="X-Backend-Epoch",
        description="Wymagany epoch z GET /api/v2/dh/nodes.")] = None,
):
    key = key or request.headers.get("idempotency-key")
    epoch = epoch or request.headers.get("x-backend-epoch")
    if key is None or epoch is None:
        reject(400, "BAD_REQUEST", "Wymagane Idempotency-Key i X-Backend-Epoch.")
    try:
        with rt.crypto.slot():
            return rt.coordinator.create(body, key, epoch, request.state.client_ip)
    except ValidationError as error:
        code = error.errors()[0]["type"]
        if code not in {"INVALID_PRIME", "INVALID_GENERATOR"}:
            code = "INVALID_REQUEST"
        reject(422, code, "Niepoprawne parametry sesji DH.")


@public.get("/nodes", response_model=Presence, summary="Dostępność procesów DH")
def nodes(rt: RT):
    return rt.coordinator.presence()


@public.get("/sessions/{session_id}", response_model=SessionView)
def session(session_id: HexId, token: Owner, rt: RT):
    return rt.coordinator.get(session_id, token)


@public.post("/sessions/{session_id}/start", response_model=SessionView)
def start(session_id: HexId, token: Owner, rt: RT):
    return rt.coordinator.transition(session_id, token, "start")


@public.post("/sessions/{session_id}/cancel", response_model=SessionView)
def cancel(session_id: HexId, token: Owner, rt: RT):
    return rt.coordinator.transition(session_id, token, "cancel")


@public.delete("/sessions/{session_id}", status_code=204)
def delete(session_id: HexId, token: Owner, rt: RT):
    rt.coordinator.delete(session_id, token)
    return Response(status_code=204)


@public.get("/sessions/{session_id}/events", response_model=Events)
def events(session_id: HexId, token: Owner, rt: RT,
           after: Annotated[int, Query(ge=0)] = 0,
           limit: Annotated[int, Query(ge=1, le=32)] = 32):
    return rt.coordinator.events(session_id, token, after, limit)


@public.get("/sessions/{session_id}/diagnostics", response_model=SessionDiagnostics)
def diagnostics(session_id: HexId, token: Owner, rt: RT):
    return rt.coordinator.diagnostics(session_id, token)


@public.get("/sessions/{session_id}/diagnostics/mallory", response_model=MalloryDiagnostics)
def mallory_diagnostics(session_id: HexId, token: Owner, rt: RT):
    return rt.coordinator.diagnostics(session_id, token, mallory=True)


@internal.post("/nodes/{role}/heartbeat", response_model=Heartbeat)
def heartbeat(role: NodeRole, body: HeartbeatRequest, authenticated_role: Node, rt: RT):
    if role != authenticated_role:
        reject(403, "ROLE_FORBIDDEN")
    return rt.coordinator.heartbeat(role, body.instance_id)


@internal.get("/sessions", response_model=Discovery)
def discovery(
    request: Request, role: Node, rt: RT,
    epoch: Annotated[str | None, Header(alias="X-Backend-Epoch")] = None,
    instance: Annotated[str | None, Header(alias="X-Node-Instance")] = None,
):
    epoch = epoch or request.headers.get("x-backend-epoch")
    instance = instance or request.headers.get("x-node-instance")
    if epoch is None or instance is None:
        reject(400, "BAD_REQUEST", "Wymagane nagłówki epoch i instancji.")
    return rt.coordinator.discover(role, epoch, instance)


@internal.post("/sessions/{session_id}/messages", response_model=Message)
def publish(body: Publish, record: Assigned, role: Node, rt: RT):
    return invoke(rt, record, "publish", role, body)


@internal.get("/sessions/{session_id}/messages", response_model=Inbox)
def inbox(record: Assigned, role: Node, rt: RT):
    return invoke(rt, record, "inbox", role)


@internal.post("/sessions/{session_id}/messages/{message_id}/ack", response_model=Message)
def acknowledge(message_id: MessageId, record: Assigned, role: Node, rt: RT):
    return invoke(rt, record, "acknowledge", role, message_id)


@internal.get(
    "/sessions/{session_id}/authentication",
    response_model=AuthenticationState,
    summary="Pobierz zaufane klucze, podpisy i wyniki weryfikacji sesji",
)
def authentication(record: Assigned, role: Node, rt: RT):
    return invoke(rt, record, "authentication", role)


@internal.post(
    "/sessions/{session_id}/trusted-keys",
    response_model=TrustedKey,
    summary="Opublikuj zaufany publiczny klucz RSA własnej roli",
)
def publish_trusted_key(body: TrustedKeyRequest, record: Assigned, role: Node, rt: RT):
    return invoke(rt, record, "publish_trusted_key", role, body)


@internal.post(
    "/sessions/{session_id}/signatures",
    response_model=Signature,
    summary="Opublikuj podpis lokalnego transkryptu DH",
)
def publish_signature(body: SignatureRequest, record: Assigned, role: Node, rt: RT):
    return invoke(rt, record, "publish_signature", role, body)


@internal.post(
    "/sessions/{session_id}/verifications",
    response_model=Verification,
    summary="Zgłoś wynik weryfikacji podpisu partnera",
)
def verify_signature(body: VerificationRequest, record: Assigned, role: Node, rt: RT):
    return invoke(rt, record, "verify_signature", role, body)


@internal.get("/sessions/{session_id}/interceptions", response_model=Interceptions)
def interceptions(record: Assigned, role: Node, rt: RT):
    return invoke(rt, record, "interceptions", role)


@internal.post("/sessions/{session_id}/interceptions/{message_id}/forward", response_model=Interception)
def forward(message_id: MessageId, body: Replacement, record: Assigned, role: Node, rt: RT):
    return invoke(rt, record, "forward", role, message_id, body.public_value)


@internal.post("/sessions/{session_id}/diagnostics", status_code=204)
def report(body: Report, record: Assigned, role: Node, rt: RT):
    if role == "mallory":
        reject(403, "ROLE_FORBIDDEN")
    invoke(rt, record, "report", role, body)
    return Response(status_code=204)


@internal.post("/sessions/{session_id}/diagnostics/mallory", status_code=204)
def mallory_report(body: MalloryReport, record: Assigned, role: Node, rt: RT):
    if role != "mallory":
        reject(403, "ROLE_FORBIDDEN")
    invoke(rt, record, "report", role, body)
    return Response(status_code=204)


@internal.post(
    "/sessions/{session_id}/fail",
    response_model=SessionView,
    response_model_exclude={"scenario", "authentication"},
)
def fail(body: Failure, record: Assigned, rt: RT):
    return invoke(rt, record, "fail", body.code)


@health.get("/live")
def live():
    return {"status": "ok"}


@health.get("/ready")
def ready(rt: RT):
    with rt.crypto.slot():
        get_crypto_core()
    return {"status": "ready"}
