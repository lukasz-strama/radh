"""Jawny mechanizm testowy, konfigurowany wyłącznie lokalnie w procesie węzła."""

from backend.app.crypto_core import CryptoCore
from .node import DhNode, _uint32
from .mallory import MalloryNode


class DeterministicDhNode(DhNode):
    """Stały lokalny wykładnik; nie używać w zwykłej sesji demonstratora."""

    def __init__(self, participant: str, secret: int, core: CryptoCore | None = None) -> None:
        _uint32(secret, 1, "INVALID_SECRET")
        super().__init__(participant, core)
        self._test_secret = secret

    def _new_secret(self) -> int:
        return self._test_secret


class DeterministicMalloryNode(MalloryNode):
    """Dwa stałe wykładniki ustawiane wyłącznie lokalnie w trybie testowym."""

    def __init__(self, x: int, y: int, core: CryptoCore | None = None) -> None:
        _uint32(x, 1, "INVALID_SECRET")
        _uint32(y, 1, "INVALID_SECRET")
        super().__init__(core)
        self._test_x, self._test_y = x, y

    def _new_pair(self) -> tuple[DhNode, DhNode]:
        return (DeterministicDhNode("mallory", self._test_x, self._core),
                DeterministicDhNode("mallory", self._test_y, self._core))
