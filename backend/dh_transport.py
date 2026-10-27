"""Klient HTTP uruchamiany osobno przy węźle z #36, nigdy wewnątrz FastAPI."""

import argparse
import json
import os
import sys
import time
from http.client import HTTPException
from typing import Literal, Protocol

from pydantic import TypeAdapter, ValidationError

from .app.session_models import Message, Session


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


class InvalidResponse(Exception):
    """Odpowiedź koordynatora nie spełnia kontraktu; nie ujawniamy jej treści."""
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TransportError(Exception):
    """Kontrolowany błąd HTTP bez treści wiadomości w diagnostyce."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class HttpTransport:
    def __init__(self, base_url: str, role: Role, node: Node) -> None:
        if role not in ("alice", "bob"):
            raise ValueError("Niepoprawna rola transportu.")
        self.base_url = base_url.rstrip("/") + "/api/v1/dh/sessions"
        self.role = role
        self.peer = "bob" if role == "alice" else "alice"
        self.node = node

    def request(self, path: str, body: dict[str, object] | None = None) -> object:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base_url + path, data=data,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:
                try:
                    return json.load(response)
                except (ValueError, UnicodeError, RecursionError):
                    raise InvalidResponse() from None
        except HTTPError as error:
            status = error.code
            error.close()
            raise TransportError(status) from None

    def poll(self) -> None:
        """Jedna iteracja; ponowienie POST/ACK nie powtarza operacji protokołu."""
        try:
            session = Session.model_validate(self.request("/current"))
        except ValidationError:
            raise InvalidResponse() from None
        if not {"session_id", "prime", "generator", "mode", "status"} <= session.model_fields_set:
            raise InvalidResponse()
        if session.status != "running" or session.mode != "normal":
            return
        session_id = session.session_id
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Transport HTTP dla osobnego węzła DH (#37).")
    parser.add_argument("--role", choices=("alice", "bob"), required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--test-mode", action="store_true")
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
    transport = HttpTransport(args.url, args.role, node)
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
        except (NodeError, CryptoCoreCallError, CryptoCoreInputError):
            print("Node rejected operation; retrying", file=sys.stderr)
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
