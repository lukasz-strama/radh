"""Testy pojedynczego węzła i rzeczywistej wymiany między procesami."""

import ctypes
import io
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from backend.app.crypto_core import CryptoCore, CryptoCoreCallError, CryptoCoreInputError, UINT32_MAX
from nodes import DhNode, NodeError
from nodes.__main__ import dispatch
from nodes.testing import DeterministicDhNode


@pytest.fixture
def adapter(core):
    return CryptoCore(core.path)


@pytest.fixture
def alice(adapter):
    return DeterministicDhNode("alice", 6, adapter)


def test_modexp_abi_and_native_results(adapter):
    assert adapter._modexp.argtypes == [ctypes.c_uint32] * 3 + [ctypes.POINTER(ctypes.c_uint32)]
    assert adapter._modexp.restype is ctypes.c_int
    for args in [(5, 6, 23), (19, 6, 23), (0, 0, 1), (0, 0, 23),
                 (UINT32_MAX, UINT32_MAX, 4294967291)]:
        assert adapter.modexp(*args) == pow(*args)
    with pytest.raises(CryptoCoreCallError, match="większy od 0") as error:
        adapter.modexp(5, 6, 0)
    assert error.value.code == "INVALID_MODULUS"


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("value", [-1, 2**32, True, False, 1.0, "1", None, [], {}])
def test_modexp_rejects_types_before_c(adapter, monkeypatch, index, value):
    def unexpected(*args):
        pytest.fail("Błędne dane dotarły do C")
    monkeypatch.setattr(adapter, "_modexp", unexpected)
    args = [5, 6, 23]
    args[index] = value
    with pytest.raises(CryptoCoreInputError):
        adapter.modexp(*args)


@pytest.mark.parametrize("status", [1, 3, 4, 5, 6, 7, -1, 99])
def test_modexp_status_mapping(adapter, monkeypatch, status):
    monkeypatch.setattr(adapter, "_modexp", lambda *args: status)
    with pytest.raises(CryptoCoreCallError) as error:
        adapter.modexp(5, 6, 23)
    assert error.value.code == "INTERNAL_ERROR"
    assert error.value.status == status


def test_independent_reference_and_no_exchange_call(alice, adapter, monkeypatch):
    def unexpected(*args):
        pytest.fail("Węzeł nie może wywoływać centralnej wymiany")
    monkeypatch.setattr(adapter, "_exchange", unexpected)
    bob = DeterministicDhNode("bob", 15, adapter)
    assert alice.start_session("ref", 23, 5).public_value == 8
    assert bob.state.phase == "idle"
    assert bob.start_session("ref", 23, 5).public_value == 19
    alice.receive_public("ref", 19)
    assert bob.state.phase == "public_ready"
    bob.receive_public("ref", 8)
    assert alice.diagnostics()["shared_secret"] == bob.diagnostics()["shared_secret"] == 2


@pytest.mark.parametrize("p", [0, 1, 4, 9, 561, 3215031751, 65521**2, UINT32_MAX,
                               -1, 2**32, True, 23.0, "23", None])
def test_invalid_prime_preserves_state(alice, p):
    alice.start_session("old", 23, 5)
    alice.receive_public("old", 19)
    before = alice.state, alice.diagnostics()
    with pytest.raises(NodeError):
        alice.start_session("new", p, 5)
    assert (alice.state, alice.diagnostics()) == before


@pytest.mark.parametrize("g", [0, 1, 23, 24, -1, 2**32, True, 5.0, "5", None])
def test_invalid_generator(alice, g):
    with pytest.raises(NodeError, match="."):
        alice.start_session("ref", 23, g)
    assert alice.state.phase == "idle"


@pytest.mark.parametrize("secret", [0, -1, 2**32, True, 6.0, "6", None])
def test_invalid_test_secret(adapter, secret):
    with pytest.raises(NodeError):
        DeterministicDhNode("alice", secret, adapter)


@pytest.mark.parametrize("p,g,secret", [(3, 2, 1), (23, 2, 22), (4294967291, 2, UINT32_MAX)])
def test_valid_boundaries(adapter, p, g, secret):
    node = DeterministicDhNode("alice", secret, adapter)
    assert node.start_session("ref", p, g).public_value == pow(g, secret, p)
    node.receive_public("ref", 1)
    assert node.diagnostics()["shared_secret"] == 1


