#include "radh_crypto_core.h"

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

_Static_assert(sizeof(radh_rsa_keygen_result_t) == 16, "Keygen ABI size");
_Static_assert(offsetof(radh_rsa_keygen_result_t, n) == 0, "Keygen ABI n");
_Static_assert(offsetof(radh_rsa_keygen_result_t, e) == 4, "Keygen ABI e");
_Static_assert(offsetof(radh_rsa_keygen_result_t, d) == 8, "Keygen ABI d");
_Static_assert(offsetof(radh_rsa_keygen_result_t, phi) == 12, "Keygen ABI phi");
_Static_assert(RADH_STATUS_RSA_KEYGEN_INVALID_P == 8, "Keygen status ABI");
_Static_assert(RADH_STATUS_RSA_KEYGEN_INVALID_Q == 9, "Keygen status ABI");
_Static_assert(RADH_STATUS_RSA_KEYGEN_EQUAL_PRIMES == 10, "Keygen status ABI");
_Static_assert(RADH_STATUS_RSA_KEYGEN_MODULUS_OVERFLOW == 11, "Keygen status ABI");
_Static_assert(RADH_STATUS_RSA_KEYGEN_INVALID_EXPONENT == 12, "Keygen status ABI");
_Static_assert(RADH_STATUS_RSA_KEYGEN_EXPONENT_NOT_COPRIME == 13, "Keygen status ABI");

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "Check failed at line %d: %s\n", __LINE__, #condition); \
    return 1; } } while (0)

typedef struct {
    uint32_t p, q, e;
    radh_status_t status;
} invalid_case_t;

static int check_errors(void)
{
    static const invalid_case_t cases[] = {
        {0, 0, 0, RADH_STATUS_RSA_KEYGEN_INVALID_P},
        {1, 53, 17, RADH_STATUS_RSA_KEYGEN_INVALID_P},
        {9, 53, 17, RADH_STATUS_RSA_KEYGEN_INVALID_P},
        {561, 53, 17, RADH_STATUS_RSA_KEYGEN_INVALID_P},
        {UINT32_MAX, 53, 17, RADH_STATUS_RSA_KEYGEN_INVALID_P},
        {61, 0, 0, RADH_STATUS_RSA_KEYGEN_INVALID_Q},
        {61, 1, 17, RADH_STATUS_RSA_KEYGEN_INVALID_Q},
        {61, 49, 17, RADH_STATUS_RSA_KEYGEN_INVALID_Q},
        {61, 3215031751u, 17, RADH_STATUS_RSA_KEYGEN_INVALID_Q},
        {61, UINT32_MAX, 17, RADH_STATUS_RSA_KEYGEN_INVALID_Q},
        {9, 9, 0, RADH_STATUS_RSA_KEYGEN_INVALID_P},
        {65537, 65537, 0, RADH_STATUS_RSA_KEYGEN_EQUAL_PRIMES},
        {2, 2, 0, RADH_STATUS_RSA_KEYGEN_EQUAL_PRIMES},
        {65537, 65539, 0, RADH_STATUS_RSA_KEYGEN_MODULUS_OVERFLOW},
        {4294967291u, 2, 17, RADH_STATUS_RSA_KEYGEN_MODULUS_OVERFLOW},
        {4294967291u, 4294967279u, 17, RADH_STATUS_RSA_KEYGEN_MODULUS_OVERFLOW},
        {61, 53, 0, RADH_STATUS_RSA_KEYGEN_INVALID_EXPONENT},
        {61, 53, 1, RADH_STATUS_RSA_KEYGEN_INVALID_EXPONENT},
        {61, 53, 3120, RADH_STATUS_RSA_KEYGEN_INVALID_EXPONENT},
        {61, 53, 3121, RADH_STATUS_RSA_KEYGEN_INVALID_EXPONENT},
        {61, 53, UINT32_MAX, RADH_STATUS_RSA_KEYGEN_INVALID_EXPONENT},
        {2, 3, 2, RADH_STATUS_RSA_KEYGEN_INVALID_EXPONENT},
        {61, 53, 2, RADH_STATUS_RSA_KEYGEN_EXPONENT_NOT_COPRIME},
        {61, 53, 12, RADH_STATUS_RSA_KEYGEN_EXPONENT_NOT_COPRIME},
        {61, 53, 17, RADH_STATUS_OK}
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        const invalid_case_t *c = &cases[i];
        CHECK(radh_rsa_keygen_u32(c->p, c->q, c->e, NULL) == RADH_STATUS_INVALID_POINTER);
        radh_rsa_keygen_result_t result;
        unsigned char before[sizeof(result)];
        memset(&result, 0xa5, sizeof(result));
        memcpy(before, &result, sizeof(result));
        CHECK(radh_rsa_keygen_u32(c->p, c->q, c->e, &result) == c->status);
        if (c->status != RADH_STATUS_OK) {
            CHECK(memcmp(before, &result, sizeof(result)) == 0);
        }
    }
    return 0;
}

