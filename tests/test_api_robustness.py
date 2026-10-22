import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

import reference
from conftest import API_URL, CASES

BASE = {"message": 65, "public_exponent": 17, "modulus": 3233}
EXPECTED_CIPHERTEXT = 2790
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"


def assert_server_still_works(client):
    """Po każdej serii błędów poprawne żądanie nadal musi się udać."""
    response = client.post(API_URL, json=BASE)
    assert response.status_code == 200
    assert response.json() == {"ciphertext": EXPECTED_CIPHERTEXT}


def test_server_survives_series_of_invalid_requests(client):
    invalid_bodies = [case for case in CASES["invalid"]]
    for round_number in range(10):
        for case in invalid_bodies:
            body = {
                "message": case["message"],
                "public_exponent": case["public_exponent"],
                "modulus": case["modulus"],
            }
            assert client.post(API_URL, json=body).status_code == 422
        for raw in (b"{", b"", b"\xff\xfe", b"[]", b"null"):
            response = client.post(
                API_URL, content=raw, headers={"content-type": "application/json"}
            )
            assert 400 <= response.status_code < 500
        assert_server_still_works(client)


# Nietypowe żądania. Każde ma zakończyć się odpowiedzią 4xx, nigdy 5xx.
WEIRD_REQUESTS = [
    pytest.param("POST", API_URL, {"content": b"9" * 5000}, id="body_5000_digits"),
    pytest.param(
        "POST",
        API_URL,
        {
            "content": b'{"message":' + b"9" * 5000 + b',"public_exponent":17,"modulus":3233}',
            "headers": {"content-type": "application/json"},
        },
        id="huge_integer_literal",
    ),
    pytest.param(
        "POST",
        API_URL,
        {"content": b"\xff\xfe\x00", "headers": {"content-type": "application/json"}},
        id="invalid_utf8",
    ),
    pytest.param("GET", API_URL, {}, id="get_instead_of_post"),
    pytest.param("PUT", API_URL, {"json": BASE}, id="put_instead_of_post"),
    pytest.param("DELETE", API_URL, {}, id="delete_method"),
    pytest.param("POST", "/api/v1/rsa/nie-istnieje", {"json": BASE}, id="unknown_path"),
    pytest.param("GET", "/", {}, id="root_path"),
]


@pytest.mark.parametrize("method,url,kwargs", WEIRD_REQUESTS)
def test_unusual_requests_get_4xx_and_server_keeps_working(client, method, url, kwargs):
    response = client.request(method, url, **kwargs)
    assert 400 <= response.status_code < 500
    assert_server_still_works(client)

@pytest.mark.xfail(strict=True, reason="DEFEKT: błędy frameworka mają inny format niż ErrorResponse")
@pytest.mark.parametrize(
    "method,url,kwargs",
    [
        pytest.param("GET", API_URL, {}, id="405_method_not_allowed"),
        pytest.param("GET", "/nie-istnieje", {}, id="404_not_found"),
        pytest.param(
            "POST",
            API_URL,
            {
                "content": b'{"message":' + b"9" * 5000 + b',"public_exponent":17,"modulus":3233}',
                "headers": {"content-type": "application/json"},
            },
            id="400_huge_integer_literal",
        ),
    ],
)
def test_framework_errors_use_common_error_format(client, method, url, kwargs):
    body = client.request(method, url, **kwargs).json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}


def test_library_unavailable_returns_503_and_recovers(client, core, monkeypatch):
    from app.api import get_crypto_core
    from app.crypto_core import LIBRARY_ENV_VAR

    missing = str(Path(core.path).with_name("nie_istnieje.so"))
    monkeypatch.setenv(LIBRARY_ENV_VAR, missing)
    get_crypto_core.cache_clear()

    response = client.post(API_URL, json=BASE)
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "CRYPTO_CORE_UNAVAILABLE"
    # Odpowiedź nie może ujawniać ścieżek z serwera.
    assert missing not in response.text

    # Po przywróceniu biblioteki serwer wraca do normalnej pracy bez restartu.
    monkeypatch.setenv(LIBRARY_ENV_VAR, str(core.path))
    get_crypto_core.cache_clear()
    assert_server_still_works(client)


