import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from native_core import NativeCore, find_library

DATA_PATH = Path(__file__).parent / "data" / "rsa_cases.json"
DH_DATA_PATH = Path(__file__).parent / "data" / "dh_cases.json" 

with open(DATA_PATH, encoding="utf-8") as _file:
    CASES = json.load(_file)

with open(DH_DATA_PATH, encoding="utf-8") as _file:
    DH_CASES = json.load(_file)


def case_ids(cases):
    """Nazwy przypadków w raporcie pytest."""
    return [case["id"] for case in cases]


API_URL = "/api/v1/rsa/demo/encrypt"
DH_API_URL = "/api/v1/dh/demo/exchange"


@pytest.fixture(scope="session")
def core():
    try:
        path = find_library()
    except FileNotFoundError as error:
        pytest.fail(str(error), pytrace=False)
    return NativeCore(path)


@pytest.fixture
def client(core, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import get_crypto_core
    from app.crypto_core import LIBRARY_ENV_VAR
    from app.main import app

    monkeypatch.setenv(LIBRARY_ENV_VAR, str(core.path))
    get_crypto_core.cache_clear()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    get_crypto_core.cache_clear()


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(core, tmp_path):
    """Prawdziwy serwer uvicorn w osobnym procesie (jak przy uruchomieniu API ręcznie)."""
    port = _free_port()
    log_path = tmp_path / "uvicorn.log"
    env = dict(os.environ, RADH_CRYPTO_CORE_LIBRARY=str(core.path))
    with open(log_path, "wb") as log:
        process = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "app.main:app",
                "--app-dir", str(BACKEND_DIR),
                "--host", "127.0.0.1", "--port", str(port),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.time() + 20
            while True:
                if process.poll() is not None:
                    pytest.fail("Serwer zakończył pracę przy starcie:\n" + log_path.read_text(errors="replace"))
                try:
                    if httpx.get(base_url + "/openapi.json", timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if time.time() > deadline:
                    pytest.fail("Serwer nie wystartował w 20 s:\n" + log_path.read_text(errors="replace"))
                time.sleep(0.1)
            yield process, base_url, port
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
