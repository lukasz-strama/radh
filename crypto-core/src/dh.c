#include "radh_crypto_core.h"

#include <stdbool.h>
#include <stddef.h>

static bool is_prime_u32(uint32_t value)
{
    if (value < 2) {
        return false;
    }
    if (value % 2 == 0) {
        return value == 2;
    }

    /* Dzielenie zamiast divisor * divisor zapobiega przepełnieniu. */
    for (uint32_t divisor = 3; divisor <= value / divisor; divisor += 2) {
        if (value % divisor == 0) {
            return false;
        }
    }
    return true;
}

radh_status_t radh_dh_exchange_u32(
    uint32_t prime,
    uint32_t generator,
    uint32_t alice_secret,
    uint32_t bob_secret,
    radh_dh_exchange_result_t *result
)
{
    if (result == NULL) {
        return RADH_STATUS_INVALID_POINTER;
    }
    if (!is_prime_u32(prime)) {
        return RADH_STATUS_INVALID_PRIME;
    }
    if (generator < 2 || generator >= prime) {
        return RADH_STATUS_INVALID_GENERATOR;
    }
    if (alice_secret == 0) {
        return RADH_STATUS_INVALID_SECRET;
    }
    if (bob_secret == 0) {
        return RADH_STATUS_INVALID_SECRET;
    }

    /* Zapis do pamięci wywołującego następuje dopiero po wszystkich obliczeniach. */
    radh_dh_exchange_result_t output;
    radh_status_t status = radh_modexp_u32(generator, alice_secret, prime,
        &output.alice_public);
    if (status != RADH_STATUS_OK) {
        return status;
    }
    status = radh_modexp_u32(generator, bob_secret, prime, &output.bob_public);
    if (status != RADH_STATUS_OK) {
        return status;
    }
    status = radh_modexp_u32(output.bob_public, alice_secret, prime,
        &output.alice_shared_key);
    if (status != RADH_STATUS_OK) {
        return status;
    }
    status = radh_modexp_u32(output.alice_public, bob_secret, prime,
        &output.bob_shared_key);
    if (status != RADH_STATUS_OK) {
        return status;
    }

    *result = output;
    return RADH_STATUS_OK;
}
