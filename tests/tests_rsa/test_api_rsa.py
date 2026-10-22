
import json
import random

import pytest

import reference
from conftest import API_URL, CASES, case_ids

VALID = CASES["valid"]
INVALID = CASES["invalid"]

# Mapowanie statusu biblioteki C na kod błędu w odpowiedzi API (backend/app/crypto_core.py).
API_ERROR_CODE = {
    "INVALID_MODULUS": "INVALID_MODULUS",
    "INVALID_EXPONENT": "INVALID_EXPONENT",
    "INVALID_MESSAGE": "MESSAGE_OUT_OF_RANGE",
}


def payload(case):
    return {
        "message": case["message"],
        "public_exponent": case["public_exponent"],
        "modulus": case["modulus"],
    }


def assert_controlled_error(response, status_code, code):
    """Błąd ma stały kształt {"error": {"code": ..., "message": ...}}."""
    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_valid_request_returns_ciphertext(client, case):
    response = client.post(API_URL, json=payload(case))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"ciphertext": case["ciphertext"]}


@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_invalid_parameters_return_422_with_error_code(client, case):
    response = client.post(API_URL, json=payload(case))
    assert_controlled_error(response, 422, API_ERROR_CODE[case["status"]])


def test_api_matches_c_library_and_python_reference(client, core):
    """Ten sam wynik z trzech źródeł: API, bezpośrednio z C i z pow() w Pythonie."""
    rng = random.Random(7)
    for _ in range(300):
        modulus = rng.randint(2, reference.UINT32_MAX)
        message = rng.randint(0, modulus - 1)
        exponent = rng.randint(1, reference.UINT32_MAX)

        response = client.post(
            API_URL,
            json={"message": message, "public_exponent": exponent, "modulus": modulus},
        )
        status, from_c = core.encrypt(message, exponent, modulus)

        assert response.status_code == 200, (message, exponent, modulus)
        assert status == 0
        expected = reference.rsa_encrypt(message, exponent, modulus)
        assert response.json()["ciphertext"] == from_c == expected


# Dane niepoprawne już na poziomie typów/zakresu uint32: odrzuca je walidacja
# API (Pydantic), zanim w ogóle dotrą do biblioteki C.
BASE = {"message": 65, "public_exponent": 17, "modulus": 3233}
INVALID_PAYLOADS = [
    pytest.param({**BASE, "message": -1}, id="message_negative"),
    pytest.param({**BASE, "public_exponent": -17}, id="exponent_negative"),
    pytest.param({**BASE, "modulus": -3233}, id="modulus_negative"),
    pytest.param({**BASE, "modulus": 2**32}, id="modulus_above_uint32"),
    pytest.param({**BASE, "message": 2**32}, id="message_above_uint32"),
    pytest.param({**BASE, "public_exponent": 2**32}, id="exponent_above_uint32"),
    pytest.param({**BASE, "modulus": 2**64}, id="modulus_above_uint64"),
    pytest.param({**BASE, "message": "65"}, id="message_is_string"),
    pytest.param({**BASE, "modulus": "abc"}, id="modulus_is_text"),
    pytest.param({**BASE, "message": 65.0}, id="message_is_float_integral"),
    pytest.param({**BASE, "message": 65.5}, id="message_is_float"),
    pytest.param({**BASE, "message": True}, id="message_is_bool"),
    pytest.param({**BASE, "message": None}, id="message_is_null"),
    pytest.param({**BASE, "message": [65]}, id="message_is_list"),
    pytest.param({"public_exponent": 17, "modulus": 3233}, id="missing_message"),
    pytest.param({"message": 65, "modulus": 3233}, id="missing_public_exponent"),
    pytest.param({"message": 65, "public_exponent": 17}, id="missing_modulus"),
    pytest.param({}, id="empty_object"),
    pytest.param({**BASE, "extra": 1}, id="unknown_field"),
    pytest.param([1, 2, 3], id="body_is_list"),
    pytest.param(5, id="body_is_number"),
    pytest.param("text", id="body_is_string"),
]


@pytest.mark.parametrize("body", INVALID_PAYLOADS)
def test_malformed_payload_returns_422_invalid_request(client, body):
    response = client.post(API_URL, json=body)
    assert_controlled_error(response, 422, "INVALID_REQUEST")


RAW_BODIES = [
    pytest.param(b"{niepoprawny json", "application/json", id="broken_json"),
    pytest.param(b"", "application/json", id="empty_body"),
    pytest.param(b"NaN", "application/json", id="nan_literal"),
    pytest.param(json.dumps(BASE).encode(), "text/plain", id="valid_json_wrong_content_type"),
    pytest.param(b"message=65&public_exponent=17&modulus=3233", "application/x-www-form-urlencoded", id="form_data"),
]


@pytest.mark.parametrize("raw,content_type", RAW_BODIES)
def test_non_json_body_returns_422_invalid_request(client, raw, content_type):
    response = client.post(API_URL, content=raw, headers={"content-type": content_type})
    assert_controlled_error(response, 422, "INVALID_REQUEST")


def test_response_contains_only_ciphertext_field(client):
    response = client.post(API_URL, json=BASE)
    assert set(response.json()) == {"ciphertext"}
    assert isinstance(response.json()["ciphertext"], int)


def test_same_request_gives_same_response(client):
    """Szyfrowanie jest deterministyczne (RSA bez paddingu)."""
    responses = {client.post(API_URL, json=BASE).text for _ in range(20)}
    assert len(responses) == 1


def test_openapi_documents_endpoint_and_error_responses(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    operation = response.json()["paths"][API_URL]["post"]
    assert {"200", "422", "500", "503"} <= set(operation["responses"])
