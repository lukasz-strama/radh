"""Ulotny koordynator DH: przechowuje wyłącznie parametry publiczne i metadane."""

from threading import RLock
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from .models import ErrorResponse
from .node_presence import Presence
from .session_models import (
    Acknowledge, CreateSession, DiagnosticReport, Event, Identifier, Interception,
    MalloryDiagnosticReport, MalloryDiagnostics, Message, PublicMessage, Replacement,
    Role, Session, SessionDiagnostics,
)


class SessionError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def conflict(code: str, message: str):
    raise SessionError(409, code, message)


class SessionStore:
    """Jedna sesja na proces serwera; blokada obejmuje każdą zmianę i jej log."""

    def __init__(self):
        self.lock = RLock()
        self.session: Session | None = None
        self.used_ids: set[str] = set()
        self._diagnostics = SessionDiagnostics()
        self._mallory_diagnostics = MalloryDiagnostics()

    def _get(self, session_id: str) -> Session:
        if self.session is None or self.session.session_id != session_id:
            raise SessionError(404, "SESSION_NOT_FOUND", "Nie znaleziono sesji.")
        return self.session

    @staticmethod
    def _event(session: Session, event_type, **fields):
        session.events.append(Event(sequence=len(session.events) + 1, type=event_type, **fields))

    def create(self, request: CreateSession) -> Session:
        with self.lock:
            if request.session_id == "current" or request.session_id in self.used_ids:
                conflict("SESSION_ID_IN_USE", "Identyfikator jest zarezerwowany lub został już użyty.")
            if self.session is not None:
                if self.session.status in {"created", "running"}:
                    conflict("SESSION_BUSY", "Najpierw zakończ lub anuluj bieżącą sesję.")
            self.session = Session(**request.model_dump())
            self._diagnostics = SessionDiagnostics()
            self._mallory_diagnostics = MalloryDiagnostics()
            self.used_ids.add(request.session_id)
            self._event(self.session, "session_created")
            return self.session.model_copy(deep=True)

    def get(self, session_id: str | None = None) -> Session:
        with self.lock:
            session = self._get(session_id if session_id is not None else (
                self.session.session_id if self.session else ""
            ))
            return session.model_copy(deep=True)

    def transition(self, session_id: str, action: Literal["start", "cancel"], *, mallory_online: bool = False) -> Session:
        with self.lock:
            session = self._get(session_id)
            if action == "start":
                if session.status != "created":
                    conflict("INVALID_SESSION_STATE", "Można uruchomić tylko nową sesję.")
                if session.mode == "mitm" and not mallory_online:
                    conflict("MALLORY_UNAVAILABLE", "Uruchom proces Mallory przed rozpoczęciem sesji MITM.")
                session.status = "running"
                self._event(session, "session_started")
            else:
                if session.status not in {"created", "running"}:
                    conflict("INVALID_SESSION_STATE", "Sesja została już zakończona.")
                session.status = "cancelled"
                self._event(session, "session_cancelled")
            return session.model_copy(deep=True)

    def send(self, session_id: str, request: PublicMessage) -> Message:
        with self.lock:
            session = self._get(session_id)
            # Powtórzenie identycznego POST jest bezpieczne także po zakończeniu sesji.
            for message in session.messages:
                if message.message_id == request.message_id:
                    original = message.model_dump(exclude={"status"})
                    interception = next((i for i in session.interceptions if i.message_id == message.message_id), None)
                    if interception is not None:
                        original["public_value"] = interception.original_value
                    if original == request.model_dump():
                        return message.model_copy(deep=True)
                    conflict("MESSAGE_ID_CONFLICT", "Identyfikator wiadomości ma już inną treść.")
            if session.status != "running":
                conflict("INVALID_SESSION_STATE", "Sesja nie jest uruchomiona.")
            if request.sender == request.recipient or not 1 <= request.public_value < session.prime:
                raise SessionError(422, "INVALID_MESSAGE", "Niepoprawny odbiorca lub wartość publiczna.")
            if any(m.sender == request.sender for m in session.messages):
                conflict("PUBLIC_VALUE_ALREADY_SENT", "Węzeł wysłał już wartość publiczną.")
            message = Message(**request.model_dump())
            if session.mode == "mitm":
                message.status = "intercepted"
                session.interceptions.append(Interception(
                    message_id=message.message_id, original_sender=message.sender,
                    recipient=message.recipient, original_value=message.public_value,
                ))
            session.messages.append(message)
            session.participants[request.sender] = "published"
            self._event(session, "message_intercepted" if session.mode == "mitm" else "public_value",
                        **request.model_dump(exclude={"type"}), status=message.status)
            return message.model_copy(deep=True)

    def inbox(self, session_id: str, recipient: Role) -> list[Message]:
        with self.lock:
            session = self._get(session_id)
            if session.status not in {"running", "completed"}:
                conflict("INVALID_SESSION_STATE", "Sesja nie jest uruchomiona.")
            return [m.model_copy(deep=True) for m in session.messages
                    if m.recipient == recipient and m.status == "queued"]

    def acknowledge(self, session_id: str, message_id: str, recipient: Role) -> Message:
        with self.lock:
            session = self._get(session_id)
            message = next((m for m in session.messages if m.message_id == message_id), None)
            if message is None:
                raise SessionError(404, "MESSAGE_NOT_FOUND", "Nie znaleziono wiadomości.")
            if message.recipient != recipient:
                raise SessionError(422, "INVALID_RECIPIENT", "Potwierdzenie musi wskazywać odbiorcę.")
            if message.status == "intercepted":
                conflict("INTERCEPTION_REQUIRED", "Wiadomość oczekuje na podmianę przez Mallory.")
            if message.status == "processed":
                return message.model_copy(deep=True)
            if session.status != "running":
                conflict("INVALID_SESSION_STATE", "Sesja nie jest uruchomiona.")
            if not any(m.sender == recipient for m in session.messages):
                conflict("PUBLIC_VALUE_REQUIRED", "Najpierw wyślij własną wartość publiczną.")
            message.status = "processed"
            for interception in session.interceptions:
                if interception.message_id == message_id:
                    interception.status = "processed"
            session.participants[recipient] = "received"
            self._event(session, "message_processed", **message.model_dump(exclude={"type", "status"}))
            if len(session.messages) == 2 and all(m.status == "processed" for m in session.messages):
                session.status = "completed"
                self._event(session, "session_completed")
            return message.model_copy(deep=True)

    def _mitm(self, session_id: str) -> Session:
        session = self._get(session_id)
        if session.mode != "mitm":
            conflict("MITM_REQUIRED", "Operacja wymaga sesji MITM.")
        if session.status not in {"running", "completed"}:
            conflict("INVALID_SESSION_STATE", "Sesja nie jest uruchomiona ani ukończona.")
        return session

    def interceptions(self, session_id: str) -> list[Interception]:
        with self.lock:
            return [i.model_copy(deep=True) for i in self._mitm(session_id).interceptions]

    def forward(self, session_id: str, message_id: str, replacement: Replacement) -> Interception:
        with self.lock:
            session = self._mitm(session_id)
            interception = next((i for i in session.interceptions if i.message_id == message_id), None)
            if interception is None:
                raise SessionError(404, "MESSAGE_NOT_FOUND", "Nie znaleziono przechwyconej wiadomości.")
            value = replacement.public_value
            if not 1 <= value < session.prime:
                raise SessionError(422, "INVALID_MESSAGE", "Wartość publiczna musi spełniać 1 <= value < prime.")
            if interception.delivered_value is not None:
                if interception.delivered_value != value:
                    conflict("REPLACEMENT_CONFLICT", "Mallory przekazała już inną wartość dla tej wiadomości.")
                return interception.model_copy(deep=True)
            message = next(m for m in session.messages if m.message_id == message_id)
            interception.delivered_value = value
            interception.actual_sender = "mallory"
            interception.status = "forwarded"
            message.public_value, message.status = value, "queued"
            self._event(session, "message_forwarded", sender="mallory", recipient=message.recipient,
                        public_value=value, message_id=message_id, status="queued")
            return interception.model_copy(deep=True)

    def mallory_diagnostics(self, session_id: str) -> MalloryDiagnostics:
        with self.lock:
            self._get(session_id)
            return self._mallory_diagnostics.model_copy(deep=True)

    def report_mallory_diagnostics(self, session_id: str, report: MalloryDiagnosticReport) -> None:
        with self.lock:
            session = self._mitm(session_id)
            if len(session.interceptions) != 2 or any(i.status == "pending" for i in session.interceptions):
                conflict("FORWARD_REQUIRED", "Najpierw przekaż obie podmienione wiadomości.")
            if any(not 1 <= value < session.prime for value in report.model_dump().values()):
                raise SessionError(422, "INVALID_DIAGNOSTIC", "Wynik diagnostyczny musi spełniać 1 <= K < prime.")
            result = MalloryDiagnostics(**report.model_dump())
            if self._mallory_diagnostics.shared_with_alice is not None and self._mallory_diagnostics != result:
                conflict("DIAGNOSTIC_CONFLICT", "Mallory zgłosiła już inne wyniki diagnostyczne.")
            self._mallory_diagnostics = result

    def diagnostics(self, session_id: str) -> SessionDiagnostics:
        with self.lock:
            self._get(session_id)
            return self._diagnostics.model_copy(deep=True)

    def report_diagnostics(self, session_id: str, report: DiagnosticReport) -> None:
        with self.lock:
            session = self._get(session_id)
            if session.status not in {"running", "completed"}:
                conflict("INVALID_SESSION_STATE", "Sesja nie jest uruchomiona ani ukończona.")
            if session.participants[report.participant] != "received":
                conflict("ACK_REQUIRED", "Najpierw potwierdź przetworzenie wiadomości partnera.")
            if not 1 <= report.shared_secret < session.prime:
                raise SessionError(422, "INVALID_DIAGNOSTIC", "Wynik diagnostyczny musi spełniać 1 <= K < prime.")
            previous = getattr(self._diagnostics, report.participant)
            if previous is not None and previous != report.shared_secret:
                conflict("DIAGNOSTIC_CONFLICT", "Uczestnik zgłosił już inny wynik diagnostyczny.")
            setattr(self._diagnostics, report.participant, report.shared_secret)


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.dh_sessions


