"""Jawny mechanizm testowy, konfigurowany wyłącznie lokalnie w procesie węzła."""

from backend.app.crypto_core import CryptoCore
from .node import DhNode, _uint32


class DeterministicDhNode(DhNode):
    """Stały lokalny wykładnik; nie używać w zwykłej sesji demonstratora."""

    def __init__(self, participant: str, secret: int, core: CryptoCore | None = None) -> None:
        _uint32(secret, 1, "INVALID_SECRET")
        super().__init__(participant, core)
        self._test_secret = secret

    def _new_secret(self) -> int:
        return self._test_secret
