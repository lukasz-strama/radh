"""Testy jednostkowe backendu bez serwera i bez zbudowanej biblioteki C."""

import asyncio
import ctypes
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from app.crypto_core import (
    CryptoCore, CryptoCoreCallError, CryptoCoreInputError, CryptoCoreLoadError,
)
from app.models import DhExchangeRequest, DhExchangeResponse
from app.main import http_error, crypto_core_call_error

BASE = {"prime": 23, "generator": 5, "alice_secret": 6, "bob_secret": 15}


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    def encrypt(*args):
        return 0
    def exchange(*args):
        return 0
    library = SimpleNamespace(radh_rsa_encrypt_u32=encrypt, radh_dh_exchange_u32=exchange)
    monkeypatch.setattr(ctypes, "CDLL", lambda path: library)
    return CryptoCore(tmp_path / "fake-library")


@pytest.mark.parametrize("field", BASE)
@pytest.mark.parametrize("value", [-1, 2**32, True, False, "5", 5.0, None, [], {}])
def test_adapter_rejects_arguments_before_call(adapter, field, value):
    def unexpected(*args):
        pytest.fail("Niepoprawny argument dotarł do ABI")
    adapter._exchange = unexpected
    with pytest.raises(CryptoCoreInputError):
        adapter.exchange(**{**BASE, field: value})


def test_adapter_passes_uint32_and_reads_all_native_fields(adapter):
    def exchange(*args):
        assert [arg.value for arg in args[:4]] == [23, 5, 2**32 - 1, 15]
        assert all(type(arg) is ctypes.c_uint32 for arg in args[:4])
        # Cztery różne wartości wykrywają zamianę lub kopiowanie pól wyniku.
        result = ctypes.cast(args[4], adapter._exchange.argtypes[-1]).contents
        result.alice_public, result.bob_public = 7, 11
        result.alice_shared_key, result.bob_shared_key = 13, 17
        return 0
    exchange.argtypes = adapter._exchange.argtypes
    adapter._exchange = exchange
    result = adapter.exchange(**{**BASE, "alice_secret": 2**32 - 1})
    assert (result.alice_public, result.bob_public,
            result.alice_shared_key, result.bob_shared_key) == (7, 11, 13, 17)


@pytest.mark.parametrize("symbol", ["radh_rsa_encrypt_u32", "radh_dh_exchange_u32"])
def test_missing_symbol_is_load_error(monkeypatch, tmp_path, symbol):
    library = SimpleNamespace(radh_rsa_encrypt_u32=lambda: 0, radh_dh_exchange_u32=lambda: 0)
    delattr(library, symbol)
    monkeypatch.setattr(ctypes, "CDLL", lambda path: library)
    with pytest.raises(CryptoCoreLoadError, match=symbol):
        CryptoCore(tmp_path / "old-library")


@pytest.mark.parametrize("operation,status,code,http_status", [
    ("exchange", 5, "INVALID_PRIME", 422),
    ("exchange", 6, "INVALID_GENERATOR", 422),
    ("exchange", 7, "INVALID_SECRET", 422),
    *[("exchange", s, "INTERNAL_ERROR", 500) for s in (1, 2, 3, 4, -1, 99)],
    ("encrypt", 2, "INVALID_MODULUS", 422),
    ("encrypt", 3, "INVALID_EXPONENT", 422),
    ("encrypt", 4, "MESSAGE_OUT_OF_RANGE", 422),
    *[("encrypt", s, "INTERNAL_ERROR", 500) for s in (1, 5, 6, 7, -1, 99)],
])
def test_status_mapping_is_specific_to_operation(adapter, operation, status, code, http_status):
    setattr(adapter, "_" + operation, lambda *args: status)
    args = BASE.values() if operation == "exchange" else (65, 17, 3233)
    with pytest.raises(CryptoCoreCallError) as caught:
        getattr(adapter, operation)(*args)
    assert caught.value.status == status
    assert caught.value.code == code
    response = asyncio.run(crypto_core_call_error(None, caught.value))
    assert response.status_code == http_status
    assert json.loads(response.body)["error"]["code"] == code


@pytest.mark.parametrize("field", BASE)
@pytest.mark.parametrize("value", [-1, 2**32, True, "5", 5.0, None])
def test_request_model_rejects_invalid_uint32(field, value):
    with pytest.raises(ValidationError):
        DhExchangeRequest(**{**BASE, field: value})


@pytest.mark.parametrize("field", BASE)
def test_request_model_requires_fields(field):
    with pytest.raises(ValidationError):
        DhExchangeRequest(**{k: v for k, v in BASE.items() if k != field})


def test_models_preserve_contract():
    assert DhExchangeRequest(**BASE).model_dump() == BASE
    with pytest.raises(ValidationError):
        DhExchangeRequest(**BASE, extra=1)
    values = dict(alice_public=8, bob_public=19, alice_shared_key=2, bob_shared_key=2)
    assert DhExchangeResponse(**values).model_dump() == values


@pytest.mark.parametrize("status,code,headers", [
    (400, "BAD_REQUEST", None), (404, "NOT_FOUND", None),
    (405, "METHOD_NOT_ALLOWED", {"Allow": "POST"}),
    (429, "HTTP_429", {"Retry-After": "30"}),
])
def test_http_handler_preserves_status_headers_and_hides_details(status, code, headers):
    response = asyncio.run(http_error(None, HTTPException(status, "private detail", headers)))
    assert response.status_code == status
    body = json.loads(response.body)
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert b"private detail" not in response.body
    for name, value in (headers or {}).items():
        assert response.headers[name] == value
