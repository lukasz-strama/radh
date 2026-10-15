import json
from pathlib import Path
import pytest
from native_core import NativeCore, find_library

DATA_PATH = Path(__file__).parent / "data" / "rsa_cases.json"

with open(DATA_PATH, encoding="utf-8") as _file:
    CASES = json.load(_file)


def case_ids(cases):
    """Nazwy przypadków w raporcie pytest."""
    return [case["id"] for case in cases]


API_URL = "/api/v1/rsa/demo/encrypt"


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
