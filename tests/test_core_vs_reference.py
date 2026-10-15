
import random
import pytest
import reference
from native_core import STATUS

UINT32_MAX = reference.UINT32_MAX
SEED = 20261012
RANDOM_CASES = 20_000


def _interesting_values():
    """Wartości graniczne uint32."""
    values = {0, 1, 2, 3, 255, 256, 65535, 65536, 65537}
    values |= {2**31 - 1, 2**31, 2**31 + 1}
    values |= {UINT32_MAX - k for k in range(0, 6)}
    values |= {4294967291}  # największa liczba pierwsza poniżej 2^32
    return sorted(values)


INTERESTING = _interesting_values()


def test_modexp_matches_python_pow_on_random_inputs(core):
    rng = random.Random(SEED)
    for _ in range(RANDOM_CASES):
        base = rng.randint(0, UINT32_MAX)
        exponent = rng.randint(0, UINT32_MAX)
        modulus = rng.randint(1, UINT32_MAX)
        status, result = core.modexp(base, exponent, modulus)
        assert status == STATUS["OK"], (base, exponent, modulus)
        assert result == reference.modexp(base, exponent, modulus), (
            base,
            exponent,
            modulus,
        )


def test_modexp_matches_python_pow_with_large_moduli(core):
    """Moduły tuż pod 2^32."""
    rng = random.Random(SEED + 1)
    for _ in range(RANDOM_CASES):
        modulus = rng.randint(UINT32_MAX - 1_000_000, UINT32_MAX)
        base = rng.randint(0, UINT32_MAX)
        exponent = rng.randint(0, UINT32_MAX)
        status, result = core.modexp(base, exponent, modulus)
        assert status == STATUS["OK"]
        assert result == reference.modexp(base, exponent, modulus), (
            base,
            exponent,
            modulus,
        )


def test_modexp_matches_python_pow_on_all_boundary_combinations(core):
    for base in INTERESTING:
        for exponent in INTERESTING:
            for modulus in INTERESTING:
                if modulus == 0:
                    continue
                status, result = core.modexp(base, exponent, modulus)
                assert status == STATUS["OK"]
                assert result == reference.modexp(base, exponent, modulus), (
                    base,
                    exponent,
                    modulus,
                )


def test_encrypt_status_and_result_match_reference_on_random_inputs(core):
    """Losujemy też błędne parametry: status ma zgadzać się z oracle z reference.py."""
    rng = random.Random(SEED + 2)
    for _ in range(RANDOM_CASES):
        modulus = rng.choice([0, 1, rng.randint(2, 3233), rng.randint(2, UINT32_MAX)])
        public_exponent = rng.choice([0, 1, 17, 65537, rng.randint(0, UINT32_MAX)])
        message = rng.choice(
            [0, 1, modulus, modulus + 1, rng.randint(0, UINT32_MAX)]
        )
        message = min(message, UINT32_MAX)

        expected_status = reference.expected_encrypt_status(
            message, public_exponent, modulus
        )
        status, ciphertext = core.encrypt(message, public_exponent, modulus)
        assert status == STATUS[expected_status], (message, public_exponent, modulus)
        if expected_status == "OK":
            assert ciphertext == reference.rsa_encrypt(
                message, public_exponent, modulus
            ), (message, public_exponent, modulus)


@pytest.mark.parametrize(
    "modulus", [2, 3, 4, 65535, 65536, 2**31, 4294967291, UINT32_MAX]
)
def test_encrypt_every_boundary_message_matches_reference(core, modulus):
    exponents = [1, 2, 3, 17, 65537, UINT32_MAX]
    candidates = {0, 1, 2, modulus // 2, modulus - 2, modulus - 1}
    messages = sorted(m for m in candidates if 0 <= m < modulus)
    for message in messages:
        for exponent in exponents:
            status, ciphertext = core.encrypt(message, exponent, modulus)
            assert status == STATUS["OK"]
            assert ciphertext == reference.rsa_encrypt(message, exponent, modulus), (
                message,
                exponent,
                modulus,
            )
