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

## Cały system przez Docker Compose v2 (Fedora Linux, lokalnie)

Wymagany rootful Docker Engine z działającym `sudo docker compose` i Python 3.11+.
Z katalogu repozytorium:

```sh
test -f .env || cp .env.example .env
sudo python3 deploy/init_secrets.py
sudo docker compose config --quiet
sudo docker compose build
sudo docker compose run --rm --no-deps web -t
sudo docker compose up -d --wait
sudo docker compose ps
```

Otwórz <http://127.0.0.1:8080> lub <http://localhost:8080>. Pięć usług to web
(Nginx + React), backend (jeden Uvicorn + CryptoCore) i niezależne procesy
Alice/Bob/Mallory korzystające wyłącznie z internal API. UI używa DH v2;
`RADH_LEGACY_API_ENABLED=false` wyłącza stare sesje i heartbeat v1. `/current`
nie jest dostępne. RSA/keygen i matematyczne demo DH zachowują endpointy v1.

Inicjalizator tworzy trzy niezależne tokeny w ignorowanym `.local/secrets/`.
Nie nadpisuje istniejących. Root jest wymagany do ustawienia UID/GID 10001,
trybu plików 0400 i katalogu root:root 0700. Backend ma trzy read-only bindy,
a każdy węzeł tylko własny. Web/front nie otrzymują tokenów. Compose nie zmienia
właściciela plików za nas; runtime healthcheck sprawdza UID/GID/tryb/odczyt i
read-only mount. SELinux na Fedorze: inicjalizator jawnie nadaje trzem plikom
współdzieloną etykietę `container_file_t:s0`, także dla istniejących tokenów.
Pozostawiono bind `selinux: z`, ale Compose 5.6 może pominąć tę opcję przy
`create_host_path: false`; nie polegamy na niej jako jedynym relabelowaniu.
Wariant rootless Docker wymaga osobnego uzgodnienia mapowania UID, nie jest
obsługiwany przez ten skrypt. Nie stosuj chmod 644 ani wyłączania SELinux.

```sh
sudo docker compose logs --tail=100 web backend alice bob mallory
python3 deploy/smoke.py
# Osobna próba: jawny lokalny opt-in węzłów; w UI dodatkowo zaznacz zgodę na K.
RADH_DIAGNOSTICS=1 sudo --preserve-env=RADH_DIAGNOSTICS docker compose up -d --wait
python3 deploy/smoke.py --diagnostics
# Powrót do konfiguracji .env (domyślnie diagnostyka wyłączona):
sudo docker compose up -d --wait
```

Smoke używa rzeczywistych usług na loopback, tworzy własne sesje normal/MITM,
sprawdza auth, idempotencję, diagnostykę i DELETE. Respektuje 429/Retry-After;
może czekać na budżet create (6/min, burst 2). Sprząta wyłącznie własne sesje.
Równoległe starty nie są automatycznie dowodem nakładania stanów running —
skrypt raportuje, czy rzeczywiście je zaobserwował. Nie wypisuje tokenów ani K.

W `.env` zmień `RADH_HTTP_PORT`, np. 18080, i odtwórz usługi. Port oraz oba
`RADH_ALLOWED_ORIGINS` są wyprowadzane z tej samej wartości. Smoke uruchom wtedy
z `--url http://127.0.0.1:18080`. Domyślna prywatna podsieć 172.30.87.0/24
musi być wolna na hoście/VPN; przy zmianie ustaw zgodnie RADH_SERVICES_SUBNET
i RADH_PROXY_IP. Backend ufa XFF wyłącznie z dokładnego IP web, nie z całej sieci.

```sh
sudo docker compose stop
sudo docker compose start
sudo docker compose down  # usuwa kontenery/sieci; pliki tokenów pozostają
sudo docker compose build --pull
sudo docker compose up -d --wait
```

Restart backendu usuwa ulotne sesje i zmienia epoch. Węzły rejestrują się ponownie;
jeżeli stracą lease, kończą proces i polityka restart uruchamia nową instancję.
Sekretów DH nie można odtworzyć; utwórz nowe sesje. Unhealthy nie oznacza
automatycznego restartu działającego procesu: sprawdź logi i `docker compose ps`.
Brak tokenów blokuje mount/start, błędne uprawnienia blokują healthcheck. Po zmianie
kodu/config Nginx przebuduj obrazy, sam restart nie kopiuje plików z hosta.

Szczegóły i polecenia weryfikacyjne: [wdrożenie](docs/architecture/deployment.md)
i [wyniki testów](docs/architecture/verification.md). **Publiczna beta: NO-GO**
do spełnienia [release gate](docs/security/release-gate.md). To edukacyjna
kryptografia 32-bitowa, bez produkcyjnego TLS w Compose; nie publikuj tego portu.


## Demo na iPhonie przez Wi-Fi — dwóch użytkowników

Telefon i komputer muszą być w tej samej zaufanej sieci Wi-Fi. Dodatkowy plik
`compose.lan.yaml` zachowuje localhost i dodaje wyłącznie wskazany adres LAN
oraz odpowiadający mu Origin. Domyślny `compose.yaml` nadal jest tylko lokalny.

Przykład dla komputera 192.168.1.30 (aktualny adres sprawdź `ip -4 -brief address`):

```sh
sudo env RADH_LAN_IP=192.168.1.30 docker compose -f compose.yaml -f compose.lan.yaml up -d --wait
```

Na iPhonie otwórz Safari: **http://192.168.1.30:8080**. Na komputerze możesz
pozostać przy http://localhost:8080. Każde urządzenie ma własne poświadczenie
sesji. Uruchom normal na komputerze i MITM na telefonie; Reset telefonu powinien
usunąć wyłącznie jego sesję. Najlepiej przygotować oba formularze i rozpocząć
wymiany jednocześnie. Nie wysyłaj drugiemu użytkownikowi tokenu, wystarczy adres.

Włączenie wariantu LAN odtwarza backend ze zmienioną listą Origin — dotychczasowe
ulotne sesje znikną. Utwórz nowe. Nie potrzeba przebudowy obrazu. Dla jawnego
raportowania K dodaj `RADH_DIAGNOSTICS=1` po `sudo env` i zaznacz opt-in w UI.
Po demonstracji usuń nasłuchiwanie LAN:

```sh
sudo docker compose -f compose.yaml up -d --wait
```

Jeżeli telefon nie łączy: sprawdź adres komputera, wspólną sieć Wi-Fi i wyłączoną
izolację klientów/tryb sieci gościnnej. Sprawdź najpierw ten sam adres LAN w
przeglądarce komputera. Nie wyłączaj SELinux ani firewalla. Wariant służy demo
w zaufanej LAN przez HTTP; nie przekierowuj portu na routerze. Publiczna beta
pozostaje NO-GO. Szczegóły: [wdrożenie — LAN](docs/architecture/deployment.md#demo-lan).

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

## Ręczne uruchomienie poza Compose (historyczny demonstrator v1)

**Uwaga:** poniższe polecenia procesów DH dotyczą historycznego v1 i nie
obsługują obecnego UI v2. Do pełnej aplikacji użyj Compose powyżej.
Ręczne uruchomienie v2 opisano w backend/MULTI_SESSION.md oraz nodes/MULTI_SESSION.md.

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
