# Kontrakt CryptoCore dla deszyfrowania RSA (#98/#99)

Backend z #99 oczekuje jednego addytywnego symbolu. Istniejące ABI oraz
`radh_rsa_encrypt_u32` nie mogą zmienić zachowania.

Do `crypto-core/include/radh_crypto_core.h` należy dodać:

```c
/* Edukacyjne textbook RSA bez paddingu.
 * Kolejność walidacji: message != NULL, modulus >= 2,
 * private_exponent > 0, ciphertext < modulus.
 * Błąd nie zmienia *message.
 */
radh_status_t radh_rsa_decrypt_u32(
    uint32_t ciphertext,
    uint32_t private_exponent,
    uint32_t modulus,
    uint32_t *message
);
```

Symbol musi mieć dokładną nazwę `radh_rsa_decrypt_u32`. Adapter przekazuje trzy
`uint32_t` i wskaźnik na `uint32_t`; wynik funkcji ma ABI `int`.

Należy wykorzystać `radh_modexp_u32(ciphertext, private_exponent, modulus, ...)`
i zachować istniejące statusy bez zmiany numeracji:

| Status | Wartość | Warunek |
| --- | ---: | --- |
| `RADH_STATUS_OK` | 0 | poprawne wywołanie |
| `RADH_STATUS_INVALID_POINTER` | 1 | `message == NULL` |
| `RADH_STATUS_INVALID_MODULUS` | 2 | `modulus < 2` |
| `RADH_STATUS_INVALID_EXPONENT` | 3 | `private_exponent == 0` |
| `RADH_STATUS_INVALID_MESSAGE` | 4 | `ciphertext >= modulus` |

Minimalny wektor: dla `ciphertext=2790`, `private_exponent=2753` i
`modulus=3233` wynikiem jest `message=65`.

Brak symbolu powoduje kontrolowane `503 CRYPTO_CORE_UNAVAILABLE` tylko na nowych
trasach deszyfrowania. Istniejące keygen i szyfrowanie pozostają dostępne.
