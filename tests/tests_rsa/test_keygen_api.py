"""Testy endpointu POST /api/v1/rsa/demo/keygen (#56, #58).

Kontrakt: backend/README.md. Testy działają na prawdziwej bibliotece C
(fixture `client` z conftest.py). Pomijane (SKIPPED) są, gdy:
- backend nie ma jeszcze trasy keygen (#56 niezmergowane),
- biblioteka C nie eksportuje radh_rsa_keygen_u32 (#55 niezmergowane).
"""

import json

import pytest

from conftest import API_URL, CASES, case_ids
from native_core import KEYGEN_SYMBOL

KEYGEN_URL = "/api/v1/rsa/demo/keygen"
VALID = CASES["keygen_valid"]
INVALID = CASES["keygen_invalid"]
BASE = {"p": 61, "q": 53, "e": 17}


def assert_controlled_error(response, status_code, code):
    """Błąd ma stały kształt {"error": {"code": ..., "message": ...}}."""
    assert response.status_code == status_code, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def _has_route(client):
    return KEYGEN_URL in client.get("/openapi.json").json()["paths"]


@pytest.fixture
def api(client):
    """Klient, gdy backend ma trasę keygen (walidacja JSON nie wymaga C)."""
    if not _has_route(client):
        pytest.skip(f"Backend nie ma trasy {KEYGEN_URL} (#56 niezmergowane)")
    return client


@pytest.fixture
def api_with_c(api, core):
    """Klient, gdy dodatkowo biblioteka C umie generować klucze."""
    if not core.has_keygen:
        pytest.skip(f"Biblioteka CryptoCore nie eksportuje {KEYGEN_SYMBOL} (#55 niezmergowane)")
    return api


# --- Poprawna ścieżka ---------------------------------------------------------

def test_keygen_61_53_17_returns_expected_keys(api_with_c):
    response = api_with_c.post(KEYGEN_URL, json=BASE)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"n": 3233, "e": 17, "d": 2753, "phi": 3120}


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_keygen_valid_cases(api_with_c, case):
    response = api_with_c.post(KEYGEN_URL, json={k: case[k] for k in ("p", "q", "e")})
    assert response.status_code == 200
    assert response.json() == {"n": case["n"], "e": case["e"], "d": case["d"], "phi": case["phi"]}


def test_public_key_from_keygen_works_in_existing_encrypt_endpoint(api_with_c):
    """(n, e) z keygen przekazane do /encrypt: m=65 daje c=2790, a c^d mod n = 65."""
    keys = api_with_c.post(KEYGEN_URL, json=BASE).json()
    response = api_with_c.post(
        API_URL, json={"message": 65, "public_exponent": keys["e"], "modulus": keys["n"]}
    )
    assert response.status_code == 200
    assert response.json() == {"ciphertext": 2790}
    assert pow(2790, keys["d"], keys["n"]) == 65


def test_keygen_response_has_only_contract_fields(api_with_c):
    body = api_with_c.post(KEYGEN_URL, json=BASE).json()
    assert set(body) == {"n", "e", "d", "phi"}
    assert all(type(value) is int for value in body.values())


def test_keygen_is_deterministic(api_with_c):
    responses = {api_with_c.post(KEYGEN_URL, json=BASE).text for _ in range(10)}
    assert len(responses) == 1


# --- Błędy matematyczne z CryptoCore -----------------------------------------

@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_keygen_invalid_parameters_return_422_with_error_code(api_with_c, case):
    response = api_with_c.post(KEYGEN_URL, json={k: case[k] for k in ("p", "q", "e")})
    assert_controlled_error(response, 422, case["code"])


@pytest.mark.parametrize("status", [1, 99], ids=["invalid_pointer", "unknown_status"])
def test_unexpected_c_status_returns_500_internal_error(api_with_c, monkeypatch, status):
    """INVALID_POINTER lub status spoza kontraktu -> 500 INTERNAL_ERROR."""
    from app.api import get_crypto_core

    monkeypatch.setattr(get_crypto_core(), "_keygen", lambda *args: status)
    response = api_with_c.post(KEYGEN_URL, json=BASE)
    assert_controlled_error(response, 500, "INTERNAL_ERROR")


# --- Biblioteka bez funkcji keygen -> 503 -------------------------------------

