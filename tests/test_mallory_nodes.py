"""Obliczenia C, atomowość i lokalny proces Mallory."""

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from backend.app.crypto_core import CryptoCore, CryptoCoreCallError
from nodes import MalloryNode, NodeError
from nodes.__main__ import dispatch
from nodes.testing import DeterministicDhNode, DeterministicMalloryNode


@pytest.fixture
def mallory(core):
    return DeterministicMalloryNode(7, 11, CryptoCore(core.path))


@pytest.mark.parametrize("order", [("alice", "bob"), ("bob", "alice")])
def test_reference(mallory, order, monkeypatch):
    calls = []
    native = mallory._core._modexp
    def modexp(*args):
        calls.append(tuple(arg.value for arg in args[:3]))
        return native(*args)
    monkeypatch.setattr(mallory._core, "_modexp", modexp)
    monkeypatch.setattr(mallory._core, "_exchange", lambda *args: pytest.fail("Centralna wymiana"))
    state = mallory.start_session("ref", 23, 5)
    assert (state.substitute_to_alice, state.substitute_to_bob) == (17, 22)
    for source in order:
        mallory.receive_public("ref", source, {"alice": 8, "bob": 19}[source])
    assert mallory.diagnostics() == dict(participant="mallory", session_id="ref",
                                        shared_with_alice=12, shared_with_bob=22)
    assert calls == [(5, 7, 23), (5, 11, 23)] + [
        (8, 7, 23) if source == "alice" else (19, 11, 23) for source in order]
    for role, secret, substitute, expected in [("alice", 6, 17, 12), ("bob", 15, 22, 22)]:
        node = DeterministicDhNode(role, secret, mallory._core)
        node.start_session("ref", 23, 5)
        node.receive_public("ref", substitute)
        assert node.diagnostics()["shared_secret"] == expected
    assert set(asdict(mallory.state)) == {
        "participant", "session_id", "phase", "p", "g", "original_from_alice",
        "original_from_bob", "substitute_to_alice", "substitute_to_bob"}


@pytest.mark.parametrize("field,value", [
    ("p", 0), ("p", 1), ("p", 9), ("p", 2**32), ("p", True), ("p", 23.0),
    ("p", "23"), ("g", 0), ("g", 1), ("g", 23), ("g", -1), ("g", True),
    ("g", "5"), ("g", 5.0), ("session_id", ""), ("session_id", None)])
def test_bad_start_preserves_state(mallory, field, value):
    mallory.start_session("old", 23, 5)
    before = mallory.state
    with pytest.raises(NodeError):
        mallory.start_session(**{**dict(session_id="new", p=23, g=5), field: value})
    assert mallory.state == before


@pytest.mark.parametrize("source", ["alice", "bob"])
@pytest.mark.parametrize("value", [0, -1, 23, 2**32, True, "8", 8.0, None])
def test_bad_public(mallory, source, value):
    mallory.start_session("ref", 23, 5)
    before = mallory.state
    with pytest.raises(NodeError):
        mallory.receive_public("ref", source, value)
    assert mallory.state == before


@pytest.mark.parametrize("source", [None, [], {}, True, "mallory", "Alice"])
def test_bad_source(mallory, source):
    with pytest.raises(NodeError) as error:
        mallory.receive_public("ref", source, 8)
    assert error.value.code == "INVALID_SOURCE"


def test_lifecycle(mallory):
    with pytest.raises(NodeError):
        mallory.receive_public("ref", "alice", 8)
    mallory.start_session("ref", 23, 5)
    with pytest.raises(NodeError):
        mallory.start_session("ref", 23, 5)
    with pytest.raises(NodeError):
        mallory.receive_public("old", "alice", 8)
    state = mallory.receive_public("ref", "alice", 8)
    assert state.phase == "partial"
    assert mallory.receive_public("ref", "alice", 8) == state
    with pytest.raises(NodeError):
        mallory.receive_public("ref", "alice", 19)
    with pytest.raises(NodeError):
        mallory.diagnostics()
    mallory.receive_public("ref", "bob", 1)
    assert mallory.diagnostics()["shared_with_bob"] == 1
    mallory.start_session("new", 23, 5)
    assert mallory.state.phase == "public_ready"
    assert mallory.state.original_from_alice is None
    assert mallory.state.original_from_bob is None
    with pytest.raises(NodeError):
        mallory.diagnostics()


@pytest.mark.parametrize("fail_at", [1, 2])
def test_atomic_start_c_failure(mallory, monkeypatch, fail_at):
    mallory.start_session("old", 23, 5)
    mallory.receive_public("old", "alice", 8)
    mallory.receive_public("old", "bob", 19)
    before = mallory.state, mallory.diagnostics()
    native = mallory._core._modexp
    count = 0
    def fail(*args):
        nonlocal count
        count += 1
        return 99 if count == fail_at else native(*args)
    monkeypatch.setattr(mallory._core, "_modexp", fail)
    with pytest.raises(CryptoCoreCallError):
        mallory.start_session("new", 23, 5)
    assert (mallory.state, mallory.diagnostics()) == before