def test_prime_two_has_no_generator(alice):
    with pytest.raises(NodeError) as error:
        alice.start_session("ref", 2, 2)
    assert error.value.code == "INVALID_GENERATOR"


@pytest.mark.parametrize("value", [0, 23, 24, -1, 2**32, True, False, 19.0, "19", None])
def test_invalid_received_value_preserves_result(alice, value):
    alice.start_session("ref", 23, 5)
    alice.receive_public("ref", 19)
    before = alice.state, alice.diagnostics()
    with pytest.raises(NodeError):
        alice.receive_public("ref", value)
    assert (alice.state, alice.diagnostics()) == before


def test_session_order_duplicates_and_conflicts(alice):
    with pytest.raises(NodeError) as error:
        alice.receive_public("ref", 19)
    assert error.value.code == "NOT_INITIALIZED"
    alice.start_session("ref", 23, 5)
    with pytest.raises(NodeError) as error:
        alice.start_session("ref", 23, 5)
    assert error.value.code == "SESSION_ALREADY_STARTED"
    with pytest.raises(NodeError) as error:
        alice.receive_public("wrong", 19)
    assert error.value.code == "SESSION_MISMATCH"
    state = alice.receive_public("ref", 19)
    assert alice.receive_public("ref", 19) == state
    with pytest.raises(NodeError) as error:
        alice.receive_public("ref", 8)
    assert error.value.code == "PUBLIC_VALUE_CONFLICT"
    assert alice.state == state


@pytest.mark.parametrize("session_id", [None, True, 1, "", " ", "x" * 129])
def test_invalid_session_id(alice, session_id):
    with pytest.raises(NodeError):
        alice.start_session(session_id, 23, 5)
    assert alice.state.phase == "idle"


def test_reset_generates_fresh_local_secret_and_clears_key(adapter, monkeypatch):
    values = iter([5, 14, UINT32_MAX - 1, 0])
    def randbelow(bound):
        assert bound == UINT32_MAX
        return next(values)
    monkeypatch.setattr("nodes.node.secrets.randbelow", randbelow)
    node = DhNode("alice", adapter)
    assert node.start_session("one", 23, 5).public_value == 8
    node.receive_public("one", 19)
    assert node.diagnostics()["shared_secret"] == 2
    assert node.start_session("two", 23, 5).public_value == 19
    assert node.state.received_public is None
    with pytest.raises(NodeError):
        node.diagnostics()
    assert node.start_session("three", 23, 5).public_value == pow(5, UINT32_MAX, 23)
    assert node.start_session("four", 23, 5).public_value == 5


def test_c_failure_preserves_state_and_allows_retry(alice, adapter, monkeypatch):
    alice.start_session("old", 23, 5)
    original = adapter._modexp
    monkeypatch.setattr(adapter, "_modexp", lambda *args: 1)
    before = alice.state
    with pytest.raises(CryptoCoreCallError):
        alice.receive_public("old", 19)
    assert alice.state == before
    monkeypatch.setattr(adapter, "_modexp", original)
    alice.receive_public("old", 19)
    before = alice.state, alice.diagnostics()
    monkeypatch.setattr(adapter, "_modexp", lambda *args: 99)
    with pytest.raises(CryptoCoreCallError):
        alice.start_session("new", 23, 5)
    assert (alice.state, alice.diagnostics()) == before


def test_standard_protocol_contains_only_public_state(alice):
    request = {"op": "start", "session_id": "ref", "p": 23, "g": 5}
    for field in ("secret", "alice_secret", "bob_secret", "test_secret"):
        with pytest.raises(NodeError):
            dispatch(alice, {**request, field: 6})
    result = dispatch(alice, request)
    assert set(result) == {"state", "pid"}
    assert set(result["state"]) == {"participant", "session_id", "phase", "p", "g",
                                   "public_value", "received_public"}
    dispatch(alice, {"op": "receive", "session_id": "ref", "public_value": 19})
    assert "secret" not in json.dumps(dispatch(alice, {"op": "state"}))
    with pytest.raises(NodeError):
        dispatch(alice, {"op": "diagnostics"})
    assert dispatch(alice, {"op": "diagnostics"}, True)["diagnostics"]["shared_secret"] == 2
    assert "_secret" not in repr(alice)


