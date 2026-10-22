# RADH - RSA & Diffie-Hellman Demonstrator

**RADH** to demonstrator kryptosystemu RSA oraz wymiany kluczy Diffiego–Hellmana, realizowany w ramach przedmiotu *Podstawy kryptografii i kodowania*.

## Cel projektu

Celem jest stworzenie aplikacji edukacyjnej umożliwiającej poznanie zasad działania algorytmów RSA i Diffiego–Hellmana, wizualizację obliczeń kryptograficznych oraz przeprowadzanie eksperymentów związanych z bezpieczeństwem komunikacji.

## Zasady współpracy

Konwencje językowe, zasady branchowania, commitowania i tworzenia Pull Requestów znajdują się w pliku [CONTRIBUTING.md](CONTRIBUTING.md).

## Dostępne komponenty

- [`crypto-core/`](crypto-core/) – edukacyjne operacje kryptograficzne w C11.
- [`backend/`](backend/) – API FastAPI integrujące Python z CryptoCore przez `ctypes`.
- [`frontend/`](frontend/) – interfejs React + TypeScript + Vite.

Obecnie można zaszyfrować pojedynczą liczbę za pomocą edukacyjnego RSA.
Formularz wysyła dane do backendu, który wykonuje obliczenia w bibliotece C.

## Wymagania

- Kompilator C11, np. GCC lub Clang, oraz Make lub Ninja.
- CMake 3.20 lub nowszy.
- Python 3.11 lub nowszy z modułami `venv` i `pip`.
- Node.js 20.19+ lub 22.12+ oraz `npm`.

Poniższe polecenia są przeznaczone dla Linux/macOS (Bash lub Zsh).
Zacznij w katalogu głównym sklonowanego repozytorium `radh`.

## Przygotowanie i kompilacja

### 1. Biblioteka C

```sh
cmake -S crypto-core -B crypto-core/build
cmake --build crypto-core/build
ctest --test-dir crypto-core/build --output-on-failure
```

Powstanie `crypto-core/build/libradh_crypto_core.so` na Linuxie lub
`crypto-core/build/libradh_crypto_core.dylib` na macOS. Backend automatycznie
szuka biblioteki w tym katalogu. Po zmianie kodu C wykonaj ponownie budowanie
i testy, a następnie zrestartuj backend, aby załadował nową bibliotekę.

### 2. Zależności backendu

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Polecenia korzystają bezpośrednio z interpretera środowiska wirtualnego,
więc nie wymagają jego aktywacji. Po zmianie `backend/requirements.txt`
powtórz instalację zależności.

### 3. Zależności i kompilacja frontendu

```sh
npm --prefix frontend ci
npm --prefix frontend run build
npm --prefix frontend run lint
```

`npm ci` instaluje wersje zapisane w `frontend/package-lock.json`; wykonaj je
ponownie po zmianie zależności. `build` sprawdza typy TypeScript i zapisuje
zbudowany frontend w `frontend/dist/`, a `lint` sprawdza kod.

## Uruchomienie całego projektu lokalnie

Uruchom dwa terminale w katalogu głównym repozytorium. Biblioteka C jest
ładowana przez backend i nie wymaga osobnego procesu.

### Terminal 1 — backend

```sh
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

API działa pod adresem <http://127.0.0.1:8000>, a dokumentacja Swagger pod
<http://127.0.0.1:8000/docs>.

### Terminal 2 — frontend

```sh
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Otwórz <http://127.0.0.1:5173/>. Vite przekierowuje żądania `/api/...` do
backendu na porcie `8000`, a backend wywołuje bibliotekę C przez `ctypes`.
Oba terminale muszą pozostać uruchomione; `Ctrl+C` zatrzymuje dany serwer.
Przy kolejnych uruchomieniach wystarczą te dwa polecenia, jeśli kod C
i zależności się nie zmieniły.

Ten sposób uruchomienia korzysta z serwera deweloperskiego Vite.
Wdrożenie plików z `frontend/dist/` wymaga serwera obsługującego pliki statyczne
oraz przekierowania `/api/...` do backendu.

## Sprawdzenie integracji

W formularzu wpisz `m = 65`, `e = 17`, `n = 3233` i kliknij **Szyfruj**.
Oczekiwany szyfrogram to **2790**.

Możesz również wysłać żądanie przez proxy frontendu z trzeciego terminala:

```sh
curl --fail-with-body http://127.0.0.1:5173/api/v1/rsa/demo/encrypt \
  -H 'Content-Type: application/json' \
  -d '{"message":65,"public_exponent":17,"modulus":3233}'
```

Oczekiwana odpowiedź:

```json
{"ciphertext":2790}
```


Backend obsługuje również `POST /api/v1/dh/demo/exchange`. Wymianę DH można
wykonać przez Swagger UI pod <http://127.0.0.1:8000/docs>; przykład żądania,
wynik `A=8, B=19, K=2` i kontrakt znajdują się w
[backend/README.md](backend/README.md#wymiana-kluczy-dh--kontrakt-api-13-29).
