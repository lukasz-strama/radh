"""BUG-NODE-01: klucz prywatny węzła nie jest losowany z [2, p − 2].

Reprodukcja w UI: DH, p = 23, g = 5, kilkanaście sesji z diagnostyką — co ~22. sesja
któraś strona ma A = 1 (lub B = 1) i K = 1. ``DhNode._new_secret`` (nodes/node.py) zwraca
``randbelow(UINT32_MAX) + 1`` niezależnie od p, więc dla małych p wykładnik ≡ 0 (mod p − 1)
z prawdopodobieństwem ≈ 1/(p − 1). Ten sam kod losuje x i y Mallory.

Test jest deterministyczny: podmienia źródło losowości tak, by zwróciło wykładnik
podzielny przez p − 1, i sprawdza, że wartość publiczna nie jest trywialna.
"""

import secrets

import pytest

from backend.app.crypto_core import CryptoCore
from nodes.node import DhNode

SESSION = "a" * 32


@pytest.fixture
def adapter(core):
    return CryptoCore(core.path)


@pytest.mark.xfail(strict=True, reason="BUG-NODE-01: wykładnik nie jest redukowany do [2, p − 2]")
@pytest.mark.parametrize("draw", [21, 43, 65])
def test_public_value_is_never_trivial(adapter, monkeypatch, draw):
    # randbelow(n) + 1 == wielokrotność 22 → g^secret ≡ 1 (mod 23)
    assert (draw + 1) % 22 == 0
    monkeypatch.setattr(secrets, "randbelow", lambda _upper: draw)
    state = DhNode("alice", adapter).start_session(SESSION, 23, 5)
    assert state.public_value != 1, "A = 1 → K = 1 dla każdej wartości partnera"


def test_public_value_in_group_for_random_draws(adapter):
    """Regresja (przechodzi): losowe wykładniki dają wartość w [1, p − 1]."""
    for index in range(200):
        state = DhNode("bob", adapter).start_session(f"{index:032x}", 23, 5)
        assert 1 <= state.public_value < 23
