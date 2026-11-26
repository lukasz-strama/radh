"""Trasy HTTP backendu RADH."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from .crypto_core import CryptoCore
from .coordinator_http import runtime
from .models import (
    DhExchangeRequest, DhExchangeResponse, DhParametersResponse,
    ErrorResponse, RsaEncryptRequest, RsaEncryptResponse,
    RsaKeygenRequest, RsaKeygenResponse, RsaParametersResponse,
)
from .parameter_generation import generate_dh_parameters, generate_rsa_parameters


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


@router.post(
    "/demo/parameters",
    response_model=RsaParametersResponse,
    summary="Losowanie parametrów RSA",
    description=(
        "Losuje przez secrets dwie różne, 16-bitowe liczby pierwsze oraz "
        "wykładnik publiczny. Komplet jest zatwierdzany przez RSA keygen CryptoCore. "
        "Odpowiedź nie zawiera prywatnego wykładnika ani phi."
    ),
    responses={
        429: {"model": ErrorResponse, "description": "Przekroczono limit żądań"},
        500: {"model": ErrorResponse, "description": "Błąd kontraktu CryptoCore"},
        503: {"model": ErrorResponse, "description": "Brak zasobów, prób lub CryptoCore"},
    },
)
def random_rsa_parameters(
    http_request: Request,
    crypto_core: Annotated[CryptoCore, Depends(get_crypto_core)],
) -> RsaParametersResponse:
    rt = runtime(http_request)
    with rt.parameter_generation_slot():
        result = generate_rsa_parameters(
            crypto_core, rt.settings.parameter_generation_max_attempts
        )
    return RsaParametersResponse(p=result.p, q=result.q, e=result.e)


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


@dh_router.post(
    "/demo/parameters",
    response_model=DhParametersResponse,
    summary="Losowanie parametrów Diffiego–Hellmana",
    description=(
        "Losuje przez secrets 16-bitową liczbę pierwszą p i generator g o "
        "pełnym rzędzie p - 1. Komplet jest zatwierdzany przez CryptoCore."
    ),
    responses={
        429: {"model": ErrorResponse, "description": "Przekroczono limit żądań"},
        500: {"model": ErrorResponse, "description": "Błąd kontraktu CryptoCore"},
        503: {"model": ErrorResponse, "description": "Brak zasobów, prób lub CryptoCore"},
    },
)
def random_dh_parameters(
    http_request: Request,
    crypto_core: Annotated[CryptoCore, Depends(get_crypto_core)],
) -> DhParametersResponse:
    rt = runtime(http_request)
    with rt.parameter_generation_slot():
        result = generate_dh_parameters(
            crypto_core, rt.settings.parameter_generation_max_attempts
        )
    return DhParametersResponse(prime=result.prime, generator=result.generator)
