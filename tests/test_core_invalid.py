import pytest
import reference
from conftest import CASES, case_ids
from native_core import SENTINEL, STATUS

INVALID = CASES["invalid"]


@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_encrypt_rejects_invalid_parameters(core, case):
    status, ciphertext = core.encrypt(
        case["message"], case["public_exponent"], case["modulus"]
    )
    assert status == STATUS[case["status"]]
    # Błąd nie może zmienić parametru wyjściowego.
    assert ciphertext == SENTINEL


@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_invalid_cases_match_reference_oracle(case):
    """Kontrola samych danych: oczekiwany status zgadza się z regułami z nagłówka."""
    expected = reference.expected_encrypt_status(
        case["message"], case["public_exponent"], case["modulus"]
    )
    assert case["status"] == expected


@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_encrypt_null_output_pointer_is_rejected_first(core, case):
    """NULL jako wskaźnik wyniku ma pierwszeństwo przed każdym innym błędem."""
    status = core.encrypt_null_output(
        case["message"], case["public_exponent"], case["modulus"]
    )
    assert status == STATUS["INVALID_POINTER"]


def test_encrypt_null_output_pointer_with_valid_parameters(core):
    assert core.encrypt_null_output(65, 17, 3233) == STATUS["INVALID_POINTER"]


def test_modexp_rejects_modulus_zero(core):
    status, result = core.modexp(5, 3, 0)
    assert status == STATUS["INVALID_MODULUS"]
    assert result == SENTINEL


def test_modexp_modulus_zero_wins_over_everything_else(core):
    status, result = core.modexp(0, 0, 0)
    assert status == STATUS["INVALID_MODULUS"]
    assert result == SENTINEL


def test_modexp_null_output_pointer_is_rejected(core):
    assert core.modexp_null_output(5, 3, 7) == STATUS["INVALID_POINTER"]
    assert core.modexp_null_output(5, 3, 0) == STATUS["INVALID_POINTER"]


@pytest.mark.parametrize("initial", [0, 1, 12345, 0xFFFFFFFF])
def test_failed_call_keeps_any_initial_output_value(core, initial):
    """Niezmieniony wynik po błędzie sprawdzamy dla kilku wartości początkowych."""
    status, value = core.encrypt(5, 17, 0, initial=initial)
    assert status == STATUS["INVALID_MODULUS"]
    assert value == initial
    status, value = core.encrypt(5, 0, 3233, initial=initial)
    assert status == STATUS["INVALID_EXPONENT"]
    assert value == initial
    status, value = core.encrypt(3233, 17, 3233, initial=initial)
    assert status == STATUS["INVALID_MESSAGE"]
    assert value == initial
