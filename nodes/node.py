"""Obliczenia i pojedyncza, ulotna sesja jednego uczestnika DH."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from math import isqrt

from backend.app.crypto_core import CryptoCore, UINT32_MAX


class NodeError(ValueError):
    """Kontrolowany błąd bez dołączania danych wejściowych ani sekretów."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class NodeState:
    """Publiczny, niemutowalny obraz stanu, bez sekretów i wyników kluczowych."""

    participant: str
    session_id: str | None
    phase: str
    p: int | None
    g: int | None
    public_value: int | None
    received_public: int | None


def _uint32(value: int, minimum: int, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= UINT32_MAX:
        raise NodeError(code, "Wymagana liczba całkowita w dopuszczalnym zakresie uint32.")


def _session_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise NodeError("INVALID_SESSION", "Identyfikator sesji musi mieć od 1 do 128 znaków.")


class DhNode:
    """Jeden lokalny sekret; wywołania instancji należy wykonywać sekwencyjnie."""

    def __init__(self, participant: str, core: CryptoCore | None = None) -> None:
        # Dowolna nazwa uczestnika umożliwia użycie obliczeń także w przyszłym Mallory.
        if not isinstance(participant, str) or not participant.isidentifier():
            raise NodeError("INVALID_PARTICIPANT", "Niepoprawna nazwa uczestnika.")
        self._core = core if core is not None else CryptoCore()
        self._state = NodeState(participant, None, "idle", None, None, None, None)
        self._secret: int | None = None
        self._shared_secret: int | None = None

    @property
    def state(self) -> NodeState:
        return self._state

    def _new_secret(self) -> int:
        return secrets.randbelow(UINT32_MAX) + 1

    def start_session(self, session_id: str, p: int, g: int) -> NodeState:
        """Oblicz wartość publiczną i atomowo zastąp poprzednią sesję po sukcesie."""
        _session_id(session_id)
        _uint32(p, 2, "INVALID_PRIME")
        if (p % 2 == 0 and p != 2) or any(p % d == 0 for d in range(3, isqrt(p) + 1, 2)):
            raise NodeError("INVALID_PRIME", "Parametr p musi być liczbą pierwszą.")
        _uint32(g, 2, "INVALID_GENERATOR")
        if g >= p:
            raise NodeError("INVALID_GENERATOR", "Generator musi spełniać 2 <= g < p.")
        if session_id == self._state.session_id:
            raise NodeError("SESSION_ALREADY_STARTED", "Ta sesja została już rozpoczęta.")
        secret = self._new_secret()
        _uint32(secret, 1, "INVALID_SECRET")
        public_value = self._core.modexp(g, secret, p)
        state = NodeState(self._state.participant, session_id, "public_ready", p, g, public_value, None)
        self._secret, self._shared_secret, self._state = secret, None, state
        return state

    def receive_public(self, session_id: str, public_value: int) -> NodeState:
        """Przyjmij wartość partnera; identyczny duplikat jest idempotentny."""
        _session_id(session_id)
        state = self._state
        if state.session_id is None:
            raise NodeError("NOT_INITIALIZED", "Najpierw rozpocznij sesję.")
        if session_id != state.session_id:
            raise NodeError("SESSION_MISMATCH", "Wiadomość dotyczy innej sesji.")
        _uint32(public_value, 1, "INVALID_PUBLIC_VALUE")
        assert state.p is not None and self._secret is not None
        if public_value >= state.p:
            raise NodeError("INVALID_PUBLIC_VALUE", "Wartość publiczna musi spełniać 1 <= value < p.")
        if state.received_public is not None:
            if public_value == state.received_public:
                return state
            raise NodeError("PUBLIC_VALUE_CONFLICT", "Sesja ma już inną wartość partnera.")
        shared_secret = self._core.modexp(public_value, self._secret, state.p)
        new_state = NodeState(state.participant, state.session_id, "complete", state.p,
                              state.g, state.public_value, public_value)
        self._shared_secret, self._state = shared_secret, new_state
        return new_state

    def diagnostics(self) -> dict[str, str | int]:
        """Jawna diagnostyka lokalna: wynik K, nigdy prywatny wykładnik."""
        if self._shared_secret is None:
            raise NodeError("NOT_COMPLETE", "Wspólny sekret nie został jeszcze obliczony.")
        assert self._state.session_id is not None
        return {"participant": self._state.participant, "session_id": self._state.session_id,
                "shared_secret": self._shared_secret}
