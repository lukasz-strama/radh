"""Ograniczony tekstowy cykl RSA; każda operacja modularna pozostaje w C."""

from __future__ import annotations

from .crypto_core import CryptoCore
from .telemetry import operation


MAX_TEXT_BYTES = 128


class RsaTextError(ValueError):
    """Kontrolowany błąd publicznego kontraktu tekstowego RSA."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_text_modulus(modulus: int) -> None:
    if modulus <= 255:
        raise RsaTextError(
            "TEXT_MODULUS_TOO_SMALL",
            "Moduł RSA dla tekstu musi być większy od 255.",
        )


@operation("crypto.rsa", "rsa.text.encrypt", text=True,
           public=lambda core, text, public_exponent, modulus:
           {"public_exponent": public_exponent, "modulus": modulus})
def encrypt_text(
    core: CryptoCore, text: str, public_exponent: int, modulus: int
) -> list[int]:
    """Zakoduj UTF-8 i zaszyfruj każdy bajt osobnym wywołaniem CryptoCore."""

    _require_text_modulus(modulus)
    try:
        encoded = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise RsaTextError("INVALID_UTF8", "Tekst nie jest poprawnym UTF-8.") from exc
    if not encoded:
        raise RsaTextError("EMPTY_TEXT", "Tekst nie może być pusty.")
    if len(encoded) > MAX_TEXT_BYTES:
        raise RsaTextError(
            "TEXT_TOO_LONG", "Tekst może mieć najwyżej 128 bajtów UTF-8."
        )
    return [core.encrypt(byte, public_exponent, modulus) for byte in encoded]


@operation("crypto.rsa", "rsa.text.decrypt", text=True,
           public=lambda core, ciphertexts, private_exponent, modulus: {"modulus": modulus})
def decrypt_text(
    core: CryptoCore, ciphertexts: list[int], private_exponent: int, modulus: int
) -> str:
    """Odszyfruj bajty w C, sprawdź ich zakres i odtwórz ścisłe UTF-8."""

    _require_text_modulus(modulus)
    decoded = bytearray()
    for ciphertext in ciphertexts:
        value = core.decrypt(ciphertext, private_exponent, modulus)
        if value > 255:
            raise RsaTextError(
                "DECRYPTED_BYTE_OUT_OF_RANGE",
                "Odszyfrowana wartość nie jest bajtem.",
            )
        decoded.append(value)
    try:
        return bytes(decoded).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RsaTextError(
            "INVALID_UTF8", "Odszyfrowane bajty nie tworzą poprawnego UTF-8."
        ) from exc
