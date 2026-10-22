"""Testy integracji DH z rzeczywistą biblioteką C i kontraktu HTTP."""

import ctypes
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.api import get_crypto_core
from app.crypto_core import CryptoCore, CryptoCoreInputError, CryptoCoreLoadError

URL = "/api/v1/dh/demo/exchange"
BASE = {"prime": 23, "generator": 5, "alice_secret": 6, "bob_secret": 15}
EXPECTED = {"alice_public": 8, "bob_public": 19, "alice_shared_key": 2, "bob_shared_key": 2}


def test_known_exchange(client):
    response = client.post(URL, json=BASE)
    assert response.status_code == 200
    assert response.json() == EXPECTED


@pytest.mark.parametrize("p,g,a,b", [
    (3, 2, 1, 1), (23, 4, 22, 44), (23, 5, 2**32 - 1, 2**32 - 1),
    (4294967291, 4294967290, 2**32 - 1, 2**32 - 1),
])
def test_boundaries_match_reference(client, p, g, a, b):
    response = client.post(URL, json=dict(zip(BASE, (p, g, a, b))))
    assert response.status_code == 200
    assert response.json() == {
        "alice_public": pow(g, a, p), "bob_public": pow(g, b, p),
        "alice_shared_key": pow(pow(g, b, p), a, p),
        "bob_shared_key": pow(pow(g, a, p), b, p),
    }


@pytest.mark.parametrize("patch,code", [
    ({"prime": 0}, "INVALID_PRIME"), ({"prime": 1}, "INVALID_PRIME"),
    ({"prime": 25}, "INVALID_PRIME"), ({"prime": 561}, "INVALID_PRIME"),
    ({"prime": 2}, "INVALID_GENERATOR"),
    ({"generator": 0}, "INVALID_GENERATOR"), ({"generator": 1}, "INVALID_GENERATOR"),
    ({"generator": 23}, "INVALID_GENERATOR"),
    ({"alice_secret": 0}, "INVALID_SECRET"), ({"bob_secret": 0}, "INVALID_SECRET"),
    ({"prime": 4, "generator": 0, "alice_secret": 0}, "INVALID_PRIME"),
])
def test_mathematical_validation(client, patch, code):
    response = client.post(URL, json={**BASE, **patch})
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == code
    assert isinstance(response.json()["error"]["message"], str)


@pytest.mark.parametrize("field", BASE)
@pytest.mark.parametrize("value", [-1, 2**32, True, False, "5", 5.0, None, [], {}])
def test_strict_uint32_validation(client, field, value):
    response = client.post(URL, json={**BASE, field: value})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("field", BASE)
def test_missing_field(client, field):
    response = client.post(URL, json={k: v for k, v in BASE.items() if k != field})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_extra_field(client):
    response = client.post(URL, json={**BASE, "extra": 1})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("status", [1, -1, 99])
def test_unexpected_native_status(client, monkeypatch, status):
    monkeypatch.setattr(get_crypto_core(), "_exchange", lambda *args: status)
    response = client.post(URL, json=BASE)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"


def test_missing_library(client, monkeypatch, tmp_path):
    monkeypatch.setenv("RADH_CRYPTO_CORE_LIBRARY", str(tmp_path / "missing.so"))
    get_crypto_core.cache_clear()
    response = client.post(URL, json=BASE)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CRYPTO_CORE_UNAVAILABLE"
    assert str(tmp_path) not in response.text


def test_library_without_dh_symbol(core, monkeypatch):
    class OldLibrary:
        def radh_rsa_encrypt_u32(self):
            pass

    # Funkcja jako atrybut instancji pozwala przypisać sygnaturę ctypes.
    old = OldLibrary()
    old.radh_rsa_encrypt_u32 = lambda: None
    monkeypatch.setattr(ctypes, "CDLL", lambda path: old)
    with pytest.raises(CryptoCoreLoadError, match="radh_dh_exchange_u32"):
        CryptoCore(core.path)


@pytest.mark.parametrize("field", BASE)
@pytest.mark.parametrize("value", [-1, 2**32, True, "5", 1.5, None])
def test_adapter_rejects_invalid_arguments_before_c(core, field, value):
    adapter = CryptoCore(core.path)
    def unexpected_call(*args):
        pytest.fail("Niepoprawne dane nie mogą dotrzeć do C")
    adapter._exchange = unexpected_call
    with pytest.raises(CryptoCoreInputError):
        adapter.exchange(**{**BASE, field: value})


def test_native_call_is_used(client, monkeypatch):
    instance = get_crypto_core()
    native = instance._exchange
    calls = []
    def tracked_call(*args):
        calls.append(tuple(arg.value for arg in args[:4]))
        return native(*args)
    monkeypatch.setattr(instance, "_exchange", tracked_call)
    assert client.post(URL, json=BASE).json() == EXPECTED
    assert calls == [(23, 5, 6, 15)]


def test_parallel_exchanges(client):
    def request(secret):
        response = client.post(URL, json={**BASE, "alice_secret": secret})
        assert response.status_code == 200
        assert response.json() == {
            "alice_public": pow(5, secret, 23), "bob_public": 19,
            "alice_shared_key": pow(19, secret, 23),
            "bob_shared_key": pow(pow(5, secret, 23), 15, 23),
        }
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(request, range(1, 41)))


def test_swagger_and_openapi(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    operation = schema["paths"][URL]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/DhExchangeRequest")
    for status in ("422", "500", "503"):
        assert operation["responses"][status]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
    assert schema["components"]["schemas"]["DhExchangeRequest"]["examples"] == [BASE]
    assert schema["components"]["schemas"]["DhExchangeResponse"]["examples"] == [EXPECTED]
