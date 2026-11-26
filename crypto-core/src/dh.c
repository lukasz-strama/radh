#include "radh_crypto_core.h"

#include "number_theory.h"
#include <stddef.h>

static bool passes_order_check(uint32_t prime, uint32_t generator, uint32_t factor)
{
    uint32_t power;
    return radh_modexp_u32(generator, (prime - 1) / factor, prime, &power)
        == RADH_STATUS_OK && power != 1;
}

radh_status_t radh_dh_validate_parameters_u32(uint32_t prime, uint32_t generator)
{
    if (!is_prime_u32(prime)) {
        return RADH_STATUS_INVALID_PRIME;
    }
    if (generator < 2 || generator >= prime) {
        return RADH_STATUS_INVALID_GENERATOR;
    }

    uint32_t remaining = prime - 1;
    /* Po 2 sprawdzamy tylko dzielniki nieparzyste. Dzielenie chroni przed
     * przepełnieniem i uwzględnia dzielnik równy pierwiastkowi. */
    for (uint32_t factor = 2; factor <= remaining / factor;
            factor += (factor == 2 ? 1 : 2)) {
        if (remaining % factor == 0) {
            if (!passes_order_check(prime, generator, factor)) {
                return RADH_STATUS_INVALID_GENERATOR;
            }
            /* Usuwamy wszystkie potęgi czynnika, żeby sprawdzić go tylko raz. */
            do {
                remaining /= factor;
            } while (remaining % factor == 0);
        }
    }
    /* Reszta większa od 1 jest ostatnim czynnikiem pierwszym. */
    if (remaining > 1 && !passes_order_check(prime, generator, remaining)) {
        return RADH_STATUS_INVALID_GENERATOR;
    }
    return RADH_STATUS_OK;
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
