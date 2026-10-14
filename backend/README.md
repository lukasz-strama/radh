# Backend RADH

Backend udostępnia demonstracyjne szyfrowanie RSA przez FastAPI. Obliczenia są
wykonywane przez bibliotekę CryptoCore napisaną w C, ładowaną przez `ctypes`.
Python nie zawiera zastępczej implementacji RSA.

> **Uwaga:** jest to edukacyjne, 32-bitowe RSA bez paddingu. Nie używaj go do
> ochrony prawdziwych danych.

## Wymagania

- Python 3.11 lub nowszy,
- CMake 3.20 lub nowszy,
- kompilator obsługujący C11.

## Uruchomienie

Polecenia wykonuj z katalogu głównego repozytorium.

1. Zbuduj CryptoCore:

   ```sh
   cmake -S crypto-core -B crypto-core/build
   cmake --build crypto-core/build
   ```

2. Utwórz środowisko i zainstaluj zależności:

   ```sh
   python3 -m venv backend/.venv
   source backend/.venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r backend/requirements.txt
   ```

   W PowerShell aktywacja środowiska wygląda tak:

   ```powershell
   backend\.venv\Scripts\Activate.ps1
   ```

3. Uruchom API:

   ```sh
   cd backend
   uvicorn app.main:app --reload
   ```

Dokumentacja interaktywna będzie dostępna pod adresem
<http://127.0.0.1:8000/docs>.

Biblioteka jest domyślnie szukana w `crypto-core/build` oraz w podkatalogach
konfiguracji CMake (`Debug`, `Release`, `RelWithDebInfo`, `MinSizeRel`).
Niestandardową ścieżkę można wskazać zmienną `RADH_CRYPTO_CORE_LIBRARY`:

```sh
export RADH_CRYPTO_CORE_LIBRARY=/pełna/ścieżka/libradh_crypto_core.dylib
```

## Przykładowe żądanie

```sh
curl -X POST http://127.0.0.1:8000/api/v1/rsa/demo/encrypt \
  -H 'Content-Type: application/json' \
  -d '{"message":65,"public_key":{"n":3233,"e":17}}'
```

Odpowiedź:

```json
{"ciphertext":2790}
```

Niepoprawne dane zwracają kontrolowany błąd, na przykład:

```json
{
  "error": {
    "code": "MESSAGE_OUT_OF_RANGE",
    "message": "Wiadomość musi być mniejsza od modułu."
  }
}
```
