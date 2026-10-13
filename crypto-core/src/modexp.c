#include "radh_crypto_core.h"

#include <stddef.h>

radh_status_t radh_modexp_u32(
    uint32_t base,
    uint32_t exponent,
    uint32_t modulus,
    uint32_t *result
)
{
    if (result == NULL) {
        return RADH_STATUS_INVALID_POINTER;
    }
    if (modulus == 0) {
        return RADH_STATUS_INVALID_MODULUS;
    }

    uint32_t accumulator = 1 % modulus;
    uint32_t factor = base % modulus;

    while (exponent != 0) {
        if ((exponent & 1u) != 0) {
            accumulator = (uint32_t)(((uint64_t)accumulator * factor) % modulus);
        }
        /* Iloczyn dwóch uint32_t mieści się w uint64_t. */
        factor = (uint32_t)(((uint64_t)factor * factor) % modulus);
        exponent >>= 1;
    }

    *result = accumulator;
    return RADH_STATUS_OK;
}
