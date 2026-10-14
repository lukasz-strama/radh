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
