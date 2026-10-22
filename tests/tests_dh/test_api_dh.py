import json
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

import reference
from conftest import API_URL, CASES, DH_API_URL, DH_CASES, case_ids
from native_core import STATUS

VALID = DH_CASES["valid"]
INVALID = DH_CASES["invalid"]

REQUEST_FIELDS = ("prime", "generator", "alice_secret", "bob_secret")
RESPONSE_FIELDS = ("alice_public", "bob_public", "alice_shared_key", "bob_shared_key")
BASE = {"prime": 23, "generator": 5, "alice_secret": 6, "bob_secret": 15}
EXPECTED_BASE_RESPONSE = {
    "alice_public": 8,
    "bob_public": 19,
    "alice_shared_key": 2,
    "bob_shared_key": 2,
}


def payload(case):
    return {name: case[name] for name in REQUEST_FIELDS}


def assert_controlled_error(response, status_code, code):
    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def assert_server_still_works(client):
    response = client.post(DH_API_URL, json=BASE)
    assert response.status_code == 200
    assert response.json() == EXPECTED_BASE_RESPONSE



def test_reference_vector_returns_a8_b19_k2(client):
    response = client.post(DH_API_URL, json=BASE)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == EXPECTED_BASE_RESPONSE


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_valid_request_returns_expected_values(client, case):
    response = client.post(DH_API_URL, json=payload(case))
    assert response.status_code == 200
    assert response.json() == {
        "alice_public": case["alice_public"],
        "bob_public": case["bob_public"],
        "alice_shared_key": case["shared_key"],
        "bob_shared_key": case["shared_key"],
    }


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_api_matches_c_library_and_python_pow(client, core, case):
    response = client.post(DH_API_URL, json=payload(case))
    status, from_c = core.dh_exchange(*(case[name] for name in REQUEST_FIELDS))
    assert response.status_code == 200
    assert status == STATUS["OK"]
    body = response.json()
    from_api = tuple(body[name] for name in RESPONSE_FIELDS)
    assert from_api == from_c == reference.dh_exchange(*(case[n] for n in REQUEST_FIELDS))
    assert body["alice_shared_key"] == body["bob_shared_key"]


def test_response_contains_only_documented_fields(client):
    body = client.post(DH_API_URL, json=BASE).json()
    assert set(body) == set(RESPONSE_FIELDS)
    assert all(isinstance(body[name], int) for name in RESPONSE_FIELDS)


def test_same_request_gives_same_response(client):
    assert len({client.post(DH_API_URL, json=BASE).text for _ in range(20)}) == 1



@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_invalid_parameters_return_422_with_error_code(client, case):
    response = client.post(DH_API_URL, json=payload(case))
    assert_controlled_error(response, 422, case["status"])


INVALID_PAYLOADS = [
    pytest.param({**BASE, "prime": -23}, id="prime_negative"),
    pytest.param({**BASE, "generator": -1}, id="generator_negative"),
    pytest.param({**BASE, "alice_secret": -6}, id="alice_secret_negative"),
    pytest.param({**BASE, "bob_secret": -15}, id="bob_secret_negative"),
    pytest.param({**BASE, "prime": 2**32}, id="prime_above_uint32"),
    pytest.param({**BASE, "generator": 2**32}, id="generator_above_uint32"),
    pytest.param({**BASE, "alice_secret": 2**32}, id="alice_secret_above_uint32"),
    pytest.param({**BASE, "bob_secret": 2**32}, id="bob_secret_above_uint32"),
    pytest.param({**BASE, "prime": 2**64}, id="prime_above_uint64"),
    pytest.param({**BASE, "alice_secret": 10**30}, id="alice_secret_huge"),
    pytest.param({**BASE, "prime": "23"}, id="prime_is_string"),
    pytest.param({**BASE, "generator": "abc"}, id="generator_is_text"),
    pytest.param({**BASE, "alice_secret": 6.0}, id="alice_secret_is_float_integral"),
    pytest.param({**BASE, "bob_secret": 15.5}, id="bob_secret_is_float"),
    pytest.param({**BASE, "prime": True}, id="prime_is_bool"),
    pytest.param({**BASE, "generator": None}, id="generator_is_null"),
    pytest.param({**BASE, "alice_secret": [6]}, id="alice_secret_is_list"),
    pytest.param({k: v for k, v in BASE.items() if k != "prime"}, id="missing_prime"),
    pytest.param({k: v for k, v in BASE.items() if k != "generator"}, id="missing_generator"),
    pytest.param({k: v for k, v in BASE.items() if k != "alice_secret"}, id="missing_alice_secret"),
    pytest.param({k: v for k, v in BASE.items() if k != "bob_secret"}, id="missing_bob_secret"),
    pytest.param({}, id="empty_object"),
    pytest.param({**BASE, "extra": 1}, id="unknown_field"),
    pytest.param([1, 2, 3], id="body_is_list"),
    pytest.param(5, id="body_is_number"),
    pytest.param("text", id="body_is_string"),
]


