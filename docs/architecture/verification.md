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
