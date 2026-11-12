"""Testy CryptoCore (C) dla generowania kluczy RSA - radh_rsa_keygen_u32 (#55, #58).

Testy wołają bibliotekę C bezpośrednio przez ctypes (tests/native_core.py).
Dopóki zbudowana biblioteka nie eksportuje radh_rsa_keygen_u32, są pomijane
(SKIPPED z powodem w raporcie `pytest -ra`), a nie zaliczane.
"""

import pytest

import reference
from conftest import CASES, case_ids
from native_core import KEYGEN_SYMBOL, SENTINEL, STATUS

VALID = CASES["keygen_valid"]
INVALID = CASES["keygen_invalid"]
UINT32_MAX = reference.UINT32_MAX


@pytest.fixture
def keygen_core(core):
    if not core.has_keygen:
        pytest.skip(f"Biblioteka CryptoCore nie eksportuje {KEYGEN_SYMBOL} (#55 niezmergowane)")
    return core



def expected_keygen_status(p, q, e):
    """Niezależna od C wyrocznia: kolejność warunków z kontraktu (backend/README.md)."""
    if not reference.is_prime(p):
        return "RSA_KEYGEN_INVALID_P"
    if not reference.is_prime(q):
        return "RSA_KEYGEN_INVALID_Q"
    if p == q:
        return "RSA_KEYGEN_EQUAL_PRIMES"
    if p * q > UINT32_MAX:
        return "RSA_KEYGEN_MODULUS_OVERFLOW"
    phi = (p - 1) * (q - 1)
    if e <= 1 or e >= phi:
        return "RSA_KEYGEN_INVALID_EXPONENT"
    if reference_gcd(e, phi) != 1:
        return "RSA_KEYGEN_EXPONENT_NOT_COPRIME"
    return "OK"


def reference_gcd(a, b):
    while b:
        a, b = b, a % b
    return a


# --- Kontrola samych danych testowych (działa także bez #55) -----------------

@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_valid_keygen_data_is_consistent(case):
    """n = p*q, phi = (p-1)(q-1), d = e^-1 mod phi, c = m^e mod n."""
    assert case["n"] == case["p"] * case["q"] <= UINT32_MAX
    assert case["phi"] == (case["p"] - 1) * (case["q"] - 1)
    assert case["d"] == reference.private_exponent(case["p"], case["q"], case["e"])
    assert case["ciphertext"] == reference.rsa_encrypt(case["message"], case["e"], case["n"])
    assert expected_keygen_status(case["p"], case["q"], case["e"]) == "OK"


@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_invalid_keygen_data_matches_reference_oracle(case):
    assert expected_keygen_status(case["p"], case["q"], case["e"]) == case["status"]


def test_textbook_example_from_task():
    """Wartości z treści zadania, policzone w Pythonie bez udziału C."""
    assert reference.private_exponent(61, 53, 17) == 2753
    assert pow(65, 17, 3233) == 2790
    assert pow(2790, 2753, 3233) == 65


# --- Biblioteka C -------------------------------------------------------------

@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_keygen_returns_expected_keys(keygen_core, case):
    status, keys = keygen_core.rsa_keygen(case["p"], case["q"], case["e"])
    assert status == STATUS["OK"]
    assert keys == {"n": case["n"], "e": case["e"], "d": case["d"], "phi": case["phi"]}


def test_keygen_textbook_61_53_17(keygen_core):
    status, keys = keygen_core.rsa_keygen(61, 53, 17)
    assert status == STATUS["OK"]
    assert keys == {"n": 3233, "e": 17, "d": 2753, "phi": 3120}


def test_generated_keys_encrypt_65_to_2790_and_decrypt_back(keygen_core):
    """Klucz z C używamy w szyfrowaniu C, a odszyfrowujemy przez modexp C."""
    _, keys = keygen_core.rsa_keygen(61, 53, 17)
    status, ciphertext = keygen_core.encrypt(65, keys["e"], keys["n"])
    assert (status, ciphertext) == (STATUS["OK"], 2790)
    status, decrypted = keygen_core.modexp(ciphertext, keys["d"], keys["n"])
    assert (status, decrypted) == (STATUS["OK"], 65)


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_generated_keys_roundtrip_many_messages(keygen_core, case):
    _, keys = keygen_core.rsa_keygen(case["p"], case["q"], case["e"])
    n = keys["n"]
    for message in sorted({0, 1, 2, n // 2, n - 2, n - 1}):
        _, ciphertext = keygen_core.encrypt(message, keys["e"], n)
        _, decrypted = keygen_core.modexp(ciphertext, keys["d"], n)
        assert decrypted == message


@pytest.mark.parametrize("case", INVALID, ids=case_ids(INVALID))
def test_keygen_rejects_invalid_parameters_without_writing_result(keygen_core, case):
    status, keys = keygen_core.rsa_keygen(case["p"], case["q"], case["e"])
    assert status == STATUS[case["status"]]
    assert keys == dict.fromkeys(("n", "e", "d", "phi"), SENTINEL)


@pytest.mark.parametrize("case", VALID + INVALID, ids=case_ids(VALID + INVALID))
def test_keygen_null_output_is_rejected_first(keygen_core, case):
    """NULL jako wskaźnik wyniku ma pierwszeństwo przed każdym innym błędem."""
    assert keygen_core.rsa_keygen_null_output(case["p"], case["q"], case["e"]) == STATUS["INVALID_POINTER"]


def test_keygen_matches_reference_for_many_prime_pairs(keygen_core):
    """Porównanie z Pythonem dla wielu par liczb pierwszych i wykładników."""
    primes = [p for p in range(2, 400) if reference.is_prime(p)]
    checked = 0
    for p in primes[::3]:
        for q in primes[1::4]:
            for e in (3, 5, 7, 17, 257, 65537):
                expected = expected_keygen_status(p, q, e)
                status, keys = keygen_core.rsa_keygen(p, q, e)
                assert status == STATUS[expected], (p, q, e)
                if expected == "OK":
                    phi = (p - 1) * (q - 1)
                    assert keys == {"n": p * q, "e": e, "d": pow(e, -1, phi), "phi": phi}
                checked += 1
    assert checked > 500


def test_existing_rsa_and_dh_functions_still_work(keygen_core):
    """Regresja: nowa funkcja nie zmienia zachowania dotychczasowego ABI."""
    assert keygen_core.encrypt(65, 17, 3233) == (STATUS["OK"], 2790)
    assert keygen_core.modexp(4, 13, 497) == (STATUS["OK"], 445)
    status, _ = keygen_core.dh_exchange(23, 5, 6, 15)
    assert status == STATUS["OK"]