@pytest.mark.parametrize("source", ["alice", "bob"])
def test_receive_c_failure(mallory, monkeypatch, source):
    mallory.start_session("ref", 23, 5)
    before = mallory.state
    with monkeypatch.context() as patch:
        patch.setattr(mallory._core, "_modexp", lambda *args: 1)
        with pytest.raises(CryptoCoreCallError):
            mallory.receive_public("ref", source, 8)
    assert mallory.state == before
    assert mallory.receive_public("ref", source, 8).phase == "partial"


def test_fresh_secrets(core, monkeypatch):
    values = iter([6, 10, 0, 2**32 - 2])
    def generate(bound):
        assert bound == 2**32 - 1
        return next(values)
    monkeypatch.setattr("nodes.node.secrets.randbelow", generate)
    node = MalloryNode(CryptoCore(core.path))
    first = node.start_session("first", 23, 5)
    assert (first.substitute_to_alice, first.substitute_to_bob) == (17, 22)
    second = node.start_session("second", 23, 5)
    assert second.substitute_to_alice == 5
    assert second.substitute_to_bob == pow(5, 2**32 - 1, 23)


@pytest.mark.parametrize("secret", [0, -1, 2**32, True, 7.0, "7"])
@pytest.mark.parametrize("side", [0, 1])
def test_bad_local_secret(core, secret, side):
    pair = [7, 11]
    pair[side] = secret
    with pytest.raises(NodeError):
        DeterministicMalloryNode(*pair, core=CryptoCore(core.path))


def test_protocol(mallory):
    start = dict(op="start", session_id="ref", p=23, g=5)
    for field in ("x", "y", "secret", "shared_with_alice"):
        with pytest.raises(NodeError):
            dispatch(mallory, {**start, field: 7})
    dispatch(mallory, start)
    with pytest.raises(NodeError):
        dispatch(mallory, dict(op="receive", session_id="ref", public_value=8))
    with pytest.raises(NodeError):
        dispatch(mallory, dict(op="diagnostics"))


def run_process(core, requests, env_values, flags):
    env = dict(os.environ, RADH_CRYPTO_CORE_LIBRARY=str(core.path))
    for name in ("RADH_NODE_TEST_SECRET", "RADH_MALLORY_TEST_X", "RADH_MALLORY_TEST_Y"):
        env.pop(name, None)
    env.update(env_values)
    return subprocess.run([sys.executable, "-m", "nodes", "--role", "mallory", *flags],
                          input="\n".join(requests) + "\n", text=True, capture_output=True,
                          timeout=10, cwd=Path(__file__).resolve().parents[1], env=env)


def test_process(core):
    requests = ['{"op":"start","session_id":"ref","p":23,"g":5}', '{',
                '{"op":"receive","session_id":"ref","source":[],"public_value":8}',
                '{"op":"receive","session_id":"ref","source":"bob","public_value":19}',
                '{"op":"receive","session_id":"ref","source":"alice","public_value":8}',
                '{"op":"diagnostics"}']
    result = run_process(core, requests, dict(RADH_MALLORY_TEST_X="7", RADH_MALLORY_TEST_Y="11"),
                         ["--test-mode", "--allow-diagnostics"])
    assert result.returncode == 0 and result.stderr == ""
    replies = list(map(json.loads, result.stdout.splitlines()))
    assert len(replies) == len(requests)
    assert replies[0]["pid"] != os.getpid()
    assert replies[0]["state"]["substitute_to_alice"] == 17
    assert replies[0]["state"]["substitute_to_bob"] == 22
    assert "error" in replies[1] and "error" in replies[2]
    assert replies[4]["state"]["phase"] == "complete"
    assert replies[5]["diagnostics"]["shared_with_alice"] == 12
    assert replies[5]["diagnostics"]["shared_with_bob"] == 22
    assert "secret" not in json.dumps(replies[:-1])
    restarted = run_process(core, ['{"op":"state"}', '{"op":"diagnostics"}'], {}, [])
    state, error = map(json.loads, restarted.stdout.splitlines())
    assert state["state"]["phase"] == "idle"
    assert error["error"]["code"] == "DIAGNOSTICS_DISABLED"


@pytest.mark.parametrize("values,flags", [
    ({"RADH_MALLORY_TEST_X": "7"}, []),
    ({"RADH_MALLORY_TEST_Y": "11"}, []),
    ({"RADH_MALLORY_TEST_X": "7"}, ["--test-mode"]),
    ({"RADH_MALLORY_TEST_X": "bad-private", "RADH_MALLORY_TEST_Y": "11"}, ["--test-mode"]),
    ({"RADH_NODE_TEST_SECRET": "6"}, []),
])
def test_bad_process_config(core, values, flags):
    result = run_process(core, [], values, flags)
    assert result.returncode == 1 and not result.stdout
    assert "Traceback" not in result.stderr and "bad-private" not in result.stderr
