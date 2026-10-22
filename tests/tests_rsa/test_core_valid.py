import re
import pytest
import reference
from conftest import CASES, case_ids
from native_core import HEADER_PATH, STATUS, SENTINEL

VALID = CASES["valid"]
KEYS = CASES["rsa_keys"]
UINT32_MAX = reference.UINT32_MAX


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_encrypt_returns_expected_ciphertext(core, case):
    status, ciphertext = core.encrypt(
        case["message"], case["public_exponent"], case["modulus"]
    )
    assert status == STATUS["OK"]
    assert ciphertext == case["ciphertext"]


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_expected_values_in_json_match_python_pow(case):
    """Kontrola samych danych: wartości w JSON zgadzają się z pow() w Pythonie."""
    expected = reference.rsa_encrypt(
        case["message"], case["public_exponent"], case["modulus"]
    )
    assert case["ciphertext"] == expected


@pytest.mark.parametrize("key", KEYS, ids=case_ids(KEYS))
def test_rsa_key_data_is_consistent(key):
    """n = p*q, a d jest odwrotnością e modulo phi(n)."""
    assert key["p"] * key["q"] == key["modulus"]
    assert key["modulus"] <= UINT32_MAX
    assert key["private_exponent"] == reference.private_exponent(
        key["p"], key["q"], key["public_exponent"]
    )


@pytest.mark.parametrize("key", KEYS, ids=case_ids(KEYS))
def test_encrypt_then_decrypt_returns_original_message(core, key):
    """Szyfrujemy funkcją RSA, a deszyfrujemy przez modexp (c^d mod n).
    """
    n, e, d = key["modulus"], key["public_exponent"], key["private_exponent"]
    messages = [0, 1, 2, n // 2, n - 2, n - 1]
    for message in messages:
        status, ciphertext = core.encrypt(message, e, n)
        assert status == STATUS["OK"]
        status, decrypted = core.modexp(ciphertext, d, n)
        assert status == STATUS["OK"]
        assert decrypted == message


# Konwencje potęgowania modularnego opisane w radh_crypto_core.h.
MODEXP_CASES = [
    pytest.param(2, 10, 1000, 24, id="2^10 mod 1000"),
    pytest.param(4, 13, 497, 445, id="4^13 mod 497"),
    pytest.param(7, 0, 13, 1, id="exponent_zero"),
    pytest.param(0, 0, 13, 1, id="zero_to_zero_is_one"),
    pytest.param(0, 123, 13, 0, id="base_zero"),
    pytest.param(13, 5, 13, 0, id="base_equals_modulus"),
    pytest.param(15, 3, 13, 8, id="base_above_modulus_is_reduced"),
    pytest.param(7, 3, 1, 0, id="modulus_one_always_zero"),
    pytest.param(0, 0, 1, 0, id="zero_to_zero_mod_one"),
    pytest.param(UINT32_MAX, UINT32_MAX, 1, 0, id="max_values_mod_one"),
    pytest.param(UINT32_MAX, UINT32_MAX, 2, 1, id="max_values_mod_two"),
    pytest.param(UINT32_MAX, 0, UINT32_MAX, 1, id="exponent_zero_modulus_max"),
    pytest.param(UINT32_MAX - 1, 2, UINT32_MAX, 1, id="(-1)^2_mod_max"),
    pytest.param(UINT32_MAX, UINT32_MAX, 4294967291, 1024, id="64_bit_intermediate"),
]


@pytest.mark.parametrize("base,exponent,modulus,expected", MODEXP_CASES)
def test_modexp_known_values(core, base, exponent, modulus, expected):
    status, result = core.modexp(base, exponent, modulus)
    assert status == STATUS["OK"]
    assert result == expected
    assert result == reference.modexp(base, exponent, modulus)


def test_status_codes_match_header():
    """Kody statusu w testach muszą być zgodne z nagłówkiem C (ABI)."""
    header = HEADER_PATH.read_text(encoding="utf-8")
    found = dict(re.findall(r"RADH_STATUS_(\w+)\s*=\s*(\d+)", header))
    assert {name: int(value) for name, value in found.items()} == STATUS


def test_sentinel_is_not_a_valid_result_for_small_modulus():
    """Zabezpieczenie testów: wartownik nie może pokrywać się z wynikiem."""
    assert SENTINEL > 3233