def test_library_env_var_points_to_corrupted_file_returns_503(client, tmp_path, monkeypatch):
    from app.api import get_crypto_core
    from app.crypto_core import LIBRARY_ENV_VAR

    fake = tmp_path / "libradh_crypto_core.so"
    fake.write_bytes(b"to nie jest biblioteka wspolna")
    monkeypatch.setenv(LIBRARY_ENV_VAR, str(fake))
    get_crypto_core.cache_clear()

    response = client.post(API_URL, json=BASE)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CRYPTO_CORE_UNAVAILABLE"
    assert str(fake) not in response.text


@pytest.mark.parametrize("returned_status", [1, 99, -1])
def test_unexpected_c_status_returns_controlled_500(client, monkeypatch, returned_status):
    """Gdyby biblioteka zwróciła status spoza kontraktu, API zwraca 500 bez szczegółów."""
    from app.api import get_crypto_core

    instance = get_crypto_core()
    monkeypatch.setattr(instance, "_encrypt", lambda *args: returned_status)

    response = client.post(API_URL, json=BASE)
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "Traceback" not in response.text


def test_parallel_requests_return_correct_results(client):
    """Wiele równoległych żądań (poprawnych i błędnych) nie myli wyników."""

    def worker(index):
        if index % 3 == 0:
            r = client.post(API_URL, json={**BASE, "modulus": 0})
            return r.status_code == 422
        r = client.post(API_URL, json=BASE)
        return r.status_code == 200 and r.json() == {"ciphertext": EXPECTED_CIPHERTEXT}

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(200)))
    assert all(results)


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


@pytest.mark.live
def test_live_server_survives_invalid_and_garbage_requests(live_server):
    process, base_url, port = live_server
    url = base_url + API_URL

    for case in CASES["invalid"]:
        body = {k: case[k] for k in ("message", "public_exponent", "modulus")}
        assert httpx.post(url, json=body, timeout=5).status_code == 422
    assert httpx.post(url, content=b"{zly json", headers={"content-type": "application/json"}, timeout=5).status_code == 422

    # Surowe, niepoprawne dane HTTP wysłane przez gniazdo TCP.
    for garbage in (b"GARBAGE\r\n\r\n", b"\x00\x01\x02\x03\r\n\r\n", b"POST " + b"A" * 100_000 + b" HTTP/1.1\r\n\r\n"):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            try:
                sock.sendall(garbage)
                sock.recv(4096)
            except OSError:
                pass

    assert process.poll() is None, "Proces serwera zakończył się po błędnych żądaniach"
    response = httpx.post(url, json=BASE, timeout=5)
    assert response.status_code == 200
    assert response.json() == {"ciphertext": EXPECTED_CIPHERTEXT}


@pytest.mark.live
def test_live_server_matches_reference_for_valid_requests(live_server):
    _process, base_url, _port = live_server
    for case in CASES["valid"]:
        body = {k: case[k] for k in ("message", "public_exponent", "modulus")}
        response = httpx.post(base_url + API_URL, json=body, timeout=5)
        assert response.status_code == 200
        assert response.json()["ciphertext"] == reference.rsa_encrypt(**body)


@pytest.mark.live
def test_live_dh_exchange_and_validation(live_server):
    """Wymiana DH przez prawdziwy serwer oraz RSA po błędnym żądaniu DH."""
    _process, base_url, _port = live_server
    url = base_url + "/api/v1/dh/demo/exchange"
    data = {"prime": 23, "generator": 5, "alice_secret": 6, "bob_secret": 15}
    response = httpx.post(url, json=data, timeout=5)
    assert response.status_code == 200
    assert response.json() == {
        "alice_public": 8, "bob_public": 19, "alice_shared_key": 2, "bob_shared_key": 2,
    }
    response = httpx.post(url, json={**data, "prime": 25}, timeout=5)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PRIME"
    assert httpx.get(base_url + "/docs", timeout=5).status_code == 200
    response = httpx.post(base_url + API_URL, json=BASE, timeout=5)
    assert response.status_code == 200
    assert response.json() == {"ciphertext": EXPECTED_CIPHERTEXT}
