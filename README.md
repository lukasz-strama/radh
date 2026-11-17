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
- [`nodes/`](nodes/README.md) – niezależne procesy Alice i Bob z lokalnym interfejsem DH.

Obecnie można zaszyfrować pojedynczą liczbę za pomocą edukacyjnego RSA.
Formularz wysyła dane do backendu, który wykonuje obliczenia w bibliotece C.

## Wymagania

- Kompilator C11, np. GCC lub Clang, oraz Make lub Ninja.
- CMake 3.20 lub nowszy.
- Python 3.11 lub nowszy z modułami `venv` i `pip`.
- Node.js 20.19+ lub 22.12+ oraz `npm`.

Poniższe polecenia są przeznaczone dla Linux/macOS (Bash lub Zsh).
Zacznij w katalogu głównym sklonowanego repozytorium `radh`.

## Cały aktualny system przez Docker Compose (lokalnie)

Wymagany Docker Engine z Compose v2.20+ (lub nowszym zgodnym pluginem) i dostępem
użytkownika do demona. Z katalogu głównego repozytorium:

```sh
test -f .env || cp .env.example .env
docker compose config --quiet
docker compose build
docker compose up -d --wait
```

Otwórz <http://127.0.0.1:8080>. Jeden reverse proxy serwuje produkcyjny build
React i przekazuje API do jednego FastAPI. Alice, Bob i Mallory są trzema
osobnymi procesami/kontenerami. Nie trzeba uruchamiać ich dodatkowo w terminalach.
Biblioteka C jest kompilowana i testowana w builderze; CMake/Python/Node nie
muszą być instalowane na hoście. Pierwszy build wymaga pobrania obrazów i pakietów.

```sh
# Stan, logi i szybka kontrola API
docker compose ps
docker compose logs --tail=100 -f web backend alice bob mallory
curl --fail http://127.0.0.1:8080/api/v1/dh/nodes
curl --fail http://127.0.0.1:8080/api/v1/rsa/demo/keygen \
   -H 'Content-Type: application/json' -d '{"p":61,"q":53,"e":17}'
```

Ręczny smoke (zwykły Python 3.11+ na hoście, bez dodatkowych pakietów):

```sh
python3 deploy/smoke.py
# Jeśli RADH_DIAGNOSTICS=1:
python3 deploy/smoke.py --diagnostics
```

Smoke tworzy własne sesje normal/MITM i zastępuje ukończoną sesję w v1;
uruchamiaj go na wolnym lokalnym środowisku. Nie wysyła żądań poza loopback.

Po zgłoszeniu heartbeatów role mają `online: true`. Brak sesji `/current` (404)
wewnątrz backendu przed startem wymiany jest normalny. UI pozwala utworzyć sesję
normal lub MITM. Przy domyślnym losowaniu sekretów wyniki K nie są stałym wektorem.
Aby pokazywać K edukacyjnie w UI, ustaw w `.env` `RADH_DIAGNOSTICS=1` i wykonaj
`docker compose up -d`; domyślnie K pozostają w procesach.
Nie przekazuj prawdziwych kluczy ani danych poufnych.

```sh
# Zatrzymanie i ponowny start (bez przebudowy)
docker compose stop
docker compose start
# Usunięcie kontenerów i sieci; ulotne sesje giną
docker compose down
# Przebudowa po zmianach kodu/biblioteki/dependencji
docker compose build --pull
docker compose up -d --wait
```

Zmiana `RADH_HTTP_PORT` w `.env` zmienia tylko port loopback. Nie publikuj tego
Compose w Internecie: obecny system ma jedną globalną sesję i nie ma auth/TLS
publicznej bety. Compose nie implementuje wielosesyjności z #68–71.
Healthcheck `unhealthy` wymaga diagnozy (`docker compose logs`); sama polityka
restart nie restartuje działającego, lecz zawieszonego procesu. Restart backendu
lub węzła wymaga rozpoczęcia nowej sesji. Starych sekretów nie da się odzyskać.

Architektura i konfiguracja: [deployment](docs/architecture/deployment.md).
Kontrakt dla zespołu: [multi-session](docs/architecture/multi-session.md).
Bezpieczeństwo: [model STRIDE](docs/security/threat-model.md) i
[warunki publikacji](docs/security/release-gate.md). Wyniki rzeczywiście wykonanej
weryfikacji: [verification](docs/architecture/verification.md).

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

Uruchom backend i frontend w osobnych terminalach w katalogu głównym repozytorium. Biblioteka C jest
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
Do wymiany DH uruchom też po jednym procesie HTTP Alice, Boba i Mallory
(polecenia poniżej). Wszystkie terminale muszą pozostać uruchomione; `Ctrl+C` zatrzymuje dany serwer.
Przy kolejnych uruchomieniach powtórz polecenia backendu, frontendu i potrzebnych
węzłów, jeśli kod C i zależności się nie zmieniły.

### Dodatkowe terminale — procesy DH

Każde polecenie uruchom w osobnym terminalu (do RSA wystarczą backend i frontend):

```sh
backend/.venv/bin/python -m backend.dh_transport --role alice
backend/.venv/bin/python -m backend.dh_transport --role bob
backend/.venv/bin/python -m backend.dh_transport --role mallory
```

Dodaj `--allow-diagnostics` do odpowiednich poleceń, aby jawnie pokazać K w UI.
Samo `python -m nodes` uruchamia lokalne JSON Lines, bez heartbeatów HTTP.

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
