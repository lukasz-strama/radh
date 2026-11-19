# Weryfikacja integracji Compose v2 — #87

Data: 2026-11-19. Gałąź chore/87-compose-multi-session, baza
origin/feat/70-multi-session-ui = 5ca0454 (z #82, #85 i #86).
**Publiczna beta pozostaje NO-GO. Runtime Compose nie został tu potwierdzony.**

## Demo LAN — kontrola konfiguracji

Dodano jawną nakładkę compose.lan.yaml dla RADH_LAN_IP. Walidacja Compose
5.6.0 i odczyt modelu JSON: PASS dla 192.168.1.30:8080 i portu 18080; dokładnie
dwa bindy (127.0.0.1 i wskazany LAN), właściwy Origin, brak publikacji backendu,
niezmienione role/mounty/non-root/read-only. Bez zmiennej RADH_LAN_IP wariant
poprawnie odmawia walidacji. Bazowy Compose nadal udostępnia tylko loopback.
Git diff --check: PASS. Rzeczywisty dostęp Safari przez Wi-Fi: NOT RUN w środowisku
autora. Nie deklarujemy sukcesu na telefonie na podstawie config.

Użytkownik potwierdził po poprawce SELinux: wszystkie pięć usług Healthy, smoke
bez diagnostyki zaliczył allowlistę, RSA/keygen, normal i MITM, zaobserwował oba
running, autoryzację/idempotencję/izolację/brak K i cleanup. To wynik hosta
użytkownika dla wariantu localhost, nie dowód dostępności nowego wariantu LAN.
Osobna próba z RADH_DIAGNOSTICS=1 nadal wymaga potwierdzenia.

## Aktualizacja: próba na hoście Fedora i poprawka SELinux

Wyniki przekazane przez użytkownika 2026-11-19: inicjalizator, build obrazów
oraz nginx -t przeszły. Start Compose zatrzymał się na backendzie z błędem
odczytu poświadczenia Alice. Pliki miały poprawne 10001:10001/0400, ale
etykietę user_home_t:s0; alert SELinux wskazywał read procesu python.
Nie jest to zaliczenie pięciu healthy ani smoke.

Na gałęzi fix/87-selinux-secret-mounts dodano jawne chcon tylko trzech plików
w inicjalizatorze, wykonywane na SELinux także dla istniejących tokenów.
Pozostają read-only, create_host_path=false, non-root i 0400. Nie regenerujemy
tokenów ani nie wyłączamy SELinux. Przyczyna potwierdzona kodem Compose 5.6:
Mount API wymuszane przez create_host_path=false nie przenosi opcji SELinux z.

Po poprawce: 5 testów tests/test_deploy/test_secret_labels.py PASS,
składnia Pythona, Compose config i git diff --check PASS. Runtime poprawki
w środowisku autora nadal blokuje docker.sock. Na hoście wykonać:

```sh
sudo docker compose down
sudo python3 deploy/init_secrets.py
sudo ls -lZ .local/secrets
# Każdy plik ma container_file_t:s0, nadal 10001:10001 i 0400.
RADH_DIAGNOSTICS=0 sudo --preserve-env=RADH_DIAGNOSTICS docker compose up -d --force-recreate --wait
python3 deploy/smoke.py
```

Nie jest potrzebna przebudowa obrazu dla samej zmiany hostowego inicjalizatora.
Poniższa tabela zachowuje wcześniejsze wyniki ograniczonego środowiska autora;
nowy wynik użytkownika rozstrzyga powyższa sekcja.

## Rzeczywiste wyniki bieżącej zmiany

| Sprawdzenie | Wynik |
| --- | --- |
| git diff --check, składnia deploy/*.py, sh -n deploy/node-entrypoint.sh | PASS |
| docker compose config --quiet / config --format json | PASS, Compose 5.6.0 |
| Statyczna kontrola pięciu usług, mountów per rola, RO, cap_drop, PID, loopback i dokładnego IP proxy | PASS; nie dowodzi zachowania mountów runtime |
| RADH_HTTP_PORT=18080 RADH_DIAGNOSTICS=1 docker compose config | PASS: port, oba Origin i flagi wszystkich ról spójne |
| docker compose build | NOT RUN runtime — próba exit 1, permission denied na /var/run/docker.sock |
| docker compose run --rm --no-deps web -t | NOT RUN — próba exit 1, brak dostępu do demona |
| docker compose up -d --build --wait i docker compose ps | NOT RUN — obie próby exit 1, ten sam brak dostępu |
| RADH_DIAGNOSTICS=1 docker compose up -d --wait | NOT RUN — próba exit 1, brak dostępu do demona |
| python3 deploy/smoke.py oraz --diagnostics | NOT RUN scenariuszy — obie próby exit 1: środowisko blokuje otwieranie socketów |
| Inicjalizacja sekretów, UID/GID, mount RO, SELinux | NOT RUN runtime; uruchomienie inicjalizatora bez sudo poprawnie odmówiło działania, niczego nie utworzono |
| CMake configure/build, CTest | PASS, 2/2 |
| python3 -m pytest backend/tests/unit -q | PASS, 66 |
| Nowe procesy wielosesyjne i istniejące agenty (tests/test_multi_session + test_nodes + test_mallory_nodes) | PASS, 219 |
| Istniejąca regresja agentów/adaptera i natywnego RSA/DH bez serwera HTTP | PASS, 642 (zestawy się pokrywają, nie sumować) |
| timeout 60s python3 -m pytest -q -o faulthandler_timeout=15 | NOT COMPLETE, exit 124: istniejący TestClient w fixture test_sessions.api; nie ma raportu pełnego zaliczenia |
| npm test | PASS, 37 testów w 2 plikach (w tym 9 nowych przypadków regresji proxy) |
| npm run lint | PASS |
| npm run build | PASS, TypeScript i Vite 8.3.4 |
| Restart backendu i SIGTERM usług | NOT RUN runtime |

Brak vitest/oxlint/tsc na początku rozwiązano instalacją npm ci na hoście użytkownika;
instalacja offline w środowisku nie miała paczki why-is-node-running w cache.
Nie zmieniono locka ani zależności. Testy fetch są jednostkowe, nie dowodzą
uruchomienia Nginx czy wymiany przez prawdziwe kontenery. Nie dodano skip/xfail.

## Polecenia do wykonania na Fedorze z rootful Docker Engine

```sh
test -f .env || cp .env.example .env
sudo python3 deploy/init_secrets.py
sudo docker compose config --quiet
sudo docker compose build
sudo docker compose run --rm --no-deps web -t
sudo docker compose up -d --build --wait
sudo docker compose ps
# Każda sonda kontroluje faktyczne UID/GID/0400/RO i możliwość odczytu:
sudo docker compose exec -T backend python -m deploy.healthcheck backend
sudo docker compose exec -T alice python -m deploy.healthcheck node
sudo docker compose exec -T bob python -m deploy.healthcheck node
sudo docker compose exec -T mallory python -m deploy.healthcheck node
# Wyświetla wyłącznie metadane plików i etykiety, nigdy zawartość:
sudo ls -ldZ .local/secrets
sudo ls -lZ .local/secrets
```

Do kontroli mountów użyj (Compose nie ma przenośnego podpolecenia inspect):

```sh
sudo docker inspect $(sudo docker compose ps -q) --format '{{.Name}} user={{.Config.User}} readonly={{.HostConfig.ReadonlyRootfs}} mounts={{json .Mounts}}'
python3 deploy/smoke.py
RADH_DIAGNOSTICS=1 sudo --preserve-env=RADH_DIAGNOSTICS docker compose up -d --wait
python3 deploy/smoke.py --diagnostics
sudo docker compose up -d --wait
```

Smoke nie wyłącza limitów (create 6/min, burst 2), respektuje Retry-After.
Przed obiema próbami wybierz zgodną konfigurację węzłów: domyślnie .env ma
RADH_DIAGNOSTICS=0, drugi wariant powyżej jawnie ustawia 1. Dla zmienionego portu
użyj --url http://127.0.0.1:PORT. Skrypt nie wypisuje tokenów, kluczy ani K.
Sprawdza dwa osobne ID/tokeny/klucze create, retry create, auth 401/404 bez mutacji,
ukończone normal/MITM, ich wiadomości i historię, zgodność/brak diagnostyki,
DELETE jednego rekordu bez zmiany drugiego, idempotentny DELETE i cleanup finally.
Starty są wysłane równolegle. Skrypt osobno raportuje, czy w snapshotach
rzeczywiście zaobserwowano oba running; ich brak nie jest dowodem współbieżności.

Dodatkowo w dwóch kartach UI utworzyć własne sesje, odświeżyć jedną i usunąć ją
bez wpływu na drugą. Zatrzymać backend podczas aktywnej sesji, uruchomić ponownie
z nowym epoch; potwierdzić utratę starej sesji, rejestrację węzłów i nową wymianę.
Polecenia: sudo docker compose stop backend; sudo docker compose start backend;
sudo docker compose up -d --wait. Potwierdzić brak niekontrolowanych procesów
po sudo docker compose stop i poprawny start. Nie zaliczono tutaj tych scenariuszy.

Próby publicznego API (bez tokenów): /internal i /internal/health/ready →403,
/api/v1/dh/sessions/current oraz heartbeat v1 →404 NOT_FOUND proxy, wiadomości,
ACK i forward pod publicznym v2 →404, POST diagnostyki i niedozwolone metody
znanych tras →403. ID inne niż 32 małe hex →404. GET /api/v2/dh/nodes →200 z epoch.
Docs/OpenAPI/ReDoc →403. Przy wyłączonym legacy sprawdzić też niedostępność v1
bezpośrednio z sieci usług — jest to osobna kontrola wyłączenia routerów backendu.
Nie traktować 404 proxy jako dowodu wyłączenia routerów wewnątrz backendu.

## Definition of Done — stan dowodów

Potwierdzono automatycznie modele konfiguracji, regresję frontendowego epoch,
regresję C/agentów, backendowe jednostki i przygotowanie dokumentacji/CI.
Rozbieżność #68/#69 dotycząca remaining_ttl_seconds w completed jest opisana
w deployment.md; wymaga osobnego uzgodnienia retencji agenta.
Pięć healthy, rzeczywiste mounty/SELinux, RSA i normal/MITM przez proxy, auth
runtime, sygnały i restart pozostają **otwarte**, do wykonania powyższymi poleceniami.
Nie ma podstaw do oznaczenia całego #87 ani publicznego release gate jako zaliczonego.

<details>
<summary>Historyczne wyniki #73 / Compose v1 — nie dotyczą bieżącego uruchomienia v2</summary>

# Weryfikacja lokalna #73

Data: 2026-11-17. Baza: main a37d066, gałąź `chore/73-deployment-threat-model`.
Wyniki odnoszą się do środowiska autora, nie VPS i nie publicznej bety.
Nie zmieniano backendu, węzłów, CryptoCore, frontendu, testów Python ani workflow.
`RACI.md` jest śledzony i dołączony do PR #81; pozostawiono go nietkniętego.
Powinien zostać wydzielony do osobnego commita lub PR, poza zakresem #73.

## Ponowiona weryfikacja po review PR #81

Poniższe wyniki dotyczą poprawek review na bazie ee47d86. Zmieniono wyłącznie
proxy, ręczny smoke i dokumentację. **Publiczna publikacja nadal NO-GO.**

| Sprawdzenie | Rzeczywisty wynik po poprawkach |
| --- | --- |
| `docker compose config --quiet` | **OK**, Compose 5.6.0 |
| `docker compose build` | **ZABLOKOWANE**, exit 1: permission denied na `/var/run/docker.sock`; obrazów nie zbudowano |
| `docker compose run --rm --no-deps web -t` | **ZABLOKOWANE**, exit 1: ten sam brak dostępu do demona; składnia Nginx nie została potwierdzona przez Nginx |
| `docker compose up -d --wait` | **ZABLOKOWANE**, exit 1: ten sam brak dostępu; usług nie uruchomiono |
| `RADH_DIAGNOSTICS=1 docker compose up -d --wait` | **ZABLOKOWANE**, exit 1: ten sam brak dostępu |
| `python3 deploy/smoke.py` oraz `python3 deploy/smoke.py --diagnostics` | **NIEZALICZONE**, oba exit 1 na pierwszej próbie HTTP; dalsze scenariusze RSA/DH/MITM, diagnostyki i resetu nie zostały wykonane |
| `curl --noproxy '*' --max-time 3 -i http://127.0.0.1:8080/api/v1/dh/sessions/current` | **ZABLOKOWANE**, exit 7: failed to open socket: Operation not permitted; brak potwierdzenia HTTP 200/404 |
| Analogiczny curl POST `/api/v1/dh/nodes/alice/heartbeat` | **ZABLOKOWANE**, exit 7: ten sam błąd socketu; brak potwierdzenia blokad proxy runtime |
| `python3 -m py_compile deploy/smoke.py` | **OK**, wyłącznie składnia Pythona |
| `git diff --check` | **OK** |
| SHA-256 `RACI.md` przed i po zmianach | Bez zmian: `75d25baff4e9c921c42ce83e15ae5d9d396841165643bcdcd2a5af54928cc5d4` |

Odczyt konfiguracji potwierdza dokładną lokalizację GET `/current`, współdzielony
limiter/include proxy oraz zachowanie blokad internal i mutacji węzłów. Jest to
przegląd statyczny, nie test działania Nginx. Pozostałe metody `/current`, również
HEAD, są odrzucane przez jawny warunek metody (samo limit_except GET dopuszczałoby
HEAD). TRACE jest odrzucane wcześniej przez Nginx kodem 405. Pełny smoke wymaga hosta z Docker Engine i możliwością otwierania socketów.

### Korekta katalogów tymczasowych Nginx po próbie na hoście użytkownika

Użytkownik uruchomił `sudo docker compose run --rm --no-deps web -t`:
Nginx potwierdził składnię, ale test zakończył się błędem tworzenia
`/var/cache/nginx/fastcgi_temp` na systemie plików tylko do odczytu. Była to
niepełna konfiguracja ścieżek tymczasowych: przekierowano jedynie client body
i proxy. Dodano `fastcgi_temp_path`, `uwsgi_temp_path` i `scgi_temp_path` do
istniejącego zapisywalnego tmpfs `/tmp`, bez wyłączania read_only ani non-root.
Nginx inicjalizuje te katalogi również bez używania odpowiednich upstreamów.

Po poprawce wymagany jest **ponowny build obrazu web**, ponieważ konfiguracja
jest kopiowana podczas budowania (sam restart nie wystarczy):

```sh
sudo docker compose build web
sudo docker compose run --rm --no-deps web -t
sudo docker compose up -d --wait
python3 deploy/smoke.py
```

W środowisku autora ponowna próba `web -t` nadal jest blokowana dostępem do
docker.sock; nie potwierdzono tu działania poprawionego obrazu. Wynik zgłoszony
przez użytkownika dotyczy obrazu sprzed tej korekty.

### Próba po przebudowie web i korekta smoke

Użytkownik potwierdził po przebudowie obrazu: `web -t` zakończył się sukcesem,
a `docker compose up -d --wait` zgłosiło wszystkie pięć usług jako Healthy.
To wyniki z hosta użytkownika, nie z ograniczonego środowiska autora.
Smoke zakończył się błędem przed pierwszym komunikatem sukcesu (w kontrolach proxy).

W skrypcie znaleziono błędne oczekiwanie: dla TRACE wymagano 403 i JSON,
chociaż Nginx odrzuca tę metodę wcześniej kodem 405, z odpowiedzią spoza
ErrorResponse aplikacji. Poprawiono oczekiwanie na dokładne 405; nadal sprawdzana
jest odmowa dostępu. Pozostałe testowane metody /current wymagają 403.
Dodano komunikaty rozbieżności metody/ścieżki/statusu oraz błędów HTTP bez
wypisywania odpowiedzi, sekretów i querystringów. To usuwa zidentyfikowany błąd
smoke; pełna przyczyna konkretnego uruchomienia wymaga potwierdzenia ponowną próbą.

Po korekcie zaliczono kontrolę składni Pythona i `git diff --check`.
Ponownie uruchomić `python3 deploy/smoke.py` na hoście użytkownika; sama zmiana
skryptu hostowego nie wymaga przebudowy obrazów. Sukces RSA/DH/MITM i diagnostyki
nadal nie został potwierdzony.

## Wcześniejsze wyniki bazowego #73 — nie uruchomiono ponownie po review

Poniższe wyniki zachowano jako historię weryfikacji wcześniejszej wersji. Nie są
dowodem poprawnego działania zmienionej konfiguracji proxy ani nowego smoke.

| Sprawdzenie | Rzeczywisty wynik |
| --- | --- |
| `docker compose config --quiet` | OK, Docker Compose 5.6.0; ponowione po edycjach |
| Normalizacja Compose i kontrola pól | OK: 5 usług non-root, read_only, capabilities ALL usunięte, no-new-privileges, limity CPU/RAM/PID, sondy; tylko port web na 127.0.0.1; internal services |
| `RADH_HTTP_PORT=18080 RADH_DIAGNOSTICS=1 docker compose config` | OK; port i flagi trzech węzłów mają oczekiwane wartości |
| `sh -n deploy/node-entrypoint.sh` | OK |
| `python3 -m py_compile deploy/healthcheck.py deploy/smoke.py` | OK; to kontrola składni, nie uruchomienie sond kontenerowych |
| `docker compose --progress plain build` | **ZABLOKOWANE**: permission denied na `/var/run/docker.sock`; obrazy nie zostały zbudowane |
| `docker compose up -d --wait` | **ZABLOKOWANE**: ten sam brak dostępu do demona; usług nie uruchomiono |
| `python3 deploy/smoke.py` | **NIEZALICZONE w tym środowisku**: brak działającego Compose i blokada socketów; nie potwierdza działania proxy ani wymiany sieciowej |
| Nginx `-t`, sondy UID/read-only, routing proxy i prywatna sieć runtime (wersja bazowa) | **NIEWYKONANE**: brak demona i hostowego nginx; config Compose nie jest walidacją nginx.conf |
| CMake configure/build i `ctest --test-dir crypto-core/build --output-on-failure` | **2/2 zaliczone**, dotychczasowa regresja modexp/RSA/DH + natywny keygen |
| Wybrany istniejący zestaw pytest bez fixture HTTP | **642 zaliczone**, Python 3.14.8 / pytest 9.0.2; zawiera procesowe testy Alice/Bob i Mallory z rzeczywistym C |
| `timeout 25s python3 -m pytest -q -o faulthandler_timeout=10` | **PRZERWANE limitem**, exit 124; zatrzymanie w inicjalizacji istniejącego TestClient, brak pełnego raportu zaliczenia |
| Dodatkowy smoke przez HTTPX ASGI i rzeczywistą bibliotekę C | OK: keygen 61/53/17 → 3233/17/2753/3120; RSA 65 →2790 i odwrotność →65; DH demo 8/19/2/2. Nie obejmuje Nginx/TCP/Compose |
| `npm --prefix frontend run lint` | OK |
| `npm --prefix frontend run build` | OK, Vite 8.3.4; istniejący kod UI bez zmian |
| `git diff --check` | OK |

Komenda zaliczonego zestawu regresyjnego:

```sh
python3 -m pytest \
  tests/test_dh_nodes/test_backend_unit.py \
  tests/test_dh_nodes/test_nodes.py \
  tests/tests_mitm/test_mallory_nodes.py \
  tests/tests_rsa/test_core_valid.py \
  tests/tests_rsa/test_core_invalid.py \
  tests/tests_rsa/test_core_vs_reference.py \
  tests/tests_dh/test_dh_core_valid.py \
  tests/tests_dh/test_dh_core_invalid.py \
  tests/tests_dh/test_dh_vs_reference.py -q
```

Dodatkowy smoke ASGI uruchomiono jednorazowym skryptem poza repozytorium,
z okresowym wybudzaniem pętli asyncio. Powód: środowisko blokuje zarówno
`socket(AF_INET)`, jak i `socketpair.send()` błędem `PermissionError(1)`.
Nie podmieniano obliczeń C, tras ani odpowiedzi API. Nie oznacza to zaliczenia
pełnego pytest lub testów kontenerów. Nie dodano skip/xfail ani osłabionych asercji.

## Do wykonania na lokalnym hoście z dostępem do Docker Engine

```sh
docker compose config --quiet
docker compose build
docker compose run --rm --no-deps web -t
docker compose up -d --wait
docker compose ps
python3 deploy/smoke.py
# Osobna próba jawnej diagnostyki na wolnym środowisku:
RADH_DIAGNOSTICS=1 docker compose up -d --wait
python3 deploy/smoke.py --diagnostics
# Backend jest dostępny wyłącznie w prywatnej sieci, nie jako port hosta.
curl -i http://127.0.0.1:8080/api/v1/dh/sessions/current
# GET: 200 z bieżącą sesją, albo 404 SESSION_NOT_FOUND przed pierwszą sesją.
# 403 dla GET oznacza regresję proxy.
curl -i -X POST http://127.0.0.1:8080/api/v1/dh/sessions/current
# POST /current: 403 FORBIDDEN (także HEAD/PUT/PATCH/DELETE/OPTIONS).
# TRACE /current: 405 z Nginx, bez wymogu JSON ErrorResponse.
curl -i http://127.0.0.1:8080/internal/health/ready
# /internal: 403 FORBIDDEN, bez przekazania do backendu.
curl -i -X POST http://127.0.0.1:8080/api/v1/dh/nodes/alice/heartbeat
# Heartbeat: 404 NOT_FOUND z proxy, nie 204 z backendu.
docker compose logs --tail=100 web backend alice bob mallory
docker compose down
```

Ręczny smoke najpierw sprawdza blokady metod /current, internal, heartbeat,
messages POST, ACK, forward i POST diagnostyki. Potem sprawdza RSA i czeka na węzły. Tworzy własną sesję
created, pobiera ją przez GET /current, odzyskuje ID z odpowiedzi i anuluje ją,
sprawdzając stan cancelled. Na końcu wykonuje normal/MITM. Nie wymaga deterministycznych
sekretów ani zmian backendu. Przy błędzie skrypt kończy się kodem niezerowym;
nie uruchamiać go na zajętej globalnej sesji v1.

Dodatkowa próba UI po utracie lokalnego stanu: na wolnym Compose utworzyć sesję,
odświeżyć stronę i użyć resetu/anulowania. W narzędziach sieciowych potwierdzić
GET /current →200, następnie POST /{odzyskane_id}/cancel →200 ze statusem
cancelled. Powtórzyć dla running, zanim wymiana się zakończy (w razie potrzeby
zatrzymać na chwilę Boba, a po próbie ponownie go uruchomić). Nie anulować cudzej
lokalnej demonstracji. Ten scenariusz nie został wykonany w środowisku autora.
/current znika dopiero w v2, wdrażanym atomowo w #68–70.

Dodatkowo sprawdzić 413 dla body >4 KiB, CSP/no-store na sukcesach i błędach, odtwarzanie
po zmianie IP backendu oraz user/capabilities/read-only/limity przez Docker inspect.
Uruchomienie poleceń G01–G25 wymaga przyszłego kodu #68–71, nie obecnego v1.
Publiczna publikacja i testy obciążeniowe nie były wykonywane.

</details>
