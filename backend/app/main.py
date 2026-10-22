"""Punkt wejścia aplikacji FastAPI."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .api import dh_router, router
from .crypto_core import (
    CryptoCoreCallError,
    CryptoCoreInputError,
    CryptoCoreLoadError,
)


logger = logging.getLogger(__name__)

app = FastAPI(
    title="RADH API",
    version="0.1.0",
    description=(
        "API demonstratora RSA i Diffiego–Hellmana. Endpointy RSA i DH korzystają "
        "z edukacyjnej biblioteki CryptoCore w C i nie zapewniają bezpieczeństwa "
        "kryptograficznego."
    ),
)
app.include_router(router)
app.include_router(dh_router)


def _error_response(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error(
    _request: Request, _exception: RequestValidationError
) -> JSONResponse:
    return _error_response(422, "INVALID_REQUEST", "Niepoprawne dane wejściowe.")


@app.exception_handler(CryptoCoreInputError)
async def adapter_input_error(
    _request: Request, exception: CryptoCoreInputError
) -> JSONResponse:
    return _error_response(422, "INVALID_REQUEST", str(exception))


@app.exception_handler(CryptoCoreCallError)
async def crypto_core_call_error(
    _request: Request, exception: CryptoCoreCallError
) -> JSONResponse:
    if exception.code in {
        "INVALID_MODULUS",
        "INVALID_EXPONENT",
        "MESSAGE_OUT_OF_RANGE",
        "INVALID_PRIME",
        "INVALID_GENERATOR",
        "INVALID_SECRET",
    }:
        return _error_response(422, exception.code, exception.message)
    logger.error(
        "CryptoCore contract violation (status=%s): %s", exception.status, exception
    )
    return _error_response(
        500,
        "INTERNAL_ERROR",
        "CryptoCore zwrócił nieoczekiwany błąd.",
    )


@app.exception_handler(CryptoCoreLoadError)
async def crypto_core_load_error(
    _request: Request, exception: CryptoCoreLoadError
) -> JSONResponse:
    logger.error("Cannot load CryptoCore: %s", exception)
    return _error_response(
        503,
        "CRYPTO_CORE_UNAVAILABLE",
        "Biblioteka CryptoCore jest niedostępna.",
    )


_HTTP_ERRORS = {
    400: ("BAD_REQUEST", "Nie można odczytać żądania."),
    404: ("NOT_FOUND", "Nie znaleziono zasobu."),
    405: ("METHOD_NOT_ALLOWED", "Metoda HTTP jest niedozwolona dla tego zasobu."),
}


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exception: HTTPException) -> JSONResponse:
    """Wspólny format błędów HTTP, także generowanych przez router Starlette."""

    code, message = _HTTP_ERRORS.get(
        exception.status_code,
        (f"HTTP_{exception.status_code}", "Nie można obsłużyć żądania."),
    )
    return _error_response(
        exception.status_code, code, message, headers=exception.headers,
    )
