import pytest
import reference
from conftest import DH_CASES, case_ids
from native_core import DH_FIELDS, STATUS

VALID = DH_CASES["valid"]
UINT32_MAX = reference.UINT32_MAX


def exchange(core, case):
    return core.dh_exchange(
        case["prime"], case["generator"], case["alice_secret"], case["bob_secret"]
    )

def test_reference_vector_gives_a8_b19_k2(core):
    """Wektor z opisu zadania: p=23, g=5, a=6, b=15 --> A=8, B=19, K=2"""
    status, result = core.dh_exchange(23, 5, 6, 15)
    assert status == STATUS["OK"]
    assert result == (8, 19, 2, 2)

@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_exchange_returns_expected_values(core, case):
    status, (alice_public, bob_public, alice_key, bob_key) = exchange(core, case)
    assert status == STATUS["OK"]
    assert alice_public == case["alice_public"]
    assert bob_public == case["bob_public"]
    assert alice_key == case["shared_key"]
    assert bob_key == case["shared_key"]

@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_alice_and_bob_compute_the_same_secret_independently(core, case):
    """K_A = B^a mod p, K_B = A^b mod p. Liczymy je osobno przez modexp i porównujemy."""
    status, (alice_public, bob_public, alice_key, bob_key) = exchange(core, case)
    assert status == STATUS["OK"]
    p, a, b = case["prime"], case["alice_secret"], case["bob_secret"]

    status, alice_from_modexp = core.modexp(bob_public, a, p)
    assert status == STATUS["OK"]
    status, bob_from_modexp = core.modexp(alice_public, b, p)
    assert status == STATUS["OK"]

    assert alice_key == alice_from_modexp
    assert bob_key == bob_from_modexp
    assert alice_key == bob_key

@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_public_values_are_computed_with_modexp(core, case):
    """A = g^a mod p i B = g^b mod p zgodnie z radh_modexp_u32."""
    status, (alice_public, bob_public, _, _) = exchange(core, case)
    assert status == STATUS["OK"]
    assert core.modexp(case["generator"], case["alice_secret"], case["prime"]) == (
        STATUS["OK"],
        alice_public,
    )
    assert core.modexp(case["generator"], case["bob_secret"], case["prime"]) == (
        STATUS["OK"],
        bob_public,
    )


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_all_results_are_reduced_modulo_prime(core, case):
    status, result = exchange(core, case)
    assert status == STATUS["OK"]
    assert all(0 <= value < case["prime"] for value in result)


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_success_overwrites_every_result_field(core, case):
    """Po sukcesie żadne pole nie może zostać wartownikiem ani zostać pominięte."""
    for initial in (0, 0xA5A5A5A5, UINT32_MAX):
        status, result = core.dh_exchange(
            case["prime"],
            case["generator"],
            case["alice_secret"],
            case["bob_secret"],
            initial=initial,
        )
        assert status == STATUS["OK"]
        assert result == (
            case["alice_public"],
            case["bob_public"],
            case["shared_key"],
            case["shared_key"],
        )


def test_swapping_alice_and_bob_swaps_public_values_but_keeps_secret(core):
    status, (a_pub, b_pub, k_a, k_b) = core.dh_exchange(23, 5, 6, 15)
    assert status == STATUS["OK"]
    status, (b_pub2, a_pub2, k_b2, k_a2) = core.dh_exchange(23, 5, 15, 6)
    assert status == STATUS["OK"]
    assert (a_pub, b_pub) == (a_pub2, b_pub2)
    assert k_a == k_b == k_a2 == k_b2


def test_exchange_is_deterministic(core):
    results = {core.dh_exchange(4294967291, 2, 123456789, 987654321) for _ in range(20)}
    assert len(results) == 1


def test_result_value_one_is_allowed(core):
    """Nagłówek: „Wynik równy 1 jest dozwolony” (np. g^(p-1) mod p = 1)."""
    status, (alice_public, _, alice_key, bob_key) = core.dh_exchange(23, 5, 22, 44)
    assert status == STATUS["OK"]
    assert alice_public == 1
    assert alice_key == bob_key == 1


def test_generator_does_not_have_to_be_a_primitive_root(core):
    """Nagłówek: funkcja nie sprawdza pierwotności generatora (2 ma rząd 11 mod 23)."""
    assert pow(2, 11, 23) == 1
    status, result = core.dh_exchange(23, 2, 5, 7)
    assert status == STATUS["OK"]
    assert result == reference.dh_exchange(23, 2, 5, 7)


@pytest.mark.parametrize("prime", [3, 5, 7, 11, 13, 23, 65537, 2147483647, 4294967291])
def test_boundary_generators_and_secrets(core, prime):
    generators = sorted({g for g in (2, 3, prime // 2, prime - 2, prime - 1) if 2 <= g < prime})
    secrets = [1, 2, prime - 1, prime, prime + 1, UINT32_MAX]
    secrets = sorted({s for s in secrets if 1 <= s <= UINT32_MAX})
    for generator in generators:
        for a in secrets:
            for b in secrets:
                status, result = core.dh_exchange(prime, generator, a, b)
                assert status == STATUS["OK"], (prime, generator, a, b)
                assert result == reference.dh_exchange(prime, generator, a, b), (
                    prime,
                    generator,
                    a,
                    b,
                )
                assert result[2] == result[3]


def test_result_structure_has_four_uint32_fields_in_documented_order():
    """Kolejność pól to część ABI: A, B, K_A, K_B."""
    assert DH_FIELDS == ("alice_public", "bob_public", "alice_shared_key", "bob_shared_key")
