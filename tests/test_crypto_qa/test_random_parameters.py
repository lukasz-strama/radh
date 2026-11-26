"""#107 / #94: losowanie parametrów RSA i DH — 100 + 100 zestawów na żywym backendzie.

Każdy zestaw sprawdzamy niezależnie (Miller–Rabin, rząd generatora liczony wprost),
a potem używamy go w istniejących ścieżkach: RSA keygen → szyfrowanie → deszyfrowanie
oraz wymiana DH. Niepoprawne wejścia nie mogą zmienić stanu ani kolejnych wyników.
"""

import math

import pytest

from .conftest import (
    DEMO_PRIME_MAX, DEMO_PRIME_MIN, UINT32_MAX, code, full_order, is_prime, rsa_keys,
)

pytestmark = pytest.mark.live

SETS = 100


@pytest.fixture(scope="module")
def rsa_sets(api):
    sets = []
    for _ in range(SETS):
        response = api.http.post("/api/v1/rsa/demo/parameters")
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        sets.append(response.json())
    return sets


@pytest.fixture(scope="module")
def dh_sets(api):
    sets = []
    for _ in range(SETS):
        response = api.http.post("/api/v1/dh/demo/parameters")
        assert response.status_code == 200, response.text
        sets.append(response.json())
    return sets


def test_hundred_rsa_sets_are_valid(rsa_sets):
    for s in rsa_sets:
        assert set(s) == {"p", "q", "e"}, "odpowiedź nie może ujawniać d ani phi"
        p, q, e = s["p"], s["q"], s["e"]
        assert all(type(v) is int for v in (p, q, e))
        assert is_prime(p) and is_prime(q), s
        assert p != q, s
        assert DEMO_PRIME_MIN <= p <= DEMO_PRIME_MAX and DEMO_PRIME_MIN <= q <= DEMO_PRIME_MAX, s
        phi = (p - 1) * (q - 1)
        assert 255 < p * q <= UINT32_MAX
        assert 1 < e < phi and math.gcd(e, phi) == 1, s


def test_hundred_dh_sets_are_valid(dh_sets):
    for s in dh_sets:
        assert set(s) == {"prime", "generator"}
        p, g = s["prime"], s["generator"]
        assert is_prime(p), s
        assert DEMO_PRIME_MIN <= p <= DEMO_PRIME_MAX, s
        assert full_order(g, p), f"generator {g} nie ma pełnego rzędu {p - 1} modulo {p}"


def test_draws_are_random_not_repeated(rsa_sets, dh_sets):
    """Losowanie przez secrets: zestawy nie mogą się powtarzać ani skupiać na jednej wartości."""
    assert len({(s["p"], s["q"], s["e"]) for s in rsa_sets}) >= SETS - 2
    assert len({s["prime"] for s in dh_sets}) >= 80
    assert len({s["generator"] for s in dh_sets}) >= 50


def test_rsa_sets_work_end_to_end(api, rsa_sets):
    """Wylosowany zestaw → keygen → szyfrowanie → deszyfrowanie (każda operacja w C)."""
    for s in rsa_sets[:30]:
        expected = rsa_keys(s["p"], s["q"], s["e"])
        keygen = api.http.post("/api/v1/rsa/demo/keygen", json=s)
        assert keygen.status_code == 200, keygen.text
        assert keygen.json() == expected
        message = (s["p"] * 7 + 12345) % expected["n"]
        c = api.http.post("/api/v1/rsa/demo/encrypt", json={
            "message": message, "public_exponent": expected["e"], "modulus": expected["n"]})
        assert c.json() == {"ciphertext": pow(message, expected["e"], expected["n"])}
        m = api.http.post("/api/v1/rsa/demo/decrypt", json={
            "ciphertext": c.json()["ciphertext"], "private_exponent": expected["d"],
            "modulus": expected["n"]})
        assert m.json() == {"message": message}


def test_dh_sets_work_in_exchange(api, dh_sets):
    for i, s in enumerate(dh_sets[:30]):
        p, g = s["prime"], s["generator"]
        a, b = 2 + i, p - 2 - i
        response = api.http.post("/api/v1/dh/demo/exchange", json={
            "prime": p, "generator": g, "alice_secret": a, "bob_secret": b})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["alice_public"] == pow(g, a, p) and body["bob_public"] == pow(g, b, p)
        assert body["alice_shared_key"] == body["bob_shared_key"] == pow(g, a * b, p)
        # Pełny rząd: dla 1 ≤ a ≤ p − 2 wartość publiczna nigdy nie jest trywialna.
        assert body["alice_public"] != 1 and body["bob_public"] != 1


@pytest.mark.parametrize("path", ["/api/v1/rsa/demo/parameters", "/api/v1/dh/demo/parameters"])
def test_parameter_routes_reject_wrong_method_and_keep_working(api, path):
    assert api.http.get(path).status_code == 405
    good = api.http.post(path)
    assert good.status_code == 200 and good.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/api/v1/rsa/demo/parameters", "/api/v1/dh/demo/parameters"])
def test_default_parameter_rate_limit(default_api, path):
    """Kontrakt: 10/min/IP, burst 2 — trzecie żądanie od razu → 429 z Retry-After."""
    statuses = [default_api.http.post(path) for _ in range(3)]
    assert [r.status_code for r in statuses] == [200, 200, 429]
    assert code(statuses[2]) == (429, "RATE_LIMITED")
    assert int(statuses[2].headers["retry-after"]) >= 1
    other = "/api/v1/dh/demo/parameters" if "rsa" in path else "/api/v1/rsa/demo/parameters"
    # Wspólny kubełek „parameters” dla obu tras (jedna kolejka kosztownych losowań).
    assert default_api.http.post(other).status_code == 429


@pytest.mark.parametrize(("prime", "generator", "expected"), [
    (23, 5, 200),                       # pełny rząd
    (23, 4, 200),                       # ręczny tryb nadal dopuszcza rząd 11 (kontrakt #96)
    (24, 5, (422, "INVALID_PRIME")),
    (23, 23, (422, "INVALID_GENERATOR")),
    (2, 1, (422, "INVALID_GENERATOR")),
])
def test_manual_dh_exchange_unchanged(api, prime, generator, expected):
    """Regresja: walidacja pełnego rzędu nie zaostrzyła ręcznego DH."""
    response = api.http.post("/api/v1/dh/demo/exchange", json={
        "prime": prime, "generator": generator, "alice_secret": 6, "bob_secret": 15})
    if expected == 200:
        assert response.status_code == 200
        assert response.json()["alice_shared_key"] == pow(generator, 90, prime)
    else:
        assert code(response) == expected
