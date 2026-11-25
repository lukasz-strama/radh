"""Trasy HTTP backendu RADH."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from .crypto_core import CryptoCore
from .coordinator_http import runtime
from .models import (
    DhExchangeRequest, DhExchangeResponse,
    ErrorResponse, RsaDecryptRequest, RsaDecryptResponse,
    RsaEncryptRequest, RsaEncryptResponse,
    RsaKeygenRequest, RsaKeygenResponse,
    RsaTextDecryptRequest, RsaTextDecryptResponse,
    RsaTextEncryptRequest, RsaTextEncryptResponse,
)
from .rsa_text import decrypt_text, encrypt_text


HTTP_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Nie można odczytać żądania"},
    404: {"model": ErrorResponse, "description": "Nie znaleziono zasobu"},
    405: {"model": ErrorResponse, "description": "Niedozwolona metoda HTTP"},
}
router = APIRouter(prefix="/api/v1/rsa", tags=["RSA"], responses=HTTP_ERROR_RESPONSES)
dh_router = APIRouter(prefix="/api/v1/dh", tags=["DH"], responses=HTTP_ERROR_RESPONSES)


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
        429: {"model": ErrorResponse, "description": "Przekroczono limit żądań"},
        422: {"model": ErrorResponse, "description": "Niepoprawne dane wejściowe"},
        500: {"model": ErrorResponse, "description": "Błąd kontraktu CryptoCore"},
        503: {"model": ErrorResponse, "description": "CryptoCore jest niedostępny"},
    },
)
def encrypt_rsa(
    request: RsaEncryptRequest, http_request: Request,
    crypto_core: Annotated[CryptoCore, Depends(get_crypto_core)],
) -> RsaEncryptResponse:
    with runtime(http_request).demo_slot():
        ciphertext = crypto_core.encrypt(
            request.message, request.public_exponent, request.modulus,
        )
    return RsaEncryptResponse(ciphertext=ciphertext)


@router.post(
    "/demo/decrypt",
    response_model=RsaDecryptResponse,
    summary="Edukacyjne deszyfrowanie RSA",
    description=(
        "Odzyskuje pojedynczą liczbę przez CryptoCore. Jest to textbook RSA "
        "bez paddingu, wyłącznie do demonstracji edukacyjnej."
    ),
    responses={
        429: {"model": ErrorResponse, "description": "Przekroczono limit żądań"},
        422: {"model": ErrorResponse, "description": "Niepoprawne dane wejściowe"},
        500: {"model": ErrorResponse, "description": "Błąd kontraktu CryptoCore"},
        503: {"model": ErrorResponse, "description": "CryptoCore lub kolejka są niedostępne"},
    },
)
def decrypt_rsa(
    request: RsaDecryptRequest,
    http_request: Request,
    crypto_core: Annotated[CryptoCore, Depends(get_crypto_core)],
) -> RsaDecryptResponse:
    with runtime(http_request).new_crypto_slot():
        message = crypto_core.decrypt(
            request.ciphertext, request.private_exponent, request.modulus
        )
    return RsaDecryptResponse(message=message)


@router.post(
    "/demo/text/encrypt",
    response_model=RsaTextEncryptResponse,
    summary="Szyfrowanie tekstu UTF-8 przez RSA",
    description=(
        "Koduje maksymalnie 128 bajtów UTF-8 i szyfruje każdy bajt osobnym "
        "wywołaniem CryptoCore. Wymaga modułu większego od 255. Textbook RSA "
        "bez paddingu; nie używać do ochrony danych."
    ),
    responses={
        429: {"model": ErrorResponse, "description": "Przekroczono limit żądań"},
        422: {"model": ErrorResponse, "description": "Niepoprawny tekst lub klucz"},
        500: {"model": ErrorResponse, "description": "Błąd kontraktu CryptoCore"},
        503: {"model": ErrorResponse, "description": "CryptoCore lub kolejka są niedostępne"},
    },
)
def encrypt_rsa_text(
    request: RsaTextEncryptRequest,
    http_request: Request,
    crypto_core: Annotated[CryptoCore, Depends(get_crypto_core)],
) -> RsaTextEncryptResponse:
    with runtime(http_request).new_crypto_slot():
        ciphertexts = encrypt_text(
            crypto_core, request.text, request.public_exponent, request.modulus
        )
    return RsaTextEncryptResponse(ciphertexts=ciphertexts)


@router.post(
    "/demo/text/decrypt",
    response_model=RsaTextDecryptResponse,
    summary="Deszyfrowanie tekstu UTF-8 przez RSA",
    description=(
        "Deszyfruje od 1 do 128 szyfrogramów w CryptoCore, wymaga wyniku "
        "bajtowego i odtwarza tekst przez ścisłe dekodowanie UTF-8. Textbook RSA "
        "bez paddingu; nie używać do ochrony danych."
    ),
    responses={
        429: {"model": ErrorResponse, "description": "Przekroczono limit żądań"},
        422: {"model": ErrorResponse, "description": "Niepoprawny szyfrogram, klucz lub UTF-8"},
        500: {"model": ErrorResponse, "description": "Błąd kontraktu CryptoCore"},
        503: {"model": ErrorResponse, "description": "CryptoCore lub kolejka są niedostępne"},
    },
)
def decrypt_rsa_text(
    request: RsaTextDecryptRequest,
    http_request: Request,
    crypto_core: Annotated[CryptoCore, Depends(get_crypto_core)],
) -> RsaTextDecryptResponse:
    with runtime(http_request).new_crypto_slot():
        text = decrypt_text(
            crypto_core,
            request.ciphertexts,
            request.private_exponent,
            request.modulus,
        )
    return RsaTextDecryptResponse(text=text)


@router.post(
    "/demo/keygen",
    response_model=RsaKeygenResponse,
    summary="Edukacyjne generowanie kluczy RSA",
    description=(
        "CryptoCore (C) wyznacza parę kluczy z różnych liczb pierwszych p i q "
        "oraz wykładnika e spełniającego 1 < e < phi i NWD(e, phi) = 1. "
        "Moduł musi mieścić się w uint32. Odpowiedź zawiera prywatny wykładnik d. "
        "Klucze służą wyłącznie do demonstracji edukacyjnej."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Niepoprawne dane wejściowe"},
        500: {"model": ErrorResponse, "description": "Błąd kontraktu CryptoCore"},
        503: {"model": ErrorResponse, "description": "CryptoCore lub operacja keygen są niedostępne"},
    },
)
def generate_rsa_keys(request: RsaKeygenRequest, http_request: Request) -> RsaKeygenResponse:
    # Załaduj bibliotekę dopiero po walidacji żądania.
    with runtime(http_request).demo_slot():
        result = get_crypto_core().generate_rsa_keys(request.p, request.q, request.e)
    return RsaKeygenResponse(n=result.n, e=result.e, d=result.d, phi=result.phi)


@dh_router.post(
    "/demo/exchange",
    response_model=DhExchangeResponse,
    summary="Edukacyjna wymiana kluczy Diffiego–Hellmana",
    description=(
        "Oblicza wartości publiczne i wspólny sekret obu stron w CryptoCore (C). "
        "Wszystkie parametry muszą być całkowite i mieścić się w uint32. "
        "Wymaga liczby pierwszej p, 2 <= g < p oraz dodatnich sekretów. "
        "Nie sprawdza pierwotności generatora. Wyłącznie demonstracja edukacyjna."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Niepoprawne dane wejściowe"},
        500: {"model": ErrorResponse, "description": "Błąd kontraktu CryptoCore"},
        503: {"model": ErrorResponse, "description": "CryptoCore jest niedostępny"},
    },
)
def exchange_dh(
    request: DhExchangeRequest, http_request: Request,
    crypto_core: Annotated[CryptoCore, Depends(get_crypto_core)],
) -> DhExchangeResponse:
    with runtime(http_request).demo_slot():
        result = crypto_core.exchange(
            request.prime, request.generator, request.alice_secret, request.bob_secret,
        )
    return DhExchangeResponse(
        alice_public=result.alice_public,
        bob_public=result.bob_public,
        alice_shared_key=result.alice_shared_key,
        bob_shared_key=result.bob_shared_key,
    )
