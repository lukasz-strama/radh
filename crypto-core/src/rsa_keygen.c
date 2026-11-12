#include "radh_crypto_core.h"
#include "number_theory.h"

#include <stddef.h>

radh_status_t radh_rsa_keygen_u32(
    uint32_t p,
    uint32_t q,
    uint32_t e,
    radh_rsa_keygen_result_t *result
)
{
    if (result == NULL) {
        return RADH_STATUS_INVALID_POINTER;
    }
    if (!is_prime_u32(p)) {
        return RADH_STATUS_RSA_KEYGEN_INVALID_P;
    }
    if (!is_prime_u32(q)) {
        return RADH_STATUS_RSA_KEYGEN_INVALID_Q;
    }
    if (p == q) {
        return RADH_STATUS_RSA_KEYGEN_EQUAL_PRIMES;
    }
    uint64_t n = (uint64_t)p * q;
    if (n > UINT32_MAX) {
        return RADH_STATUS_RSA_KEYGEN_MODULUS_OVERFLOW;
    }
    /* Phi < n, więc po sprawdzeniu n mieści się również w uint32_t. */
    uint32_t phi = (uint32_t)((uint64_t)(p - 1) * (q - 1));
    if (e <= 1 || e >= phi) {
        return RADH_STATUS_RSA_KEYGEN_INVALID_EXPONENT;
    }

    /* Rozszerzony Euklides: współczynniki przy e mają naprzemienne znaki.
     * Ich moduły rosną do najwyżej phi/gcd(e,phi), także w końcowym kroku.
     * Zatem quotient*t i old_t-quotient*t mieszczą się w [-phi,phi].
     * int64_t bezpiecznie obejmuje cały zakres, również ponad INT32_MAX.
     */
    uint32_t old_r = phi, r = e;
    int64_t old_t = 0, t = 1;
    while (r != 0) {
        uint32_t quotient = old_r / r;
        uint32_t next_r = old_r % r;
        int64_t next_t = old_t - (int64_t)quotient * t;
        old_r = r;
        r = next_r;
        old_t = t;
        t = next_t;
    }
    if (old_r != 1) {
        return RADH_STATUS_RSA_KEYGEN_EXPONENT_NOT_COPRIME;
    }
    if (old_t < 0) {
        old_t += phi;
    }
    radh_rsa_keygen_result_t output = {(uint32_t)n, e, (uint32_t)old_t, phi};
    *result = output;
    return RADH_STATUS_OK;
}
