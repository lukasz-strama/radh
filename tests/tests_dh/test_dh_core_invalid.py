import pytest

import reference
from conftest import DH_CASES, case_ids
from native_core import SENTINEL, STATUS

INVALID = DH_CASES["invalid"]
VALID = DH_CASES["valid"]
UINT32_MAX = reference.UINT32_MAX


def args(case):
    return (
        case["prime"],
        case["generator"],
        case["alice_secret"],
        case["bob_secret"],
    )


@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_exchange_rejects_invalid_parameters(core, case):
    status, _ = core.dh_exchange(*args(case))
    assert status == STATUS[case["status"]]


@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_failed_exchange_leaves_whole_structure_unchanged(core, case):
    """Błąd nie może zmienić żadnego z czterech pól wyniku."""
    for initial in (SENTINEL, 0, UINT32_MAX):
        status, result = core.dh_exchange(*args(case), initial=initial)
        assert status == STATUS[case["status"]]
        assert result == (initial,) * 4


@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_invalid_cases_match_reference_oracle(case):
    """Kontrola samych danych: oczekiwany status zgadza się z regułami z nagłówka."""
    assert case["status"] == reference.expected_dh_status(*args(case))


@pytest.mark.parametrize("case", INVALID + VALID, ids=case_ids(INVALID + VALID))
def test_null_output_pointer_is_rejected_first(core, case):
    """NULL ma pierwszeństwo przed każdym innym błędem (także przy poprawnych danych)."""
    assert core.dh_exchange_null_output(*args(case)) == STATUS["INVALID_POINTER"]


# Kolejność walidacji: prime --> generator → alice_secret / bob_secret.
@pytest.mark.parametrize(
    "arguments,expected",
    [
        pytest.param((15, 1, 0, 0), "INVALID_PRIME", id="prime_before_generator_and_secrets"),
        pytest.param((23, 1, 0, 0), "INVALID_GENERATOR", id="generator_before_secrets"),
        pytest.param((23, 24, 0, 0), "INVALID_GENERATOR", id="generator_above_prime_before_secrets"),
        pytest.param((23, 5, 0, 15), "INVALID_SECRET", id="alice_secret_zero"),
        pytest.param((23, 5, 6, 0), "INVALID_SECRET", id="bob_secret_zero"),
        pytest.param((23, 5, 0, 0), "INVALID_SECRET", id="both_secrets_zero"),
    ],
)
def test_validation_order(core, arguments, expected):
    status, result = core.dh_exchange(*arguments)
    assert status == STATUS[expected]
    assert result == (SENTINEL,) * 4


@pytest.mark.parametrize("prime", [0, 1])
def test_prime_zero_and_one_are_not_prime(core, prime):
    assert core.dh_exchange(prime, 2, 3, 5)[0] == STATUS["INVALID_PRIME"]


def test_prime_two_is_prime_but_has_no_valid_generator(core):
    """2 jest pierwsza, ale zakres 2 <= g < 2 jest pusty."""
    for generator in (0, 1, 2, 3, UINT32_MAX):
        assert core.dh_exchange(2, generator, 1, 1)[0] == STATUS["INVALID_GENERATOR"]


@pytest.mark.parametrize(
    "prime",
    [
        561,  # Carmichael
        3215031751,  # silnie pseudopierwsza dla podstaw 2, 3, 5, 7
        65521**2,  # kwadrat największej liczby pierwszej < 2^16
        65537 * 65521,
        UINT32_MAX,
    ],
)
def test_composite_numbers_that_fool_naive_checks_are_rejected(core, prime):
    assert not reference.is_prime(prime)
    assert core.dh_exchange(prime, 2, 3, 5)[0] == STATUS["INVALID_PRIME"]


def test_every_number_below_5000_is_classified_like_python(core):
    """Wyczerpująco dla małych liczb: status INVALID_PRIME ⇔ liczba nie jest pierwsza."""
    for value in range(0, 5000):
        status, _ = core.dh_exchange(value, 2, 3, 5)
        if reference.is_prime(value):
            assert status != STATUS["INVALID_PRIME"], value
        else:
            assert status == STATUS["INVALID_PRIME"], value


def test_primes_near_uint32_max_are_classified_like_python(core):
    """Okolice 2^32: sprawdza brak przepełnienia w pętli dzielenia próbnego."""
    for value in range(UINT32_MAX - 300, UINT32_MAX + 1):
        status, _ = core.dh_exchange(value, 2, 3, 5)
        if reference.is_prime(value):
            assert status != STATUS["INVALID_PRIME"], value
        else:
            assert status == STATUS["INVALID_PRIME"], value


def test_failed_call_does_not_break_following_valid_call(core):
    assert core.dh_exchange(15, 5, 6, 15)[0] == STATUS["INVALID_PRIME"]
    assert core.dh_exchange(23, 5, 6, 15) == (STATUS["OK"], (8, 19, 2, 2))


# --- Wartości spoza zakresu uint32_t ----------------------------------------
# C przyjmuje wyłącznie uint32_t, więc zakres pilnuje adapter ctypes backendu.
# Bez tej kontroli ctypes po cichu obcinałby 2**32 + 23 do 23 i zwracał wynik.

OUT_OF_RANGE_VALUES = [-1, UINT32_MAX + 1, 2 * 23 + 2**32, 2**64, 10**30]
BASE_ARGUMENTS = {"prime": 23, "generator": 5, "alice_secret": 6, "bob_secret": 15}


@pytest.mark.parametrize("value", OUT_OF_RANGE_VALUES)
@pytest.mark.parametrize("field", BASE_ARGUMENTS)
def test_adapter_rejects_values_outside_uint32_on_real_library(core, field, value):
    from app.crypto_core import CryptoCore, CryptoCoreInputError

    adapter = CryptoCore(core.path)
    with pytest.raises(CryptoCoreInputError):
        adapter.exchange(**{**BASE_ARGUMENTS, field: value})


def test_adapter_accepts_uint32_boundaries_on_real_library(core):
    from app.crypto_core import CryptoCore

    adapter = CryptoCore(core.path)
    result = adapter.exchange(4294967291, 2, UINT32_MAX, UINT32_MAX)
    assert (
        result.alice_public, result.bob_public,
        result.alice_shared_key, result.bob_shared_key,
    ) == reference.dh_exchange(4294967291, 2, UINT32_MAX, UINT32_MAX)