Store = Annotated[SessionStore, Depends(get_session_store)]
router = APIRouter(prefix="/api/v1/dh/sessions", tags=["Sesje DH"], responses={
    code: {"model": ErrorResponse} for code in (404, 409, 422)
})


@router.post("", response_model=Session, status_code=201, summary="Utwórz ulotną sesję DH")
def create_session(body: CreateSession, store: Store):
    return store.create(body)


@router.get("/current", response_model=Session, summary="Odczytaj sesję dla oczekujących agentów")
def current_session(store: Store):
    return store.get()


@router.get("/{session_id}", response_model=Session, summary="Odczytaj status i publiczny log sesji")
def get_session(session_id: Identifier, store: Store):
    return store.get(session_id)


@router.post("/{session_id}/start", response_model=Session, summary="Uruchom wymianę bez uruchamiania procesów")
def start_session(session_id: Identifier, store: Store, presence: Presence):
    return store.transition(session_id, "start", mallory_online=presence.snapshot()["mallory"].online)


@router.post("/{session_id}/cancel", response_model=Session, summary="Anuluj sesję i zwolnij koordynatora")
def cancel_session(session_id: Identifier, store: Store):
    return store.transition(session_id, "cancel")


@router.post("/{session_id}/messages", response_model=Message, summary="Przekaż wartość publiczną drugiemu węzłowi")
def send_message(session_id: Identifier, body: PublicMessage, store: Store):
    return store.send(session_id, body)


