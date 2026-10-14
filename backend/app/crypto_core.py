"""Adapter ctypes do biblioteki CryptoCore napisanej w C."""

from __future__ import annotations

import ctypes
import os
import sys
from enum import IntEnum
from pathlib import Path


UINT32_MAX = 2**32 - 1
LIBRARY_ENV_VAR = "RADH_CRYPTO_CORE_LIBRARY"


class CryptoCoreStatus(IntEnum):
    """Kody statusu będące częścią ABI CryptoCore."""

    OK = 0
    INVALID_POINTER = 1
    INVALID_MODULUS = 2
    INVALID_EXPONENT = 3
    INVALID_MESSAGE = 4


class CryptoCoreLoadError(RuntimeError):
    """Biblioteka współdzielona nie może zostać odnaleziona lub załadowana."""


class CryptoCoreInputError(ValueError):
    """Argument adaptera nie mieści się w typie uint32_t."""


class CryptoCoreCallError(RuntimeError):
    """CryptoCore odrzucił wywołanie i zwrócił kod błędu."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


_STATUS_ERRORS = {
    CryptoCoreStatus.INVALID_POINTER: (
        "INTERNAL_ERROR",
        "Backend przekazał niepoprawny wskaźnik wyniku.",
    ),
    CryptoCoreStatus.INVALID_MODULUS: (
        "INVALID_MODULUS",
        "Moduł musi być co najmniej równy 2.",
    ),
    CryptoCoreStatus.INVALID_EXPONENT: (
        "INVALID_EXPONENT",
        "Wykładnik publiczny musi być większy od 0.",
    ),
    CryptoCoreStatus.INVALID_MESSAGE: (
        "MESSAGE_OUT_OF_RANGE",
        "Wiadomość musi być mniejsza od modułu.",
    ),
}


def _library_names() -> tuple[str, ...]:
    if sys.platform == "darwin":
        return ("libradh_crypto_core.dylib",)
    if sys.platform == "win32":
        return ("radh_crypto_core.dll", "libradh_crypto_core.dll")
    return ("libradh_crypto_core.so",)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_library_path() -> Path:
    """Znajdź bibliotekę z konfiguracji lub standardowego katalogu CMake."""

    configured_path = os.environ.get(LIBRARY_ENV_VAR)
    if configured_path:
        path = Path(configured_path).expanduser().resolve()
        if path.is_file():
            return path
        raise CryptoCoreLoadError(
            f"Plik wskazany przez {LIBRARY_ENV_VAR} nie istnieje: {path}"
        )

    build_directory = _repository_root() / "crypto-core" / "build"
    configurations = (
        Path(),
        Path("Debug"),
        Path("Release"),
        Path("RelWithDebInfo"),
        Path("MinSizeRel"),
    )
    candidates = [
        build_directory / configuration / name
        for configuration in configurations
        for name in _library_names()
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()

    searched = ", ".join(str(path) for path in candidates)
    raise CryptoCoreLoadError(
        "Nie znaleziono zbudowanej biblioteki CryptoCore. "
        "Zbuduj ją zgodnie z backend/README.md albo ustaw "
        f"{LIBRARY_ENV_VAR}. Sprawdzone ścieżki: {searched}"
    )


def _require_uint32(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CryptoCoreInputError(f"{name} musi być liczbą całkowitą.")
    if not 0 <= value <= UINT32_MAX:
        raise CryptoCoreInputError(f"{name} musi mieścić się w zakresie uint32.")


class CryptoCore:
    """Cienka, bezstanowa nakładka na publiczne ABI CryptoCore."""

    def __init__(self, library_path: Path | str | None = None) -> None:
        path = Path(library_path).resolve() if library_path else resolve_library_path()
        try:
            library = ctypes.CDLL(str(path))
        except OSError as exc:
            raise CryptoCoreLoadError(
                f"Nie można załadować CryptoCore z {path}: {exc}"
            ) from exc

        try:
            encrypt = library.radh_rsa_encrypt_u32
        except AttributeError as exc:
            raise CryptoCoreLoadError(
                "Biblioteka CryptoCore nie eksportuje funkcji radh_rsa_encrypt_u32."
            ) from exc

        encrypt.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        encrypt.restype = ctypes.c_int
        self._library = library
        self._encrypt = encrypt

    def encrypt(self, message: int, public_exponent: int, modulus: int) -> int:
        """Wywołaj C: message^public_exponent mod modulus."""

        _require_uint32("message", message)
        _require_uint32("public_exponent", public_exponent)
        _require_uint32("modulus", modulus)

        ciphertext = ctypes.c_uint32()
        raw_status = self._encrypt(
            ctypes.c_uint32(message),
            ctypes.c_uint32(public_exponent),
            ctypes.c_uint32(modulus),
            ctypes.byref(ciphertext),
        )
        try:
            status = CryptoCoreStatus(raw_status)
        except ValueError as exc:
            raise CryptoCoreCallError(
                raw_status,
                "INTERNAL_ERROR",
                f"CryptoCore zwrócił nieznany kod statusu: {raw_status}.",
            ) from exc

        if status is CryptoCoreStatus.OK:
            return ciphertext.value

        code, message = _STATUS_ERRORS[status]
        raise CryptoCoreCallError(int(status), code, message)
