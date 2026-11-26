"""Testy deszyfrowania na zbudowanej bibliotece CryptoCore."""

import ctypes
from math import gcd
from random import Random

import pytest

from native_core import SENTINEL, STATUS
from reference import UINT32_MAX


@pytest.fixture(scope="module")
def rsa_decrypt(core):
    decrypt = ctypes.CDLL(str(core.path)).radh_rsa_decrypt_u32
    decrypt.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    decrypt.restype = ctypes.c_int
    return decrypt


@pytest.mark.parametrize(("c", "d", "n"), [
    (2790, 2753, 3233),
    (0, 2753, 3233),
    (1, 2753, 3233),
    (3232, 2753, 3233),
    (42, 1, 3233),
    (0, 1, 2),
    (1, UINT32_MAX, 2),
    (UINT32_MAX - 1, UINT32_MAX, UINT32_MAX),
    (UINT32_MAX - 2, UINT32_MAX - 1, UINT32_MAX),
    (UINT32_MAX - 7, UINT32_MAX, 4294967291),
])
def test_decrypt_boundary_values(rsa_decrypt, c, d, n):
    output = ctypes.c_uint32(SENTINEL)
    assert rsa_decrypt(c, d, n, ctypes.byref(output)) == STATUS["OK"]
    assert output.value == pow(c, d, n)


def test_decrypt_matches_python_pow_across_uint32(rsa_decrypt):
    rng = Random(98)
    for _ in range(128):
        n = rng.randint(2, UINT32_MAX)
        c = rng.randrange(n)
        d = rng.randint(1, UINT32_MAX)
        output = ctypes.c_uint32(SENTINEL)
        assert rsa_decrypt(c, d, n, ctypes.byref(output)) == STATUS["OK"], (c, d, n)
        assert output.value == pow(c, d, n), (c, d, n)


@pytest.mark.parametrize(("c", "d", "n", "expected"), [
    (0, 1, 0, "INVALID_MODULUS"),
    (0, 1, 1, "INVALID_MODULUS"),
    (2790, 0, 3233, "INVALID_EXPONENT"),
    (3233, 2753, 3233, "INVALID_MESSAGE"),
    (3234, 2753, 3233, "INVALID_MESSAGE"),
    (UINT32_MAX, UINT32_MAX, UINT32_MAX, "INVALID_MESSAGE"),
    (UINT32_MAX, 0, 0, "INVALID_MODULUS"),
    (UINT32_MAX, 0, 1, "INVALID_MODULUS"),
    (3233, 0, 3233, "INVALID_EXPONENT"),
])
def test_decrypt_rejects_invalid_input_without_writing(rsa_decrypt, c, d, n, expected):
    output = ctypes.c_uint32(SENTINEL)
    assert rsa_decrypt(c, d, n, ctypes.byref(output)) == STATUS[expected]
    assert output.value == SENTINEL


@pytest.mark.parametrize(("c", "d", "n"), [(2790, 2753, 3233), (UINT32_MAX, 0, 0)])
def test_decrypt_rejects_null_first(rsa_decrypt, c, d, n):
    assert rsa_decrypt(c, d, n, None) == STATUS["INVALID_POINTER"]


@pytest.mark.parametrize(("p", "q", "exponents"), [
    (61, 53, (7, 17, 3119)),
    (2, 5, (3,)),
    (2, 11, (3, 7, 9)),
    (2, 2147483647, (5, 17, 2147483645)),
    (11, 13, (7, 11, 19)),
    (101, 113, (3, 11, 257)),
    (257, 263, (3, 65537, 67071)),
    (65521, 65537, (11, 65537, 4293918719)),
    (65519, 65521, (19, 257, 4292739359)),
])
def test_keygen_encrypt_decrypt_roundtrip(core, rsa_decrypt, p, q, exponents):
    n = p * q
    phi = (p - 1) * (q - 1)
    # p i q mają wspólny dzielnik z n, a 1 i n-1 są z nim względnie pierwsze.
    messages = sorted({0, 1, 2, p, q, n // 2, n - 1})
    for e in exponents:
        assert 1 < e < phi and gcd(e, phi) == 1
        d = pow(e, -1, phi)
        status, key = core.rsa_keygen(p, q, e)
        assert status == STATUS["OK"]
        assert key == {"n": n, "e": e, "d": d, "phi": phi}
        for message in messages:
            status, ciphertext = core.encrypt(message, key["e"], key["n"])
            assert (status, ciphertext) == (STATUS["OK"], pow(message, e, n))
            output = ctypes.c_uint32(SENTINEL)
            assert rsa_decrypt(ciphertext, key["d"], key["n"], ctypes.byref(output)) == STATUS["OK"]
            assert pow(ciphertext, d, n) == message == output.value, (p, q, e, message)


def test_textbook_roundtrip(core, rsa_decrypt):
    status, key = core.rsa_keygen(61, 53, 17)
    assert (status, key) == (STATUS["OK"], {"n": 3233, "e": 17, "d": 2753, "phi": 3120})
    assert core.encrypt(65, key["e"], key["n"]) == (STATUS["OK"], 2790)
    output = ctypes.c_uint32(SENTINEL)
    assert rsa_decrypt(2790, key["d"], key["n"], ctypes.byref(output)) == STATUS["OK"]
    assert output.value == 65
