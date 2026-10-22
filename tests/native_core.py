import ctypes
import os
import sys
from pathlib import Path

LIBRARY_ENV_VAR = "RADH_CRYPTO_CORE_LIBRARY"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HEADER_PATH = REPOSITORY_ROOT / "crypto-core" / "include" / "radh_crypto_core.h"

SENTINEL = 0xA5A5A5A5

# Kody statusu z radh_crypto_core.h
STATUS = {
    "OK": 0,
    "INVALID_POINTER": 1,
    "INVALID_MODULUS": 2,
    "INVALID_EXPONENT": 3,
    "INVALID_MESSAGE": 4,
    "INVALID_PRIME": 5, 
    "INVALID_GENERATOR": 6,
    "INVALID_SECRET": 7,
}

def _library_names():
    if sys.platform == "darwin":
        return ["libradh_crypto_core.dylib"]
    if sys.platform == "win32":
        return ["radh_crypto_core.dll", "libradh_crypto_core.dll"]
    return ["libradh_crypto_core.so"]

def find_library():
    """Zwraca ścieżkę do zbudowanej biblioteki lub zgłasza błąd."""
    configured = os.environ.get(LIBRARY_ENV_VAR)
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{LIBRARY_ENV_VAR} wskazuje nieistniejący plik: {path}")
        return path

    build_dir = REPOSITORY_ROOT / "crypto-core" / "build"
    for config in ("", "Debug", "Release", "RelWithDebInfo", "MinSizeRel"):
        for name in _library_names():
            path = build_dir / config / name
            if path.is_file():
                return path.resolve()

    raise FileNotFoundError(
        "Nie znaleziono biblioteki CryptoCore."
    )

class NativeCore:

    def __init__(self, path):
        self.path = Path(path)
        self._lib = ctypes.CDLL(str(self.path))
        for name in ("radh_modexp_u32", "radh_rsa_encrypt_u32"):
            function = getattr(self._lib, name)
            function.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            function.restype = ctypes.c_int

    def _call(self, function, a, b, c, initial):
        output = ctypes.c_uint32(initial)
        status = function(a, b, c, ctypes.byref(output))
        return status, output.value

    def modexp(self, base, exponent, modulus, initial=SENTINEL):
        """Zwraca (status, wynik). Wynik = initial, jeśli funkcja zgłosiła błąd."""
        return self._call(self._lib.radh_modexp_u32, base, exponent, modulus, initial)

    def encrypt(self, message, public_exponent, modulus, initial=SENTINEL):
        """Zwraca (status, szyfrogram). Szyfrogram = initial, jeśli był błąd."""
        return self._call(
            self._lib.radh_rsa_encrypt_u32, message, public_exponent, modulus, initial
        )

    def modexp_null_output(self, base, exponent, modulus):
        """Wywołanie ze wskaźnikiem wyniku NULL. Zwraca sam status."""
        return self._lib.radh_modexp_u32(base, exponent, modulus, None)

    def encrypt_null_output(self, message, public_exponent, modulus):
        """Wywołanie ze wskaźnikiem wyniku NULL. Zwraca sam status."""
        return self._lib.radh_rsa_encrypt_u32(message, public_exponent, modulus, None)
