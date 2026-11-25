"""Ograniczone zasobowo losowanie demonstracyjnych parametrów RSA i DH."""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass

from .crypto_core import CryptoCore, CryptoCoreCallError, UINT32_MAX


# Uzgodniony zakres demonstracyjny: nie więcej niż 16 bitów na liczbę
# pierwszą. Iloczyn dwóch wartości z tego zakresu mieści się w uint32.
DEMO_PRIME_MIN = 257
DEMO_PRIME_MAX = 65_521
RSA_MODULUS_MIN = 255


class ParameterGenerationExhausted(RuntimeError):
    """Nie znaleziono poprawnego zestawu w skonfigurowanym budżecie prób."""

    code = "PARAMETER_GENERATION_EXHAUSTED"
    message = "Nie udało się wylosować parametrów w limicie prób."


@dataclass(frozen=True)
class RsaParameters:
    p: int
    q: int
    e: int


@dataclass(frozen=True)
class DhParameters:
    prime: int
    generator: int


class _AttemptBudget:
    """Wspólny, twardy limit losowań dla jednego żądania."""

    def __init__(self, maximum: int) -> None:
        self.remaining = maximum

    def randbelow(self, upper_bound: int) -> int:
        if self.remaining <= 0:
            raise ParameterGenerationExhausted()
        self.remaining -= 1
        return secrets.randbelow(upper_bound)


def _is_prime(value: int) -> bool:
    """Szybki filtr kandydatów; ostateczną walidację wykonuje CryptoCore."""

    if value < 2:
        return False
    if value % 2 == 0:
        return value == 2
    divisor = 3
    while divisor * divisor <= value:
        if value % divisor == 0:
            return False
        divisor += 2
    return True


def _random_prime(budget: _AttemptBudget, *, exclude: int | None = None) -> int:
    odd_count = ((DEMO_PRIME_MAX - DEMO_PRIME_MIN) // 2) + 1
    while True:
        candidate = DEMO_PRIME_MIN + 2 * budget.randbelow(odd_count)
        if candidate != exclude and _is_prime(candidate):
            return candidate


def _random_public_exponent(phi: int, budget: _AttemptBudget) -> int:
    while True:
        # Zakres 2..phi-1; względna pierwszość odrzuci każdą liczbę parzystą.
        candidate = 2 + budget.randbelow(phi - 2)
        if math.gcd(candidate, phi) == 1:
            return candidate


def _prime_factors(value: int) -> set[int]:
    factors: set[int] = set()
    divisor = 2
    while divisor * divisor <= value:
        if value % divisor == 0:
            factors.add(divisor)
            while value % divisor == 0:
                value //= divisor
        divisor = 3 if divisor == 2 else divisor + 2
    if value > 1:
        factors.add(value)
    return factors


def _has_full_order(generator: int, prime: int) -> bool:
    order = prime - 1
    return all(
        pow(generator, order // factor, prime) != 1
        for factor in _prime_factors(order)
    )


def _random_full_order_generator(prime: int, budget: _AttemptBudget) -> int:
    while True:
        # p-1 ma rząd 2, więc nie może być generatorem pełnego rzędu dla p > 3.
        candidate = 2 + budget.randbelow(prime - 3)
        if _has_full_order(candidate, prime):
            return candidate


def generate_rsa_parameters(core: CryptoCore, max_attempts: int) -> RsaParameters:
    """Wylosuj p, q i e, a następnie zatwierdź komplet przez RSA keygen w C."""

    budget = _AttemptBudget(max_attempts)
    validation_errors = {
        "INVALID_P", "INVALID_Q", "EQUAL_PRIMES", "MODULUS_OVERFLOW",
        "INVALID_KEYGEN_EXPONENT", "EXPONENT_NOT_COPRIME",
    }
    while True:
        p = _random_prime(budget)
        q = _random_prime(budget, exclude=p)
        phi = (p - 1) * (q - 1)
        e = _random_public_exponent(phi, budget)
        try:
            result = core.generate_rsa_keys(p, q, e)
        except CryptoCoreCallError as exc:
            if exc.code in validation_errors:
                continue
            raise
        if not (
            RSA_MODULUS_MIN < result.n <= UINT32_MAX
            and result.n == p * q
            and result.e == e
            and result.phi == phi
        ):
            raise CryptoCoreCallError(
                -1, "INTERNAL_ERROR", "CryptoCore zwrócił niespójny wynik keygen."
            )
        return RsaParameters(p=p, q=q, e=e)


def generate_dh_parameters(core: CryptoCore, max_attempts: int) -> DhParameters:
    """Wylosuj p i pierwiastek pierwotny, zatwierdzając komplet w CryptoCore."""

    budget = _AttemptBudget(max_attempts)
    while True:
        prime = _random_prime(budget)
        generator = _random_full_order_generator(prime, budget)
        try:
            core.validate_dh_parameters(prime, generator)
        except CryptoCoreCallError as exc:
            if exc.code in {"INVALID_PRIME", "INVALID_GENERATOR"}:
                continue
            raise
        return DhParameters(prime=prime, generator=generator)
