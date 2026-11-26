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

radh_status_t radh_rsa_decrypt_u32(
    uint32_t ciphertext,
    uint32_t private_exponent,
    uint32_t modulus,
    uint32_t *message
)
{
    if (message == NULL) {
        return RADH_STATUS_INVALID_POINTER;
    }
    if (modulus < 2) {
        return RADH_STATUS_INVALID_MODULUS;
    }
    if (private_exponent == 0) {
        return RADH_STATUS_INVALID_EXPONENT;
    }
    if (ciphertext >= modulus) {
        return RADH_STATUS_INVALID_MESSAGE;
    }

    return radh_modexp_u32(ciphertext, private_exponent, modulus, message);
}

radh_status_t radh_rsa_sign_u32(
    uint32_t representative,
    uint32_t private_exponent,
    uint32_t modulus,
    uint32_t *signature
)
{
    /* Obie operacje z wykładnikiem prywatnym mają te same reguły walidacji. */
    return radh_rsa_decrypt_u32(representative, private_exponent, modulus, signature);
}

radh_status_t radh_rsa_verify_u32(
    uint32_t representative,
    uint32_t signature,
    uint32_t public_exponent,
    uint32_t modulus,
    uint32_t *verified
)
{
    if (verified == NULL) {
        return RADH_STATUS_INVALID_POINTER;
    }
    if (modulus < 2) {
        return RADH_STATUS_INVALID_MODULUS;
    }
    if (public_exponent == 0) {
        return RADH_STATUS_INVALID_EXPONENT;
    }
    if (representative >= modulus) {
        return RADH_STATUS_INVALID_MESSAGE;
    }
    if (signature >= modulus) {
        return RADH_STATUS_INVALID_MESSAGE;
    }

    uint32_t recovered;
    const radh_status_t status = radh_modexp_u32(
        signature, public_exponent, modulus, &recovered);
    if (status == RADH_STATUS_OK) {
        *verified = recovered == representative ? 1u : 0u;
    }
    return status;
}
