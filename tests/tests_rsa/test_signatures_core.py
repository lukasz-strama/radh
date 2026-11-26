"""Testy edukacyjnych podpisów RSA na zbudowanej bibliotece CryptoCore."""

import ctypes
from hashlib import sha256
from random import Random

import pytest

from native_core import SENTINEL, STATUS
from reference import UINT32_MAX


@pytest.fixture(scope="module")
def rsa_signatures(core):
    library = ctypes.CDLL(str(core.path))
    sign = library.radh_rsa_sign_u32
    verify = library.radh_rsa_verify_u32
    for function, input_count in ((sign, 3), (verify, 4)):
        function.argtypes = [ctypes.c_uint32] * input_count + [
            ctypes.POINTER(ctypes.c_uint32)
        ]
        function.restype = ctypes.c_int
    return sign, verify


def call_with_output(function, *arguments):
    output = ctypes.c_uint32(SENTINEL)
    status = function(*arguments, ctypes.byref(output))
    return status, output.value


def test_reference_signature(rsa_signatures):
    sign, verify = rsa_signatures
    assert pow(65, 2753, 3233) == 588
    assert call_with_output(sign, 65, 2753, 3233) == (STATUS["OK"], 588)
    assert call_with_output(verify, 65, 588, 17, 3233) == (STATUS["OK"], 1)
    assert call_with_output(verify, 66, 588, 17, 3233) == (STATUS["OK"], 0)


