"""Modele danych publicznego API."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


UINT32_MAX = 2**32 - 1
Uint32 = Annotated[int, Field(strict=True, ge=0, le=UINT32_MAX)]


class RsaPublicKey(BaseModel):
    """Edukacyjny klucz publiczny RSA."""

    model_config = ConfigDict(extra="forbid")

    n: Uint32 = Field(
        description="Moduł RSA; biblioteka C wymaga wartości co najmniej 2."
    )
    e: Uint32 = Field(
        description="Wykładnik publiczny; biblioteka C wymaga wartości dodatniej."
    )


class RsaEncryptRequest(BaseModel):
    """Dane wejściowe demonstracyjnego szyfrowania RSA."""

    model_config = ConfigDict(extra="forbid")

    message: Uint32 = Field(
        description="Liczba do zaszyfrowania; musi być mniejsza od n."
    )
    public_exponent: Uint32
    modulus: Uint32


class RsaEncryptResponse(BaseModel):
    """Wynik demonstracyjnego szyfrowania RSA."""

    ciphertext: Uint32


class ErrorDetail(BaseModel):
    """Stabilny kod błędu i komunikat dla użytkownika."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Wspólny format kontrolowanych błędów API."""

    error: ErrorDetail


class DhExchangeRequest(BaseModel):
    """Parametry edukacyjnej wymiany DH; walidację matematyczną wykonuje C."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [
            {"prime": 23, "generator": 5, "alice_secret": 6, "bob_secret": 15}
        ]},
    )

    prime: Uint32 = Field(description="Liczba pierwsza p; sprawdzana przez CryptoCore.")
    generator: Uint32 = Field(description="2 <= g < p; pierwotność nie jest sprawdzana.")
    alice_secret: Uint32 = Field(description="Dodatni sekret Alice; może być >= p.")
    bob_secret: Uint32 = Field(description="Dodatni sekret Boba; może być >= p.")


class DhExchangeResponse(BaseModel):
    """Wartości publiczne i sekrety obliczone niezależnie dla obu stron w C."""

    model_config = ConfigDict(json_schema_extra={"examples": [
        {"alice_public": 8, "bob_public": 19, "alice_shared_key": 2, "bob_shared_key": 2}
    ]})

    alice_public: Uint32 = Field(description="A = g^a mod p")
    bob_public: Uint32 = Field(description="B = g^b mod p")
    alice_shared_key: Uint32 = Field(description="K_A = B^a mod p")
    bob_shared_key: Uint32 = Field(description="K_B = A^b mod p")
