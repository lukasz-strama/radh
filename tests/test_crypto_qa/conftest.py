"""
Testy wołają prawdziwy backend uvicorn przez HTTP. Wynik każdej operacji
porównujemy z referencją liczoną w czystym Pythonie (``pow``, deterministyczny
Miller–Rabin, rozkład p − 1), niezależną od CryptoCore i od
``backend/app/parameter_generation.py``.
"""

from __future__ import annotations

import math

import pytest

from helpers.multi_session_stack import Stack

UINT32_MAX = 2**32 - 1
DEMO_PRIME_MIN, DEMO_PRIME_MAX = 257, 65_521  # kontrakt #96: liczby 16-bitowe

# Konfiguracja testowa: wszystkie żądania mają IP 127.0.0.1, więc 100 + 100 losowań
# wymaga podniesienia limitów tych tras. Domyślne limity sprawdza osobny serwer.
RAISED_LIMITS = {
    "PARAMETER_RATE_PER_MINUTE": 100_000, "PARAMETER_RATE_BURST": 1_000,
    "RSA_TEXT_RATE_PER_MINUTE": 100_000, "RSA_TEXT_RATE_BURST": 1_000,
    "CRYPTO_RATE_PER_MINUTE": 100_000, "CRYPTO_RATE_BURST": 1_000,
    "CREATE_RATE_PER_MINUTE": 600, "CREATE_RATE_BURST": 64, "MAX_SESSIONS_PER_IP": 64,
}


# --- niezależne referencje ----------------------------------------------------------------

def is_prime(n: int) -> bool:
    """Deterministyczny Miller–Rabin dla n < 3,3·10^24 (inna metoda niż kod zespołu)."""
    if n < 2:
        return False
    small = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
    for p in small:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in small:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def multiplicative_order(g: int, p: int) -> int:
    """Rząd g w Z_p^* liczony wprost dla małych p (≤ 65 521): brutalnie, bez rozkładu."""
    value, k = g % p, 1
    while value != 1:
        value = value * g % p
        k += 1
    return k


def full_order(g: int, p: int) -> bool:
    return 2 <= g < p and multiplicative_order(g, p) == p - 1


def modinv(a: int, m: int) -> int:
    return pow(a, -1, m)


def rsa_keys(p: int, q: int, e: int) -> dict:
    phi = (p - 1) * (q - 1)
    assert math.gcd(e, phi) == 1
    return {"n": p * q, "e": e, "d": modinv(e, phi), "phi": phi}


def code(response):
    return response.status_code, response.json().get("error", {}).get("code")


# --- serwery ---------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def api(core, tmp_path_factory):
    """Backend z podniesionymi limitami tras demo (bez procesów węzłów)."""
    stack = Stack(tmp_path_factory.mktemp("s6-api"), core.path, RAISED_LIMITS)
    stack.start_backend()
    yield stack
    stack.close()


@pytest.fixture
def default_api(core, tmp_path):
    """Świeży backend z domyślnymi limitami kontraktu — do testów 429."""
    stack = Stack(tmp_path, core.path)
    stack.start_backend()
    yield stack
    stack.close()
