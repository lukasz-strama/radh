"""Granice losowania wykładników DH po poprawce BUG-NODE-01."""

import secrets

import pytest

from backend.app.crypto_core import CryptoCore
from nodes.mallory import MalloryNode
from nodes.node import DhNode

SESSION = "a" * 32


@pytest.fixture
def adapter(core):
    return CryptoCore(core.path)


@pytest.mark.parametrize("role", ["alice", "bob", "mallory"])
@pytest.mark.parametrize(("draw", "expected"), [(0, 2), (19, 21)])
def test_full_order_exponents_at_both_bounds(adapter, monkeypatch, role, draw, expected):
    def randbelow(upper):
        assert upper == 20 and 0 <= draw < upper
        return draw

    monkeypatch.setattr(secrets, "randbelow", randbelow)
    if role == "mallory":
        state = MalloryNode(adapter).start_session(SESSION, 23, 5)
        values = (state.substitute_to_alice, state.substitute_to_bob)
    else:
        values = (DhNode(role, adapter).start_session(SESSION, 23, 5).public_value,)
    assert all(value == pow(5, expected, 23) != 1 for value in values)


@pytest.mark.parametrize("role", ["alice", "bob", "mallory"])
def test_smallest_group_uses_exponent_one(adapter, monkeypatch, role):
    def unexpected_draw(_):
        pytest.fail("Dla p=3 nie ma losowania.")

    monkeypatch.setattr(secrets, "randbelow", unexpected_draw)
    if role == "mallory":
        state = MalloryNode(adapter).start_session(SESSION, 3, 2)
        assert state.substitute_to_alice == state.substitute_to_bob == 2
    else:
        node = DhNode(role, adapter)
        assert node.start_session(SESSION, 3, 2).public_value == 2
        node.receive_public(SESSION, 2)
        assert node.diagnostics()["shared_secret"] == 2


def test_manual_generator_of_smaller_order_still_allows_identity(adapter, monkeypatch):
    def randbelow(upper):
        assert upper == 20
        return 9  # Wykładnik 11 jest w zakresie, a g=4 ma rząd 11.

    monkeypatch.setattr(secrets, "randbelow", randbelow)
    assert DhNode("bob", adapter).start_session(SESSION, 23, 4).public_value == 1
