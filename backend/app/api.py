"""Trasy HTTP backendu RADH."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends

from .crypto_core import CryptoCore
from .models import ErrorResponse, RsaEncryptRequest, RsaEncryptResponse


router = APIRouter(prefix="/api/v1/rsa", tags=["RSA"])


@lru_cache(maxsize=1)
def get_crypto_core() -> CryptoCore:
    """Załaduj jedną instancję bezstanowej biblioteki dla procesu backendu."""

    return CryptoCore()


@router.post(
    "/demo/encrypt",
    response_model=RsaEncryptResponse,
    summary="Edukacyjne szyfrowanie RSA",
    description=(
        "Szyfruje pojedynczą liczbę za pomocą 32-bitowej, edukacyjnej implementacji "
        "RSA z biblioteki CryptoCore napisanej w C. Nie używać do ochrony danych."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Niepoprawne dane wejściowe"},
        500: {"model": ErrorResponse, "description": "Błąd kontraktu CryptoCore"},
        503: {"model": ErrorResponse, "description": "CryptoCore jest niedostępny"},
    },
)
def encrypt_rsa(
    request: RsaEncryptRequest,
    crypto_core: Annotated[CryptoCore, Depends(get_crypto_core)],
) -> RsaEncryptResponse:
    ciphertext = crypto_core.encrypt(
        request.message,
        request.public_key.e,
        request.public_key.n,
    )
    return RsaEncryptResponse(ciphertext=ciphertext)
