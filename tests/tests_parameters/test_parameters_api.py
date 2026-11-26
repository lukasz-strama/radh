"""Kontrakt HTTP losowania parametrów RSA i DH (#96)."""

import math
from dataclasses import replace

import pytest


RSA_URL = "/api/v1/rsa/demo/parameters"
DH_URL = "/api/v1/dh/demo/parameters"


def factors(value):
    result = set()
    divisor = 2
    while divisor * divisor <= value:
        if value % divisor == 0:
            result.add(divisor)
            while value % divisor == 0:
                value //= divisor
        divisor += 1
    if value > 1:
        result.add(value)
    return result


def full_order(prime, generator):
    return all(
        pow(generator, (prime - 1) // factor, prime) != 1
        for factor in factors(prime - 1)
    )


@pytest.fixture
def parameter_client(client, monkeypatch):
    """Podnieś limit wyłącznie dla testu akceptacyjnego 100+100."""

    runtime = client.app.state.runtime
    runtime.settings = replace(
        runtime.settings,
        parameter_rate_per_minute=100_000,
        parameter_rate_burst=1_000,
    )
    from app.api import get_crypto_core

    core = get_crypto_core()
    if core._dh_parameter_validation is None:
        def validate(prime, generator):
            p, g = prime.value, generator.value
            return 0 if full_order(p, g) else 6

        monkeypatch.setattr(core, "_dh_parameter_validation", validate)
    return client


def test_rsa_parameters_contract_and_existing_keygen(parameter_client):
    for _ in range(100):
        response = parameter_client.post(RSA_URL)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"p", "q", "e"}
        p, q, e = body["p"], body["q"], body["e"]
        phi = (p - 1) * (q - 1)
        assert p != q and 255 < p * q <= 2**32 - 1
        assert 1 < e < phi and math.gcd(e, phi) == 1
        keys = parameter_client.post(
            "/api/v1/rsa/demo/keygen", json={"p": p, "q": q, "e": e}
        )
        assert keys.status_code == 200
        assert keys.json()["n"] == p * q


def test_dh_parameters_contract_and_existing_exchange(parameter_client):
    for _ in range(100):
        response = parameter_client.post(DH_URL)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"prime", "generator"}
        assert full_order(body["prime"], body["generator"])
        exchange = parameter_client.post(
            "/api/v1/dh/demo/exchange",
            json={**body, "alice_secret": 6, "bob_secret": 15},
        )
        assert exchange.status_code == 200
        result = exchange.json()
        assert result["alice_shared_key"] == result["bob_shared_key"]


def test_openapi_documents_bodyless_parameter_endpoints(parameter_client):
    paths = parameter_client.get("/openapi.json").json()["paths"]
    for path in (RSA_URL, DH_URL):
        operation = paths[path]["post"]
        assert "requestBody" not in operation
        assert {"200", "429", "500", "503"} <= set(operation["responses"])


def test_parameter_routes_have_separate_rate_limit(client):
    first = client.post(RSA_URL)
    second = client.post(RSA_URL)
    third = client.post(RSA_URL)
    assert first.status_code == second.status_code == 200
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "RATE_LIMITED"
    assert third.headers["retry-after"]


def test_dh_without_new_cryptocore_symbol_returns_controlled_503(client):
    from app.api import get_crypto_core

    core = get_crypto_core()
    original = core._dh_parameter_validation
    core._dh_parameter_validation = None
    try:
        response = client.post(DH_URL)
    finally:
        core._dh_parameter_validation = original
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CRYPTO_CORE_UNAVAILABLE"


def test_nginx_allowlist_contains_only_exact_parameter_routes():
    config = open("deploy/nginx.conf", encoding="utf-8").read()
    assert "^/api/v1/(rsa|dh)/demo/parameters$" in config
    assert "limit_req zone=api burst=2 nodelay;" in config
