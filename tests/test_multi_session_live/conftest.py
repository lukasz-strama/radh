"""Fixture testów systemowych #71; klasy pomocnicze są w helpers/multi_session_stack.py.

Nazwy z tego pliku nie są importowane przez testy (``from conftest import`` dotyczy
głównego tests/conftest.py), aby nie przesłaniać modułu ``conftest`` w pełnym pytest.
"""

import pytest

from helpers.multi_session_stack import ROLES, Stack


@pytest.fixture
def make_stack(core, tmp_path):
    """Fabryka: ``make_stack(env={...}, nodes=True)``; sprząta procesy po teście."""
    stacks: list[Stack] = []

    def factory(env: dict | None = None, nodes: bool | tuple = True,
                allow_diagnostics: bool = True, name: str = "stack") -> Stack:
        directory = tmp_path / f"{name}-{len(stacks)}"
        directory.mkdir()
        stack = Stack(directory, core.path, env, allow_diagnostics)
        stacks.append(stack)
        stack.start_backend()
        if nodes:
            stack.start_nodes(ROLES if nodes is True else nodes)
        return stack

    yield factory
    for stack in stacks:
        stack.close()


@pytest.fixture
def stack(make_stack) -> Stack:
    """Domyślne limity kontraktu, trzy rzeczywiste procesy ról, diagnostyka opt-in."""
    return make_stack()