@pytest.mark.parametrize("body", INVALID_PAYLOADS)
def test_malformed_payload_returns_422_invalid_request(client, body):
    response = client.post(DH_API_URL, json=body)
    assert_controlled_error(response, 422, "INVALID_REQUEST")


RAW_BODIES = [
    pytest.param(b"{niepoprawny json", "application/json", id="broken_json"),
    pytest.param(b"", "application/json", id="empty_body"),
    pytest.param(b"NaN", "application/json", id="nan_literal"),
    pytest.param(json.dumps(BASE).encode(), "text/plain", id="valid_json_wrong_content_type"),
    pytest.param(
        b"prime=23&generator=5&alice_secret=6&bob_secret=15",
        "application/x-www-form-urlencoded",
        id="form_data",
    ),
]


@pytest.mark.parametrize("raw,content_type", RAW_BODIES)
def test_non_json_body_returns_422_invalid_request(client, raw, content_type):
    response = client.post(DH_API_URL, content=raw, headers={"content-type": content_type})
    assert_controlled_error(response, 422, "INVALID_REQUEST")


def test_server_survives_series_of_invalid_requests(client):
    """Po każdej serii błędnych żądań poprawne żądanie nadal musi się udać (brak 5xx)."""
    for _ in range(10):
        for case in INVALID:
            assert client.post(DH_API_URL, json=payload(case)).status_code == 422
        for body in INVALID_PAYLOADS:
            response = client.post(DH_API_URL, json=body.values[0])
            assert 400 <= response.status_code < 500
        for raw in (b"{", b"", b"\xff\xfe", b"[]", b"null", b"9" * 5000):
            response = client.post(
                DH_API_URL, content=raw, headers={"content-type": "application/json"}
            )
            assert 400 <= response.status_code < 500
        assert_server_still_works(client)


def test_wrong_http_method_does_not_crash_server(client):
    assert client.get(DH_API_URL).status_code == 405
    assert_server_still_works(client)


def test_openapi_documents_dh_endpoint(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    operation = response.json()["paths"][DH_API_URL]["post"]
    assert {"200", "422"} <= set(operation["responses"])


WEIRD_REQUESTS = [
    pytest.param("POST", DH_API_URL, {"content": b"9" * 5000}, id="body_5000_digits"),
    pytest.param(
        "POST",
        DH_API_URL,
        {
            "content": b'{"prime":' + b"9" * 5000 + b',"generator":5,"alice_secret":6,"bob_secret":15}',
            "headers": {"content-type": "application/json"},
        },
        id="huge_integer_literal",
    ),
    pytest.param(
        "POST",
        DH_API_URL,
        {"content": b"\xff\xfe\x00", "headers": {"content-type": "application/json"}},
        id="invalid_utf8",
    ),
    pytest.param("PUT", DH_API_URL, {"json": BASE}, id="put_instead_of_post"),
    pytest.param("DELETE", DH_API_URL, {}, id="delete_method"),
    pytest.param("POST", "/api/v1/dh/nie-istnieje", {"json": BASE}, id="unknown_path"),
]


@pytest.mark.parametrize("method,url,kwargs", WEIRD_REQUESTS)
def test_unusual_requests_get_4xx_and_server_keeps_working(client, method, url, kwargs):
    response = client.request(method, url, **kwargs)
    assert 400 <= response.status_code < 500
    assert_server_still_works(client)


@pytest.mark.parametrize(
    "method,url,kwargs,status_code",
    [
        pytest.param("GET", DH_API_URL, {}, 405, id="405_method_not_allowed"),
        pytest.param("POST", "/api/v1/dh/nie-istnieje", {"json": BASE}, 404, id="404_not_found"),
    ],
)
def test_framework_errors_use_common_error_format(client, method, url, kwargs, status_code):
    response = client.request(method, url, **kwargs)
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}


