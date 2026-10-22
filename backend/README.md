# Backend RADH

Backend udostępnia demonstracyjne szyfrowanie RSA i wymianę DH przez FastAPI. Obliczenia są
wykonywane przez bibliotekę CryptoCore napisaną w C, ładowaną przez `ctypes`.
Python nie zawiera zastępczej implementacji RSA ani DH.

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
  -d '{"message":65,"public_exponent":17,"modulus":3233}'
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


## Wymiana kluczy DH — kontrakt API (#13, #29)

`POST /api/v1/dh/demo/exchange` przyjmuje dokładnie cztery wymagane pola:
`prime`, `generator`, `alice_secret`, `bob_secret`. Każde musi być liczbą
całkowitą JSON w zakresie `0..4294967295`; ciągi, liczby zmiennoprzecinkowe,
wartości logiczne, `null` i dodatkowe pola są odrzucane (422, `INVALID_REQUEST`).

CryptoCore sprawdza kolejno: pierwszość `prime`, `2 <= generator < prime`,
dodatniość obu sekretów. Sekrety mogą być >= `prime`, aż do `4294967295`.
Pierwotność generatora nie jest sprawdzana, wynik równy 1 jest dozwolony.
`prime=2` nie ma dopuszczalnego generatora. Błędy matematyczne zwracają HTTP 422
z kodem `INVALID_PRIME`, `INVALID_GENERATOR` albo `INVALID_SECRET`.
Nieznany status C lub niepoprawny wskaźnik oznacza 500 (`INTERNAL_ERROR`),
a brak, uszkodzenie lub stara biblioteka bez symbolu DH: 503
(`CRYPTO_CORE_UNAVAILABLE`). Po aktualizacji przebuduj C i zrestartuj backend.

```sh
curl --fail-with-body http://127.0.0.1:8000/api/v1/dh/demo/exchange \
  -H 'Content-Type: application/json' \
  -d '{"prime":23,"generator":5,"alice_secret":6,"bob_secret":15}'
```

Odpowiedź HTTP 200 (nazwy pól zgodne z kontraktem w #13):

```json
{"alice_public":8,"bob_public":19,"alice_shared_key":2,"bob_shared_key":2}
```

`alice_public = g^a mod p`, `bob_public = g^b mod p`,
`alice_shared_key = B^a mod p`, `bob_shared_key = A^b mod p`.
Wszystkie cztery wyniki są obliczane przez C, nie przez Python.
Jest to demonstracja 32-bitowa, bez uwierzytelniania i ochrony przed MITM;
nie służy do zabezpieczania rzeczywistych danych.

W Swagger UI (`/docs`) rozwiń **DH**, wybierz **Try it out** i **Execute**.
Przykład jest wypełniony powyższymi parametrami. Schematy wejścia, wyjścia oraz
błędów są dostępne także pod `/openapi.json`. Endpoint RSA pozostaje dostępny.
