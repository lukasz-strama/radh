"""Dwie lokalne wymiany Mallory, bez transportu i dostępu do sekretów partnerów."""

from dataclasses import dataclass

from backend.app.crypto_core import CryptoCore
from .node import DhNode, NodeError, _session_id


@dataclass(frozen=True)
class MalloryState:
    participant: str
    session_id: str | None
    phase: str
    p: int | None
    g: int | None
    original_from_alice: int | None
    original_from_bob: int | None
    substitute_to_alice: int | None
    substitute_to_bob: int | None


class MalloryNode:
    """Wywołania muszą być sekwencyjne, tak jak dla DhNode."""

    def __init__(self, core: CryptoCore | None = None) -> None:
        self._core = core if core is not None else CryptoCore()
        self._alice = DhNode("mallory", self._core)
        self._bob = DhNode("mallory", self._core)

    def _new_pair(self) -> tuple[DhNode, DhNode]:
        return DhNode("mallory", self._core), DhNode("mallory", self._core)

    @property
    def state(self) -> MalloryState:
        a, b = self._alice.state, self._bob.state
        count = sum(value is not None for value in (a.received_public, b.received_public))
        phase = "idle" if a.session_id is None else ("public_ready", "partial", "complete")[count]
        return MalloryState("mallory", a.session_id, phase, a.p, a.g,
                            a.received_public, b.received_public, a.public_value, b.public_value)

    def start_session(self, session_id: str, p: int, g: int) -> MalloryState:
        _session_id(session_id)
        if session_id == self.state.session_id:
            raise NodeError("SESSION_ALREADY_STARTED", "Ta sesja została już rozpoczęta.")
        # Nowa para staje się aktywna dopiero po sukcesie obu obliczeń C.
        alice, bob = self._new_pair()
        alice.start_session(session_id, p, g)
        bob.start_session(session_id, p, g)
        self._alice, self._bob = alice, bob
        return self.state

    def receive_public(self, session_id: str, source: str, public_value: int) -> MalloryState:
        if not isinstance(source, str) or source not in ("alice", "bob"):
            raise NodeError("INVALID_SOURCE", "Źródłem musi być alice albo bob.")
        node = self._alice if source == "alice" else self._bob
        node.receive_public(session_id, public_value)
        return self.state

    def diagnostics(self) -> dict[str, str | int]:
        """Jawny odczyt obu K dopiero po zakończeniu obu wymian; bez x i y."""
        a, b = self._alice.diagnostics(), self._bob.diagnostics()
        return {"participant": "mallory", "session_id": a["session_id"],
                "shared_with_alice": a["shared_secret"], "shared_with_bob": b["shared_secret"]}
