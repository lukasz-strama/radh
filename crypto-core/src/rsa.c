#include "radh_crypto_core.h"

#include <stddef.h>

radh_status_t radh_rsa_encrypt_u32(
    uint32_t message,
    uint32_t public_exponent,
    uint32_t modulus,
    uint32_t *ciphertext
)
{
    if (ciphertext == NULL) {
        return RADH_STATUS_INVALID_POINTER;
    }
    if (modulus < 2) {
        return RADH_STATUS_INVALID_MODULUS;
    }
    if (public_exponent == 0) {
        return RADH_STATUS_INVALID_EXPONENT;
    }
    if (message >= modulus) {
        return RADH_STATUS_INVALID_MESSAGE;
    }

    return radh_modexp_u32(message, public_exponent, modulus, ciphertext);
}
