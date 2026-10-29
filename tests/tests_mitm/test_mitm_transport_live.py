"""Integracja transportu #41 z rzeczywistym procesem Mallory z #40."""

import importlib.util
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest


@pytest.mark.live
@pytest.mark.parametrize("diagnostics", [False, True])
def test_three_processes_normal_mitm_normal(live_server, core, tmp_path, diagnostics):
    if importlib.util.find_spec("nodes.mallory") is None:
        pytest.skip("Integracja wymaga #40 (PR #49); backend i jego testy działają niezależnie.")
    _, url, _ = live_server
    
    # Przejście do głównego katalogu repozytorium (root)
    root = Path(__file__).resolve().parents[2]
    processes = {}

    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    with ExitStack() as stack, httpx.Client(base_url=url, timeout=2) as client:
        for role in ("alice", "bob", "mallory"):
            env = dict(os.environ, RADH_CRYPTO_CORE_LIBRARY=str(core.path))
            
            # Ustawienie PYTHONPATH, aby subprocesy widziały pakiety 'backend' oraz 'nodes'
            current_pythonpath = env.get("PYTHONPATH", "")
            backend_dir = str(root / "backend")
            paths_to_add = [str(root), backend_dir]
            if current_pythonpath:
                paths_to_add.append(current_pythonpath)
            env["PYTHONPATH"] = os.pathsep.join(paths_to_add)

            for key in ("RADH_NODE_TEST_SECRET", "RADH_MALLORY_TEST_X", "RADH_MALLORY_TEST_Y"):
                env.pop(key, None)
            if role == "mallory":
                env.update(RADH_MALLORY_TEST_X="7", RADH_MALLORY_TEST_Y="11")
            else:
                env["RADH_NODE_TEST_SECRET"] = "6" if role == "alice" else "15"
                
            log = stack.enter_context((tmp_path / f"{role}.log").open("w"))
            command = [sys.executable, "-m", "backend.dh_transport", "--role", role,
                       "--url", url, "--test-mode"]
            if diagnostics:
                command.append("--allow-diagnostics")
            
            process = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log)
            stack.callback(stop, process)
            processes[role] = process
        
        assert len({p.pid for p in processes.values()}) == 3

        def wait_for(read, predicate):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                result = read()
                if predicate(result):
                    return result
                for role, process in processes.items():
                    if process.poll() is not None:
                        pytest.fail(f"Proces {role} zakończył pracę: " + (tmp_path / f"{role}.log").read_text())
                time.sleep(0.1)
            pytest.fail(f"Nie osiągnięto oczekiwanego stanu; ostatnia odpowiedź: {result}")

        wait_for(lambda: client.get("/api/v1/dh/nodes").json(),
                 lambda nodes: all(n["online"] for n in nodes.values()))
        for index, mode in enumerate(("normal", "mitm", "normal")):
            if index == 2:
                stop(processes.pop("mallory"))
            created = client.post("/api/v1/dh/sessions", json={"prime": 23, "generator": 5, "mode": mode})
            assert created.status_code == 201
            path = "/api/v1/dh/sessions/" + created.json()["session_id"]
            assert client.post(path + "/start").status_code == 200
            session = wait_for(lambda: client.get(path).json(), lambda s: s["status"] == "completed")
            delivered = {m["recipient"]: m["public_value"] for m in session["messages"]}
            assert delivered == ({"alice": 17, "bob": 22} if mode == "mitm" else {"alice": 19, "bob": 8})
            assert len(session["events"]) == (9 if mode == "mitm" else 7)
            assert "shared_" not in str(session)
            if mode == "mitm":
                assert {i["original_sender"]: i["original_value"] for i in session["interceptions"]} == {"alice": 8, "bob": 19}
            else:
                assert session["interceptions"] == []
            if diagnostics:
                expected = {"alice": 12, "bob": 22} if mode == "mitm" else {"alice": 2, "bob": 2}
                wait_for(lambda: client.get(path + "/diagnostics").json(), lambda d: d == expected)
                if mode == "mitm":
                    wait_for(lambda: client.get(path + "/diagnostics/mallory").json(),
                             lambda d: d == {"shared_with_alice": 12, "shared_with_bob": 22})
            else:
                assert client.get(path + "/diagnostics").json() == {"alice": None, "bob": None}
                assert client.get(path + "/diagnostics/mallory").json() == {"shared_with_alice": None, "shared_with_bob": None}
