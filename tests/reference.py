UINT32_MAX = 2**32 - 1


def modexp(base, exponent, modulus):
    """base^exponent mod modulus (modulus >= 1). Zgodne z konwencją CryptoCore."""
    return pow(base, exponent, modulus)


def rsa_encrypt(message, public_exponent, modulus):
    """Edukacyjne RSA bez paddingu: message^e mod n."""
    return pow(message, public_exponent, modulus)


def expected_modexp_status(modulus):
    """Oczekiwany status radh_modexp_u32 (sprawdza tylko moduł)."""
    return "INVALID_MODULUS" if modulus == 0 else "OK"


def expected_encrypt_status(message, public_exponent, modulus):
    """Oczekiwany status radh_rsa_encrypt_u32.

    Kolejność walidacji z nagłówka: moduł, wykładnik, wiadomość.
    """
    if modulus < 2:
        return "INVALID_MODULUS"
    if public_exponent == 0:
        return "INVALID_EXPONENT"
    if message >= modulus:
        return "INVALID_MESSAGE"
    return "OK"


def private_exponent(p, q, public_exponent):
    """Wykładnik prywatny d = e^-1 mod phi(n) dla liczb pierwszych p, q."""
    return pow(public_exponent, -1, (p - 1) * (q - 1))