@pytest.mark.parametrize(("p", "q", "exponents"), [
    (2, 11, (3, 7, 9)),
    (11, 13, (7, 11, 19)),
    (61, 53, (7, 17, 3119)),
    (101, 113, (3, 11, 257)),
    (257, 263, (3, 65537, 67071)),
    (65521, 65537, (11, 65537, 4293918719)),
    (2, 2147483647, (5, 17, 2147483645)),
])
def test_keygen_sign_verify_matches_python(core, rsa_signatures, p, q, exponents):
    sign, verify = rsa_signatures
    n = p * q
    phi = (p - 1) * (q - 1)
    for e in exponents:
        d = pow(e, -1, phi)
        status, key = core.rsa_keygen(p, q, e)
        assert (status, key) == (STATUS["OK"], {"n": n, "e": e, "d": d, "phi": phi})
        # W zbiorze są reszty względnie pierwsze z n oraz wielokrotności p lub q.
        for representative in sorted({0, 1, 2, p, q, n // 2, n - 1}):
            expected_signature = pow(representative, d, n)
            status, signature = call_with_output(sign, representative, key["d"], key["n"])
            assert (status, signature) == (STATUS["OK"], expected_signature)
            expected_verified = int(pow(expected_signature, e, n) == representative)
            assert expected_verified == 1
            status, verified = call_with_output(verify, representative, signature, key["e"], key["n"])
            assert (status, verified) == (STATUS["OK"], expected_verified)


@pytest.mark.parametrize(("representative", "signature", "exponent", "modulus"), [
    (0, 0, 1, 2),
    (1, 1, UINT32_MAX, 2),
    (UINT32_MAX - 1, UINT32_MAX - 1, UINT32_MAX, UINT32_MAX),
    (2147483647, UINT32_MAX - 2, UINT32_MAX, UINT32_MAX),
    (UINT32_MAX - 2, UINT32_MAX - 2, UINT32_MAX, UINT32_MAX),
])
def test_sign_verify_boundary_values(rsa_signatures, representative, signature, exponent, modulus):
    sign, verify = rsa_signatures
    assert call_with_output(sign, representative, exponent, modulus) == (
        STATUS["OK"], pow(representative, exponent, modulus),
    )
    assert call_with_output(verify, representative, signature, exponent, modulus) == (
        STATUS["OK"], int(pow(signature, exponent, modulus) == representative),
    )


def test_sign_verify_matches_python_across_uint32(rsa_signatures):
    sign, verify = rsa_signatures
    rng = Random(101)
    for index in range(128):
        n = rng.randint(2, UINT32_MAX)
        h = rng.randrange(n)
        d = rng.randint(1, UINT32_MAX)
        e = rng.randint(1, UINT32_MAX)
        status, signature = call_with_output(sign, h, d, n)
        assert (status, signature) == (STATUS["OK"], pow(h, d, n))
        recovered = pow(signature, e, n)
        # Obie poprawne wartości wyniku są ćwiczone także poza kluczami RSA.
        expected = recovered if index % 2 == 0 else (recovered + 1) % n
        assert call_with_output(verify, expected, signature, e, n) == (
            STATUS["OK"], int(recovered == expected),
        )


@pytest.mark.parametrize(("representative", "signature", "exponent", "modulus"), [
    (66, 588, 17, 3233),
    (65, 589, 17, 3233),
    (65, 588, 7, 3233),
    (65, 588, 17, 3127),
])
def test_verify_rejects_selected_changes(rsa_signatures, representative, signature, exponent, modulus):
    _, verify = rsa_signatures
    assert pow(signature, exponent, modulus) != representative
    assert call_with_output(verify, representative, signature, exponent, modulus) == (STATUS["OK"], 0)


@pytest.mark.parametrize(("h", "d", "n", "status"), [
    (UINT32_MAX, 0, 0, "INVALID_MODULUS"),
    (UINT32_MAX, 0, 1, "INVALID_MODULUS"),
    (3233, 0, 3233, "INVALID_EXPONENT"),
    (3233, 2753, 3233, "INVALID_MESSAGE"),
    (UINT32_MAX, UINT32_MAX, UINT32_MAX, "INVALID_MESSAGE"),
])
def test_sign_invalid_arguments_preserve_output(rsa_signatures, h, d, n, status):
    sign, _ = rsa_signatures
    assert call_with_output(sign, h, d, n) == (STATUS[status], SENTINEL)
    assert sign(h, d, n, None) == STATUS["INVALID_POINTER"]


@pytest.mark.parametrize(("h", "s", "e", "n", "status"), [
    (UINT32_MAX, UINT32_MAX, 0, 0, "INVALID_MODULUS"),
    (UINT32_MAX, UINT32_MAX, 0, 1, "INVALID_MODULUS"),
    (3233, 3233, 0, 3233, "INVALID_EXPONENT"),
    (3233, 588, 17, 3233, "INVALID_MESSAGE"),
    (65, 3233, 17, 3233, "INVALID_MESSAGE"),
    (UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, "INVALID_MESSAGE"),
])
def test_verify_invalid_arguments_preserve_output(rsa_signatures, h, s, e, n, status):
    _, verify = rsa_signatures
    assert call_with_output(verify, h, s, e, n) == (STATUS[status], SENTINEL)
    assert verify(h, s, e, n, None) == STATUS["INVALID_POINTER"]


def test_sha256_transcript_representative(rsa_signatures):
    sign, verify = rsa_signatures
    transcript = (
        b"RADH-SIGNED-DH-V1\n"
        b"session_id=00000000000000000000000000000000\n"
        b"backend_epoch=11111111111111111111111111111111\n"
        b"signer=alice\n"
        b"prime=23\n"
        b"generator=5\n"
        b"alice_public=8\n"
        b"bob_public=19\n"
        b"alice_rsa_n=3233\n"
        b"alice_rsa_e=17\n"
        b"bob_rsa_n=143\n"
        b"bob_rsa_e=7"
    )
    changed = transcript.replace(b"bob_public=19", b"bob_public=20")
    n, e, d = 3233, 17, 2753
    h = int.from_bytes(sha256(transcript).digest(), "big") % n
    changed_h = int.from_bytes(sha256(changed).digest(), "big") % n
    expected_signature = pow(h, d, n)
    # Ujemny przypadek wymaga różnych reprezentantów po redukcji obu skrótów.
    assert pow(expected_signature, e, n) == h != changed_h
    status, signature = call_with_output(sign, h, d, n)
    assert (status, signature) == (STATUS["OK"], expected_signature)
    assert call_with_output(verify, h, signature, e, n) == (STATUS["OK"], 1)
    assert call_with_output(verify, changed_h, signature, e, n) == (STATUS["OK"], 0)
