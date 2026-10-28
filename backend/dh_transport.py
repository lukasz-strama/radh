"""Klient HTTP uruchamiany osobno przy węźle z #36, nigdy wewnątrz FastAPI."""

import argparse
import json
import os
import sys
import time
from http.client import HTTPException
from typing import Literal, Protocol
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import TypeAdapter, ValidationError

from .app.session_models import DiagnosticReport, Message, Session


Role = Literal["alice", "bob"]
MESSAGE_LIST = TypeAdapter(list[Message])


class NodeState(Protocol):
    @property
    def session_id(self) -> str | None: ...

    @property
    def public_value(self) -> int | None: ...


class Node(Protocol):
    """Minimalny interfejs obliczeń dostarczany przez #36."""

    @property
    def state(self) -> NodeState: ...

    def start_session(self, session_id: str, p: int, g: int) -> object: ...

    def receive_public(self, session_id: str, public_value: int) -> object: ...

    def diagnostics(self) -> dict[str, str | int]: ...


class InvalidResponse(Exception):
    """Odpowiedź koordynatora nie spełnia kontraktu; nie ujawniamy jej treści."""


class TransportError(Exception):
    """Kontrolowany błąd HTTP bez treści wiadomości w diagnostyce."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class HttpTransport:
    def __init__(self, base_url: str, role: Role, node: Node, *, allow_diagnostics: bool = False) -> None:
        if role not in ("alice", "bob"):
            raise ValueError("Niepoprawna rola transportu.")
        self.base_url = base_url.rstrip("/") + "/api/v1/dh/sessions"
        self.role = role
        self.peer = "bob" if role == "alice" else "alice"
        self.node = node
        self.allow_diagnostics = allow_diagnostics
        self._diagnostics_sent: str | None = None
        self._heartbeat_url = base_url.rstrip("/") + f"/api/v1/dh/nodes/{role}/heartbeat"

    def request(self, path: str, body: dict[str, object] | None = None) -> object:
        return self._request_url(self.base_url + path, body)

    @staticmethod
    def _request_url(url: str, body: dict[str, object] | None = None,
                     *, method: str | None = None, timeout: float = 5) -> object:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(url, data=data, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                if response.status == 204:
                    return None
                try:
                    return json.load(response)
                except (ValueError, UnicodeError, RecursionError):
                    raise InvalidResponse() from None
        except HTTPError as error:
            status = error.code
            error.close()
            raise TransportError(status) from None

    def heartbeat(self) -> None:
        self._request_url(self._heartbeat_url, method="POST", timeout=2)

    def heartbeat_loop(self, stop: Event) -> None:
        """Osobny wątek nie odczytuje węzła ani nie czeka na wymianę/diagnostykę."""
        while not stop.is_set():
            started = time.monotonic()
            try:
                self.heartbeat()
            except (TransportError, InvalidResponse, URLError, OSError, HTTPException):
                # Kolejna próba jest niezależna od stanu sesji i ponowień protokołu.
                print("Heartbeat failed; retrying", file=sys.stderr)
            stop.wait(max(0, 1 - (time.monotonic() - started)))

    def _publish_diagnostics(self, session_id: str) -> None:
        if (not self.allow_diagnostics or self._diagnostics_sent == session_id
                or self.node.state.session_id != session_id):
            return
        raw = self.node.diagnostics()
        if raw.get("participant") != self.role or raw.get("session_id") != session_id:
            raise InvalidResponse()
        try:
            report = DiagnosticReport(participant=self.role, shared_secret=raw.get("shared_secret"))
        except ValidationError:
            raise InvalidResponse() from None
        self.request(f"/{session_id}/diagnostics", report.model_dump())
        self._diagnostics_sent = session_id

    def poll(self) -> None:
        """Jedna iteracja; ponowienie POST/ACK nie powtarza operacji protokołu."""
        try:
            session = Session.model_validate(self.request("/current"))
        except ValidationError:
            raise InvalidResponse() from None
        if not {"session_id", "prime", "generator", "mode", "status"} <= session.model_fields_set:
            raise InvalidResponse()
        if session.mode != "normal":
            return
        session_id = session.session_id
        if (session.status in {"running", "completed"}
                and session.participants[self.role] == "received"):
            # Obsługuje utraconą odpowiedź ACK oraz ponowienia po completed.
            self._publish_diagnostics(session_id)
        if session.status != "running":
            return
        if self.node.state.session_id != session_id:
            self.node.start_session(session_id, session.prime, session.generator)
        self.request(f"/{session_id}/messages", {
            "message_id": f"{self.role}-public", "sender": self.role,
            "recipient": self.peer, "type": "public_value",
            "public_value": self.node.state.public_value,
        })
        try:
            messages = MESSAGE_LIST.validate_python(
                self.request(f"/{session_id}/messages?recipient={self.role}")
            )
        except ValidationError:
            raise InvalidResponse() from None
        # Sprawdź całą odpowiedź przed zmianą stanu lokalnego lub wysłaniem ACK.
        if len(messages) > 1 or any(
            "status" not in message.model_fields_set
            or message.sender != self.peer or message.recipient != self.role
            or message.status != "queued"
            or not 1 <= message.public_value < session.prime
            for message in messages
        ):
            raise InvalidResponse()
        for message in messages:
            self.node.receive_public(session_id, message.public_value)
            # ACK następuje dopiero po poprawnym obliczeniu w procesie węzła.
            self.request(f"/{session_id}/messages/{message.message_id}/ack",
                         {"recipient": self.role})
            self._publish_diagnostics(session_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Transport HTTP dla osobnego węzła DH (#37).")
    parser.add_argument("--role", choices=("alice", "bob"), required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--allow-diagnostics", action="store_true",
                        help="Jawnie publikuj edukacyjny wynik K w osobnym API diagnostyki.")
    args = parser.parse_args()
    try:
        from nodes import DhNode, NodeError
        from backend.app.crypto_core import CryptoCoreCallError, CryptoCoreInputError, CryptoCoreLoadError
    except ImportError:
        print("Wymagany moduł nodes z zadania #36. Uruchom z katalogu głównego repozytorium.", file=sys.stderr)
        return 1
    configured_secret = os.environ.pop("RADH_NODE_TEST_SECRET", None)
    try:
        if args.test_mode:
            from nodes.testing import DeterministicDhNode
            node = DeterministicDhNode(args.role, int(configured_secret or "0"))
        elif configured_secret is not None:
            raise ValueError("Konfiguracja testowa wymaga --test-mode.")
        else:
            node = DhNode(args.role)
    except (ValueError, CryptoCoreLoadError):
        print("Nie można uruchomić węzła; sprawdź bibliotekę C i konfigurację lokalną.", file=sys.stderr)
        return 1
    transport = HttpTransport(args.url, args.role, node, allow_diagnostics=args.allow_diagnostics)
    stop = Event()
    heartbeat_thread = Thread(target=transport.heartbeat_loop, args=(stop,), daemon=True)
    heartbeat_thread.start()
    try:
        run_exchange(transport, (NodeError, CryptoCoreCallError, CryptoCoreInputError))
    finally:
        stop.set()
        heartbeat_thread.join(timeout=3)
    return 0


def run_exchange(transport: HttpTransport, node_errors: tuple[type[Exception], ...]) -> None:
    while True:
        try:
            transport.poll()
        except TransportError as error:
            # Brak sesji, anulowanie podczas odczytu i restart serwera są oczekiwane.
            if error.status not in (404, 409):
                print(f"Transport HTTP: {error.status}", file=sys.stderr)
        except (URLError, TimeoutError, OSError, HTTPException):
            print("Coordinator unavailable; retrying", file=sys.stderr)
        except InvalidResponse:
            print("Coordinator returned invalid response; retrying", file=sys.stderr)
        except node_errors:
            print("Node rejected operation; retrying", file=sys.stderr)
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
