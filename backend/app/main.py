"""Punkt wejścia aplikacji FastAPI."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import router
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
        "API demonstratora RSA i Diffiego–Hellmana. Obecny endpoint RSA korzysta "
        "z edukacyjnej biblioteki CryptoCore w C i nie zapewnia bezpieczeństwa "
        "kryptograficznego."
    ),
)
app.include_router(router)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
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
    }:
        return _error_response(422, exception.code, exception.message)
    logger.error(
        "Błąd kontraktu CryptoCore (status=%s): %s", exception.status, exception
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
    logger.error("Nie można uruchomić CryptoCore: %s", exception)
    return _error_response(
        503,
        "CRYPTO_CORE_UNAVAILABLE",
        "Biblioteka CryptoCore jest niedostępna.",
    )
