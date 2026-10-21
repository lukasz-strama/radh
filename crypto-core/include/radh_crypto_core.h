#ifndef RADH_CRYPTO_CORE_H
#define RADH_CRYPTO_CORE_H

#include <stdint.h>

/* Wartości są częścią ABI i nie mogą być przenumerowywane. */
typedef enum {
    RADH_STATUS_OK = 0,
    RADH_STATUS_INVALID_POINTER = 1,
    RADH_STATUS_INVALID_MODULUS = 2,
    RADH_STATUS_INVALID_EXPONENT = 3,
    RADH_STATUS_INVALID_MESSAGE = 4,
    RADH_STATUS_INVALID_PRIME = 5,
    RADH_STATUS_INVALID_GENERATOR = 6,
    RADH_STATUS_INVALID_SECRET = 7
} radh_status_t;

/* ABI dla ctypes.c_int; odrzuca m.in. kompilację z -fshort-enums. */
_Static_assert(sizeof(int) == sizeof(int32_t), "ABI requires a 32-bit int");
_Static_assert(sizeof(radh_status_t) == sizeof(int), "ABI requires an int-sized enum");

/* Oblicza base^exponent mod modulus dla modulus >= 1.
 * Dowolna podstawa uint32_t i wykładnik 0 są dozwolone.
 * Przy exponent == 0 wynik to 1 % modulus, również dla base == 0.
 * Kolejność walidacji: result != NULL, modulus >= 1.
 * Błąd nie zmienia *result. Niezerowy wskaźnik musi wskazywać zapisywalny uint32_t.
 */
radh_status_t radh_modexp_u32(
    uint32_t base,
    uint32_t exponent,
    uint32_t modulus,
    uint32_t *result
);

/* Edukacyjne RSA bez paddingu i gwarancji bezpieczeństwa kryptograficznego.
 * Kolejność walidacji: ciphertext != NULL, modulus >= 2,
 * public_exponent > 0, message < modulus.
 * Błąd nie zmienia *ciphertext. Niezerowy wskaźnik musi wskazywać zapisywalny uint32_t.
 */
radh_status_t radh_rsa_encrypt_u32(
    uint32_t message,
    uint32_t public_exponent,
    uint32_t modulus,
    uint32_t *ciphertext
);

typedef struct {
    uint32_t alice_public;
    uint32_t bob_public;
    uint32_t alice_shared_key;
    uint32_t bob_shared_key;
} radh_dh_exchange_result_t;

/* Edukacyjne DH bez gwarancji bezpieczeństwa kryptograficznego.
 * Kolejność walidacji: result != NULL, prime jest liczbą pierwszą,
 * 2 <= generator < prime, alice_secret > 0, bob_secret > 0.
 * Nie sprawdza pierwotności generatora. Sekrety mogą sięgać UINT32_MAX.
 * Oblicza A = g^a mod p, B = g^b mod p, K_A = B^a mod p i K_B = A^b mod p.
 * Wynik równy 1 jest dozwolony. Błąd pozostawia całą strukturę bez zmian.
 * Niezerowy wskaźnik musi wskazywać poprawnie wyrównaną, zapisywalną strukturę.
 * Pamięć należy do wywołującego; funkcja nie przechowuje wskaźnika.
 */
radh_status_t radh_dh_exchange_u32(
    uint32_t prime,
    uint32_t generator,
    uint32_t alice_secret,
    uint32_t bob_secret,
    radh_dh_exchange_result_t *result
);

#endif