def test_keygen_returns_503_when_library_has_no_keygen(api, monkeypatch):
    """Stara biblioteka C bez radh_rsa_keygen_u32: 503 CRYPTO_CORE_UNAVAILABLE.

    Symulujemy brak symbolu, więc test działa także po zmergowaniu #55.
    """
    from app.api import get_crypto_core

    monkeypatch.setattr(get_crypto_core(), "_keygen", None)
    response = api.post(KEYGEN_URL, json=BASE)
    assert_controlled_error(response, 503, "CRYPTO_CORE_UNAVAILABLE")


def test_encrypt_still_works_without_keygen_symbol(api, monkeypatch):
    """Regresja: brak keygen nie psuje istniejącego szyfrowania."""
    from app.api import get_crypto_core

    monkeypatch.setattr(get_crypto_core(), "_keygen", None)
    response = api.post(API_URL, json={"message": 65, "public_exponent": 17, "modulus": 3233})
    assert response.status_code == 200
    assert response.json() == {"ciphertext": 2790}


# --- Walidacja JSON (odrzucana przed wywołaniem C) ----------------------------

INVALID_PAYLOADS = [
    pytest.param({**BASE, "p": -61}, id="p_negative"),
    pytest.param({**BASE, "q": -53}, id="q_negative"),
    pytest.param({**BASE, "e": -17}, id="e_negative"),
    pytest.param({**BASE, "p": 2**32}, id="p_above_uint32"),
    pytest.param({**BASE, "q": 2**32}, id="q_above_uint32"),
    pytest.param({**BASE, "e": 2**32}, id="e_above_uint32"),
    pytest.param({**BASE, "p": 2**64}, id="p_above_uint64"),
    pytest.param({**BASE, "p": "61"}, id="p_is_string"),
    pytest.param({**BASE, "q": "abc"}, id="q_is_text"),
    pytest.param({**BASE, "e": 17.0}, id="e_is_float_integral"),
    pytest.param({**BASE, "e": 17.5}, id="e_is_float"),
    pytest.param({**BASE, "p": True}, id="p_is_bool"),
    pytest.param({**BASE, "q": None}, id="q_is_null"),
    pytest.param({**BASE, "p": [61]}, id="p_is_list"),
    pytest.param({**BASE, "p": {"value": 61}}, id="p_is_object"),
    pytest.param({"q": 53, "e": 17}, id="missing_p"),
    pytest.param({"p": 61, "e": 17}, id="missing_q"),
    pytest.param({"p": 61, "q": 53}, id="missing_e"),
    pytest.param({}, id="empty_object"),
    pytest.param({**BASE, "d": 2753}, id="unknown_field"),
    pytest.param([61, 53, 17], id="body_is_list"),
    pytest.param(61, id="body_is_number"),
    pytest.param("text", id="body_is_string"),
]


@pytest.mark.parametrize("body", INVALID_PAYLOADS)
def test_malformed_payload_returns_422_invalid_request(api, body):
    response = api.post(KEYGEN_URL, json=body)
    assert_controlled_error(response, 422, "INVALID_REQUEST")


RAW_BODIES = [
    pytest.param(b"{niepoprawny json", "application/json", id="broken_json"),
    pytest.param(b"", "application/json", id="empty_body"),
    pytest.param(b"NaN", "application/json", id="nan_literal"),
    pytest.param(json.dumps(BASE).encode(), "text/plain", id="valid_json_wrong_content_type"),
    pytest.param(b"p=61&q=53&e=17", "application/x-www-form-urlencoded", id="form_data"),
]


@pytest.mark.parametrize("raw,content_type", RAW_BODIES)
def test_non_json_body_returns_422_invalid_request(api, raw, content_type):
    response = api.post(KEYGEN_URL, content=raw, headers={"content-type": content_type})
    assert_controlled_error(response, 422, "INVALID_REQUEST")


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_wrong_http_method_returns_405(api, method):
    response = getattr(api, method)(KEYGEN_URL)
    assert_controlled_error(response, 405, "METHOD_NOT_ALLOWED")


# --- Dokumentacja OpenAPI / Swagger -------------------------------------------

def test_openapi_documents_keygen_endpoint(api):
    spec = api.get("/openapi.json").json()
    operation = spec["paths"][KEYGEN_URL]["post"]
    assert {"200", "422", "500", "503"} <= set(operation["responses"])
    assert "requestBody" in operation


def test_swagger_ui_is_available(api):
    response = api.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()