@router.get("/{session_id}/messages", response_model=list[Message], summary="Odczytaj wiadomości oczekujące na potwierdzenie")
def receive_messages(session_id: Identifier, recipient: Role, store: Store):
    return store.inbox(session_id, recipient)


@router.post("/{session_id}/messages/{message_id}/ack", response_model=Message, summary="Potwierdź przetworzenie wiadomości")
def acknowledge_message(session_id: Identifier, message_id: Identifier, body: Acknowledge, store: Store):
    return store.acknowledge(session_id, message_id, body.recipient)


@router.get("/{session_id}/events", response_model=list[Event], summary="Odczytaj zdarzenia po wskazanym numerze")
def get_events(session_id: Identifier, store: Store, after: Annotated[int, Query(ge=0)] = 0):
    return [e for e in store.get(session_id).events if e.sequence > after]


@router.get("/{session_id}/diagnostics", response_model=SessionDiagnostics,
            summary="Odczytaj opcjonalne wyniki edukacyjne poza protokołem DH")
def get_diagnostics(session_id: Identifier, store: Store):
    return store.diagnostics(session_id)


@router.post("/{session_id}/diagnostics", status_code=204,
             summary="Zapisz jawny wynik diagnostyczny po potwierdzeniu przetworzenia")
def report_diagnostics(session_id: Identifier, body: DiagnosticReport, store: Store) -> Response:
    store.report_diagnostics(session_id, body)
    return Response(status_code=204)


@router.get("/{session_id}/interceptions", response_model=list[Interception],
            summary="Odczytaj oryginały i stan podmiany dla procesu Mallory")
def get_interceptions(session_id: Identifier, store: Store):
    return store.interceptions(session_id)


@router.post("/{session_id}/interceptions/{message_id}/forward", response_model=Interception,
             summary="Przekaż podmianę z procesu Mallory do zamierzonego odbiorcy")
def forward_interception(session_id: Identifier, message_id: Identifier, body: Replacement, store: Store):
    return store.forward(session_id, message_id, body)


@router.get("/{session_id}/diagnostics/mallory", response_model=MalloryDiagnostics,
            summary="Odczytaj dwa opcjonalne wyniki edukacyjne Mallory")
def get_mallory_diagnostics(session_id: Identifier, store: Store):
    return store.mallory_diagnostics(session_id)


@router.post("/{session_id}/diagnostics/mallory", status_code=204,
             summary="Zapisz wyniki Mallory poza komunikatami protokołu")
def report_mallory_diagnostics(session_id: Identifier, body: MalloryDiagnosticReport, store: Store) -> Response:
    store.report_mallory_diagnostics(session_id, body)
    return Response(status_code=204)
