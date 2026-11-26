"""Testy ABI pełnego rzędu na zbudowanej bibliotece CryptoCore."""

import ctypes

import pytest

from native_core import STATUS
from reference import UINT32_MAX, is_prime


@pytest.fixture(scope="module")
def validate_parameters(core):
    # Bind testowy korzysta z tej samej biblioteki co istniejące testy ABI.
    # Brak nowego symbolu jest błędem, także przy wskazaniu starszej biblioteki.
    validate = ctypes.CDLL(str(core.path)).radh_dh_validate_parameters_u32
    validate.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    validate.restype = ctypes.c_int
    return validate


@pytest.mark.parametrize(("p", "g", "expected"), [
    (23, 5, "OK"),
    (23, 4, "INVALID_GENERATOR"),
    (23, 1, "INVALID_GENERATOR"),
    (23, 23, "INVALID_GENERATOR"),
    (21, 2, "INVALID_PRIME"),
    (21, 0, "INVALID_PRIME"),
    (2, 2, "INVALID_GENERATOR"),
    (3, 2, "OK"),
    (0, 0, "INVALID_PRIME"),
    (1, 2, "INVALID_PRIME"),
    (65521**2, 2, "INVALID_PRIME"),
    (UINT32_MAX - 1, 2, "INVALID_PRIME"),
    (UINT32_MAX, 2, "INVALID_PRIME"),
    (UINT32_MAX, UINT32_MAX, "INVALID_PRIME"),
    (4294967291, UINT32_MAX, "INVALID_GENERATOR"),
    (4294967291, 2, "OK"),
    (4294967291, 4, "INVALID_GENERATOR"),
    (109, 6, "OK"),
    (65537, 3, "OK"),
    (1000000007, 5, "OK"),
    (1000000007, 1000000006, "INVALID_GENERATOR"),
])
def test_parameter_status(validate_parameters, p, g, expected):
    assert validate_parameters(p, g) == STATUS[expected]


def multiplicative_order(p: int, g: int) -> int:
    """Zlicza mnożenia do powrotu do 1 bez faktoryzacji p - 1."""
    power = 1
    for order in range(1, p):
        power = power * g % p
        if power == 1:
            return order
    raise AssertionError(f"Brak rzędu dla p={p}, g={g}")


@pytest.mark.parametrize("p", range(64))
def test_small_domain_matches_multiplicative_order(validate_parameters, p):
    # 64 * 65 par, w tym wszystkie dopuszczalne g dla liczb pierwszych z zakresu.
    prime = is_prime(p)
    for g in range(65):
        if not prime:
            expected = "INVALID_PRIME"
        elif 2 <= g < p and multiplicative_order(p, g) == p - 1:
            expected = "OK"
        else:
            expected = "INVALID_GENERATOR"
        assert validate_parameters(p, g) == STATUS[expected], (p, g)


def test_65521_generator_order(validate_parameters):
    assert multiplicative_order(65521, 17) == 65520
    assert validate_parameters(65521, 17) == STATUS["OK"]


def test_manual_exchange_still_accepts_generator_of_order_11(core, validate_parameters):
    assert validate_parameters(23, 4) == STATUS["INVALID_GENERATOR"]
    assert core.dh_exchange(23, 4, 3, 7) == (STATUS["OK"], (18, 8, 6, 6))
