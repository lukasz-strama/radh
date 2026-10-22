import random
import pytest
import reference
from native_core import STATUS

UINT32_MAX = reference.UINT32_MAX
SEED = 20261020
RANDOM_CASES = 5_000

# Duże liczby pierwsze znane z testów; dla losowych używane dzielenia próbnego.
KNOWN_PRIMES = [3, 5, 7, 23, 65521, 65537, 2147483647, 4294967279, 4294967291]


def random_prime(rng, low, high):
    while True:
        candidate = rng.randint(low, high) | 1
        if candidate <= high and reference.is_prime(candidate):
            return candidate


def test_exchange_matches_python_pow_for_random_valid_inputs(core):
    rng = random.Random(SEED)
    for _ in range(RANDOM_CASES):
        prime = rng.choice(KNOWN_PRIMES + [random_prime(rng, 3, UINT32_MAX - 1)])
        generator = rng.randint(2, prime - 1)
        a = rng.randint(1, UINT32_MAX)
        b = rng.randint(1, UINT32_MAX)

        status, result = core.dh_exchange(prime, generator, a, b)

        assert status == STATUS["OK"], (prime, generator, a, b)
        assert result == reference.dh_exchange(prime, generator, a, b), (
            prime,
            generator,
            a,
            b,
        )
        assert result[2] == result[3]


def test_each_value_equals_pow_with_the_documented_formula(core):
    """A = pow(g, a, p), B = pow(g, b, p), K_A = pow(B, a, p), K_B = pow(A, b, p)."""
    rng = random.Random(SEED + 1)
    for _ in range(RANDOM_CASES):
        prime = random_prime(rng, 3, 2**20)
        generator = rng.randint(2, prime - 1)
        a = rng.randint(1, UINT32_MAX)
        b = rng.randint(1, UINT32_MAX)

        status, (alice_public, bob_public, alice_key, bob_key) = core.dh_exchange(
            prime, generator, a, b
        )

        assert status == STATUS["OK"]
        assert alice_public == pow(generator, a, prime)
        assert bob_public == pow(generator, b, prime)
        assert alice_key == pow(bob_public, a, prime)
        assert bob_key == pow(alice_public, b, prime)
        assert alice_key == bob_key == pow(generator, a * b, prime)


def test_status_matches_reference_oracle_on_random_inputs(core):
    """Losujemy błędne parametry; status ma zgadzać się z oracle z reference.py."""
    rng = random.Random(SEED + 2)
    for _ in range(RANDOM_CASES):
        prime = rng.choice(
            [0, 1, 2, 4, rng.randint(0, 5000), rng.choice(KNOWN_PRIMES),
             rng.randint(0, UINT32_MAX)]
        )
        generator = rng.choice(
            [0, 1, 2, prime, min(prime + 1, UINT32_MAX), max(prime - 1, 0),
             rng.randint(0, UINT32_MAX)]
        )
        a = rng.choice([0, 1, rng.randint(0, UINT32_MAX)])
        b = rng.choice([0, 1, rng.randint(0, UINT32_MAX)])

        expected = reference.expected_dh_status(prime, generator, a, b)
        status, result = core.dh_exchange(prime, generator, a, b)

        assert status == STATUS[expected], (prime, generator, a, b)
        if expected == "OK":
            assert result == reference.dh_exchange(prime, generator, a, b)
        else:
            assert result == (0xA5A5A5A5,) * 4


@pytest.mark.parametrize("prime", KNOWN_PRIMES)
def test_exchange_for_known_primes_matches_reference_on_boundary_values(core, prime):
    generators = sorted({g for g in (2, 3, prime // 2, prime - 2, prime - 1) if 2 <= g < prime})
    secrets = [1, 2, 3, 65535, 65536, 2**31, UINT32_MAX - 1, UINT32_MAX]
    for generator in generators:
        for a in secrets:
            for b in secrets:
                status, result = core.dh_exchange(prime, generator, a, b)
                assert status == STATUS["OK"]
                assert result == reference.dh_exchange(prime, generator, a, b), (
                    prime,
                    generator,
                    a,
                    b,
                )
