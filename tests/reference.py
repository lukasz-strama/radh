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
    """Wykładnik prywatny d = e^-1 mod phi(n) dla liczb pierwszych p, q"""
    return pow(public_exponent, -1, (p - 1) * (q - 1))

def is_prime(value):
    """Niezależna od biblioteki C kontrola pierwszości"""
    if value < 2:
        return False
    if value % 2 == 0:
        return value == 2
    divisor = 3
    while divisor * divisor <= value:
        if value % divisor == 0:
            return False
        divisor += 2
    return True


def expected_dh_status(prime, generator, alice_secret, bob_secret):
    """Oczekiwany status radh_dh_exchange_u32.

    Kolejność walidacji z nagłówka: liczba pierwsza, generator, sekret Alice,
    sekret Boba (wskaźnik NULL jest sprawdzany wcześniej)
    """
    if not is_prime(prime):
        return "INVALID_PRIME"
    if generator < 2 or generator >= prime:
        return "INVALID_GENERATOR"
    if alice_secret == 0 or bob_secret == 0:
        return "INVALID_SECRET"
    return "OK"


def dh_exchange(prime, generator, alice_secret, bob_secret):
    """Referencyjna wymiana DH z wbudowanym pow(): zwraca (A, B, K_A, K_B)"""
    alice_public = pow(generator, alice_secret, prime)
    bob_public = pow(generator, bob_secret, prime)
    return (
        alice_public,
        bob_public,
        pow(bob_public, alice_secret, prime),
        pow(alice_public, bob_secret, prime),
    )