static int check_reference(void)
{
    radh_rsa_keygen_result_t key;
    CHECK(radh_rsa_keygen_u32(61, 53, 17, &key) == RADH_STATUS_OK);
    CHECK(key.n == 3233 && key.phi == 3120 && key.e == 17 && key.d == 2753);
    uint32_t ciphertext = 0, plaintext = 0;
    CHECK(radh_rsa_encrypt_u32(65, key.e, key.n, &ciphertext) == RADH_STATUS_OK);
    CHECK(ciphertext == 2790);
    CHECK(radh_modexp_u32(ciphertext, key.d, key.n, &plaintext) == RADH_STATUS_OK);
    CHECK(plaintext == 65);
    radh_rsa_keygen_result_t swapped;
    CHECK(radh_rsa_keygen_u32(53, 61, 17, &swapped) == RADH_STATUS_OK);
    CHECK(memcmp(&key, &swapped, sizeof(key)) == 0);
    return 0;
}

static int check_boundaries(void)
{
    static const uint32_t pairs[][2] = {{2, 5}, {3, 5}, {65521, 65537}, {2, 2147483647}};
    for (size_t i = 0; i < sizeof(pairs) / sizeof(pairs[0]); ++i) {
        uint32_t p = pairs[i][0], q = pairs[i][1];
        uint32_t phi = (uint32_t)((uint64_t)(p - 1) * (q - 1));
        uint32_t exponents[] = {phi - 1, 65537, 2654435761u};
        for (size_t j = 0; j < sizeof(exponents) / sizeof(exponents[0]); ++j) {
            uint32_t e = exponents[j];
            if (e >= phi) {
                continue;
            }
            uint32_t a = e, b = phi;
            while (b != 0) {
                uint32_t remainder = a % b;
                a = b;
                b = remainder;
            }
            radh_rsa_keygen_result_t key;
            radh_status_t status = radh_rsa_keygen_u32(p, q, e, &key);
            if (a != 1) {
                CHECK(status == RADH_STATUS_RSA_KEYGEN_EXPONENT_NOT_COPRIME);
                continue;
            }
            CHECK(status == RADH_STATUS_OK);
            CHECK(key.n == (uint64_t)p * q && key.phi == phi && key.e == e);
            CHECK(key.d > 0 && key.d < phi);
            CHECK(((uint64_t)e * key.d) % phi == 1);
            if (e == phi - 1) {
                CHECK(key.d == e);
            }
            uint32_t messages[] = {0, 1, p, q, key.n - 1, key.n / 2};
            for (size_t k = 0; k < sizeof(messages) / sizeof(messages[0]); ++k) {
                uint32_t ciphertext, plaintext;
                CHECK(radh_rsa_encrypt_u32(messages[k], e, key.n, &ciphertext) == RADH_STATUS_OK);
                CHECK(radh_modexp_u32(ciphertext, key.d, key.n, &plaintext) == RADH_STATUS_OK);
                CHECK(plaintext == messages[k]);
            }
        }
    }
    return 0;
}

static int check_small_domain(void)
{
    static const uint32_t primes[] = {2, 3, 5, 7, 11, 13, 17, 19};
    for (size_t i = 0; i < sizeof(primes) / sizeof(primes[0]); ++i) {
        for (size_t j = 0; j < sizeof(primes) / sizeof(primes[0]); ++j) {
            if (i == j) {
                continue;
            }
            uint32_t p = primes[i], q = primes[j], phi = (p - 1) * (q - 1);
            for (uint32_t e = 2; e < phi; ++e) {
                /* Niezależny oracle: szukanie odwrotności przez pełny przegląd. */
                uint32_t inverse = 0;
                for (uint32_t d = 1; d < phi; ++d) {
                    if ((e * d) % phi == 1) {
                        inverse = d;
                        break;
                    }
                }
                radh_rsa_keygen_result_t key;
                radh_status_t status = radh_rsa_keygen_u32(p, q, e, &key);
                if (inverse == 0) {
                    CHECK(status == RADH_STATUS_RSA_KEYGEN_EXPONENT_NOT_COPRIME);
                } else {
                    CHECK(status == RADH_STATUS_OK);
                    CHECK(key.n == p * q && key.e == e && key.phi == phi && key.d == inverse);
                }
            }
        }
    }
    return 0;
}

int main(void)
{
    if (check_errors() || check_reference() || check_boundaries() || check_small_domain()) {
        return EXIT_FAILURE;
    }
    puts("All RSA keygen checks passed");
    return EXIT_SUCCESS;
}