def test_library_unavailable_returns_503_and_recovers(client, core, monkeypatch):
    from app.api import get_crypto_core
    from app.crypto_core import LIBRARY_ENV_VAR

    missing = str(Path(core.path).with_name("nie_istnieje.so"))
    monkeypatch.setenv(LIBRARY_ENV_VAR, missing)
    get_crypto_core.cache_clear()

    response = client.post(DH_API_URL, json=BASE)
    assert_controlled_error(response, 503, "CRYPTO_CORE_UNAVAILABLE")
    assert missing not in response.text  # brak ścieżek serwera w odpowiedzi

    monkeypatch.setenv(LIBRARY_ENV_VAR, str(core.path))
    get_crypto_core.cache_clear()
    assert_server_still_works(client)


@pytest.mark.parametrize("returned_status", [1, 99, -1])
def test_unexpected_c_status_returns_controlled_500(client, monkeypatch, returned_status):
    """Status spoza kontraktu DH daje kontrolowane 500 bez szczegółów wewnętrznych."""
    from app.api import get_crypto_core

    instance = get_crypto_core()
    monkeypatch.setattr(instance, "_exchange", lambda *args: returned_status)

    response = client.post(DH_API_URL, json=BASE)
    assert_controlled_error(response, 500, "INTERNAL_ERROR")
    assert "Traceback" not in response.text
    monkeypatch.undo()
    assert_server_still_works(client)


def test_parallel_requests_return_correct_results(client):
    """Równoległe żądania (poprawne i błędne) nie mieszają wyników."""

    def worker(index):
        if index % 3 == 0:
            return client.post(DH_API_URL, json={**BASE, "prime": 24}).status_code == 422
        response = client.post(DH_API_URL, json=BASE)
        return response.status_code == 200 and response.json() == EXPECTED_BASE_RESPONSE

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(worker, range(200)))



@pytest.mark.live
def test_live_server_dh_valid_and_invalid_requests(live_server):
    process, base_url, port = live_server
    url = base_url + DH_API_URL

    for case in VALID:
        response = httpx.post(url, json=payload(case), timeout=5)
        assert response.status_code == 200
        body = response.json()
        assert tuple(body[name] for name in RESPONSE_FIELDS) == reference.dh_exchange(
            *(case[name] for name in REQUEST_FIELDS)
        )
    for case in INVALID:
        response = httpx.post(url, json=payload(case), timeout=5)
        assert_controlled_error(response, 422, case["status"])
    broken = httpx.post(
        url, content=b"{zly json", headers={"content-type": "application/json"}, timeout=5
    )
    assert_controlled_error(broken, 422, "INVALID_REQUEST")

    for garbage in (b"GARBAGE\r\n\r\n", b"\x00\x01\x02\r\n\r\n", b"POST " + b"A" * 100_000 + b" HTTP/1.1\r\n\r\n"):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            try:
                sock.sendall(garbage)
                sock.recv(4096)
            except OSError:
                pass

    assert process.poll() is None, "Proces serwera zakończył się po błędnych żądaniach"
    response = httpx.post(url, json=BASE, timeout=5)
    assert response.status_code == 200
    assert response.json() == EXPECTED_BASE_RESPONSE


RSA_VALID = CASES["valid"]
RSA_INVALID = CASES["invalid"]


def rsa_payload(case):
    return {
        "message": case["message"],
        "public_exponent": case["public_exponent"],
        "modulus": case["modulus"],
    }


@pytest.mark.parametrize("case", RSA_VALID, ids=case_ids(RSA_VALID))
def test_rsa_endpoint_still_returns_ciphertext(client, case):
    response = client.post(API_URL, json=rsa_payload(case))
    assert response.status_code == 200
    assert response.json() == {"ciphertext": case["ciphertext"]}


@pytest.mark.parametrize("case", RSA_INVALID, ids=case_ids(RSA_INVALID))
def test_rsa_endpoint_still_rejects_invalid_parameters(client, case):
    assert client.post(API_URL, json=rsa_payload(case)).status_code == 422


def test_rsa_library_function_unaffected_by_dh_status_codes(core):
    """Dodanie statusów 5–7 nie zmieniło wartości 0–4 ani wyników RSA."""
    assert core.encrypt(65, 17, 3233) == (STATUS["OK"], 2790)
    assert core.encrypt(65, 17, 0)[0] == STATUS["INVALID_MODULUS"]
    assert core.encrypt(65, 0, 3233)[0] == STATUS["INVALID_EXPONENT"]
    assert core.encrypt(3233, 17, 3233)[0] == STATUS["INVALID_MESSAGE"]
    assert core.modexp(4, 13, 497) == (STATUS["OK"], 445)
