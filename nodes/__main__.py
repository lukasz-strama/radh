"""Lokalny interfejs JSON Lines przez stdin/stdout, bez serwera HTTP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from backend.app.crypto_core import CryptoCoreCallError, CryptoCoreInputError, CryptoCoreLoadError
from .node import DhNode, NodeError


def dispatch(node: DhNode, request: object, allow_diagnostics: bool = False) -> dict[str, object]:
    """Obsłuż lokalne polecenie; żadne pole protokołu nie ustawia sekretu."""
    fields = {"start": {"op", "session_id", "p", "g"},
              "receive": {"op", "session_id", "public_value"},
              "state": {"op"}, "diagnostics": {"op"}}
    if not isinstance(request, dict) or not isinstance(request.get("op"), str):
        raise NodeError("INVALID_REQUEST", "Wymagany obiekt polecenia z polem op.")
    op = request["op"]
    if op not in fields or set(request) != fields[op]:
        raise NodeError("INVALID_REQUEST", "Niepoprawna operacja lub zestaw pól.")
    if op == "diagnostics":
        if not allow_diagnostics:
            raise NodeError("DIAGNOSTICS_DISABLED", "Diagnostyka lokalna jest wyłączona.")
        return {"diagnostics": node.diagnostics()}
    if op == "start":
        node.start_session(request["session_id"], request["p"], request["g"])
    elif op == "receive":
        node.receive_public(request["session_id"], request["public_value"])
    return {"state": asdict(node.state), "pid": os.getpid()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Lokalny uczestnik edukacyjnej wymiany DH.")
    parser.add_argument("--role", choices=("alice", "bob"), required=True)
    parser.add_argument("--test-mode", action="store_true", help="Użyj lokalnej RADH_NODE_TEST_SECRET.")
    parser.add_argument("--allow-diagnostics", action="store_true", help="Zezwól na jawny lokalny odczyt K.")
    args = parser.parse_args()
    # Usunięcie zmiennej ogranicza jej dziedziczenie przez ewentualne procesy potomne.
    configured_secret = os.environ.pop("RADH_NODE_TEST_SECRET", None)
    try:
        if args.test_mode:
            from .testing import DeterministicDhNode
            try:
                secret = int(configured_secret) if configured_secret is not None else 0
            except ValueError:
                secret = 0
            node = DeterministicDhNode(args.role, secret)
        elif configured_secret is not None:
            raise NodeError("TEST_MODE_REQUIRED", "Konfiguracja testowa wymaga --test-mode.")
        else:
            node = DhNode(args.role)
    except (NodeError, CryptoCoreLoadError):
        print("Nie można uruchomić węzła: sprawdź bibliotekę C i konfigurację testową.", file=sys.stderr)
        return 1
    for line in sys.stdin:
        try:
            response = dispatch(node, json.loads(line), args.allow_diagnostics)
        except (CryptoCoreCallError, CryptoCoreInputError):
            response = {"error": {"code": "CRYPTO_CORE_ERROR", "message": "Nie udało się wykonać obliczenia C."}}
        except (ValueError, RecursionError) as exc:
            code = exc.code if isinstance(exc, NodeError) else "INVALID_REQUEST"
            response = {"error": {"code": code, "message": "Odrzucono polecenie; stan pozostaje bez zmian."}}
        print(json.dumps(response, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
