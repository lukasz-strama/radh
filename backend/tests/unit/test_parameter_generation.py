"""Testy losowania parametrów i niezależnej kontroli warunków #96."""

import math
from types import SimpleNamespace

import pytest

from app import parameter_generation as generation
from app.crypto_core import CryptoCoreCallError


def is_prime(value):
    return value >= 2 and all(value % divisor for divisor in range(2, math.isqrt(value) + 1))


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


def has_full_order(generator, prime):
    return all(
        pow(generator, (prime - 1) // factor, prime) != 1
        for factor in factors(prime - 1)
    )


class IndependentCore:
    """Atrapa kontraktu C, która nie korzysta z funkcji modułu produkcyjnego."""

    def generate_rsa_keys(self, p, q, e):
        if not is_prime(p):
            raise CryptoCoreCallError(8, "INVALID_P", "invalid")
        if not is_prime(q):
            raise CryptoCoreCallError(9, "INVALID_Q", "invalid")
        if p == q:
            raise CryptoCoreCallError(10, "EQUAL_PRIMES", "invalid")
        phi = (p - 1) * (q - 1)
        if not 1 < e < phi or math.gcd(e, phi) != 1:
            raise CryptoCoreCallError(13, "EXPONENT_NOT_COPRIME", "invalid")
        return SimpleNamespace(n=p * q, e=e, d=pow(e, -1, phi), phi=phi)

    def validate_dh_parameters(self, prime, generator):
        if not is_prime(prime):
            raise CryptoCoreCallError(5, "INVALID_PRIME", "invalid")
        if not 2 <= generator < prime or not has_full_order(generator, prime):
            raise CryptoCoreCallError(6, "INVALID_GENERATOR", "invalid")


def test_100_rsa_sets_pass_independent_validation_and_keygen():
    core = IndependentCore()
    for _ in range(100):
        params = generation.generate_rsa_parameters(core, 256)
        phi = (params.p - 1) * (params.q - 1)
        assert generation.DEMO_PRIME_MIN <= params.p <= generation.DEMO_PRIME_MAX
        assert generation.DEMO_PRIME_MIN <= params.q <= generation.DEMO_PRIME_MAX
        assert is_prime(params.p) and is_prime(params.q) and params.p != params.q
        assert 255 < params.p * params.q <= 2**32 - 1
        assert 1 < params.e < phi and math.gcd(params.e, phi) == 1
        keys = core.generate_rsa_keys(params.p, params.q, params.e)
        assert pow(pow(65, keys.e, keys.n), keys.d, keys.n) == 65


def test_100_dh_sets_have_full_order_and_work_in_exchange():
    core = IndependentCore()
    for _ in range(100):
        params = generation.generate_dh_parameters(core, 256)
        assert generation.DEMO_PRIME_MIN <= params.prime <= generation.DEMO_PRIME_MAX
        assert is_prime(params.prime)
        assert 2 <= params.generator < params.prime
        assert has_full_order(params.generator, params.prime)
        alice_public = pow(params.generator, 6, params.prime)
        bob_public = pow(params.generator, 15, params.prime)
        assert pow(bob_public, 6, params.prime) == pow(
            alice_public, 15, params.prime
        )


@pytest.mark.parametrize("kind", ["rsa", "dh"])
def test_attempt_budget_exhaustion_is_controlled(monkeypatch, kind):
    monkeypatch.setattr(generation.secrets, "randbelow", lambda _upper: 0)
    function = (
        generation.generate_rsa_parameters
        if kind == "rsa"
        else generation.generate_dh_parameters
    )
    with pytest.raises(generation.ParameterGenerationExhausted):
        function(IndependentCore(), 3)