def test_cli_survives_c_failure_without_leaking_details(alice, adapter, monkeypatch, capsys):
    from nodes.__main__ import main

    alice.start_session("ref", 23, 5)
    monkeypatch.delenv("RADH_NODE_TEST_SECRET", raising=False)
    monkeypatch.setattr("nodes.__main__.DhNode", lambda role: alice)
    monkeypatch.setattr(adapter, "_modexp", lambda *args: 99)
    monkeypatch.setattr(sys, "argv", ["nodes", "--role", "alice"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        '{"op":"receive","session_id":"ref","public_value":19}\n'
        '{"op":"state"}\n'
    ))
    assert main() == 0
    output = capsys.readouterr()
    error, state = map(json.loads, output.out.splitlines())
    assert error["error"]["code"] == "CRYPTO_CORE_ERROR"
    assert state["state"]["phase"] == "public_ready"
    assert "99" not in output.out
    assert output.err == ""


class AgentProcess:
    """Czytanie przez wątek zapewnia limit czasu także dla potoków Windows."""

    def __init__(self, role, secret, library, diagnostics=True):
        env = dict(os.environ, RADH_CRYPTO_CORE_LIBRARY=str(library))
        env.pop("RADH_NODE_TEST_SECRET", None)
        args = [sys.executable, "-m", "nodes", "--role", role]
        if secret is not None:
            env["RADH_NODE_TEST_SECRET"] = str(secret)
            args.append("--test-mode")
        if diagnostics:
            args.append("--allow-diagnostics")
        self.process = subprocess.Popen(args, cwd=Path(__file__).resolve().parents[1],
                                        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)

    def send(self, request):
        self.process.stdin.write(request + "\n")
        self.process.stdin.flush()
        return json.loads(self.lines.get(timeout=10))

    def call(self, **request):
        return self.send(json.dumps(request))

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.reader.join(timeout=5)
        stderr = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        assert self.process.returncode == 0, stderr
        assert stderr == ""


def test_subprocess_reference_exchange_and_restart(core):
    agents = []
    try:
        alice = AgentProcess("alice", 6, core.path)
        agents.append(alice)
        bob = AgentProcess("bob", 15, core.path)
        agents.append(bob)
        a = alice.call(op="start", session_id="ref", p=23, g=5)
        b = bob.call(op="start", session_id="ref", p=23, g=5)
        assert a["pid"] == alice.process.pid
        assert b["pid"] == bob.process.pid
        assert len({a["pid"], b["pid"], os.getpid()}) == 3
        assert a["state"]["public_value"] == 8
        assert b["state"]["public_value"] == 19
        for agent, public in [(alice, 19), (bob, 8)]:
            response = agent.call(op="receive", session_id="ref", public_value=public)
            assert response["state"]["phase"] == "complete"
            assert "secret" not in json.dumps(response)
            assert agent.call(op="diagnostics")["diagnostics"]["shared_secret"] == 2
        # Uszkodzone polecenia nie kończą procesu ani nie zmieniają poprawnego wyniku.
        for request in ['{', '[]', '{"op":[]}',
                        '{"op":"receive","session_id":"ref","public_value":0}',
                        '{"op":"start","session_id":"ref","p":23,"g":5}',
                        '{"op":"state","secret":987654321}']:
            error = alice.send(request)
            assert set(error) == {"error"}
            assert "987654321" not in json.dumps(error)
            assert alice.call(op="diagnostics")["diagnostics"]["shared_secret"] == 2
        alice.close()
        agents.remove(alice)
        restarted = AgentProcess("alice", None, core.path, diagnostics=False)
        agents.append(restarted)
        assert restarted.call(op="state")["state"]["phase"] == "idle"
        assert restarted.call(op="diagnostics")["error"]["code"] == "DIAGNOSTICS_DISABLED"
        assert bob.call(op="state")["state"]["phase"] == "complete"
    finally:
        for agent in agents:
            agent.close()
