# Weryfikacja lokalna #73

Data: 2026-11-17. Baza: main a37d066, gałąź `chore/73-deployment-threat-model`.
Wyniki odnoszą się do środowiska autora, nie VPS i nie publicznej bety.
Nie zmieniano backendu, węzłów, CryptoCore, frontendu, testów Python ani workflow.
Istniejący nieśledzony `RACI.md` pozostawiono nietknięty.

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
| Nginx `-t`, sondy UID/read-only, routing proxy i prywatna sieć runtime | **NIEWYKONANE**: brak demona i hostowego nginx; config Compose nie jest walidacją nginx.conf |
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
# Wyłącznie backend jest dostępny w prywatnej sieci, nie jako port hosta.
curl -i http://127.0.0.1:8080/internal/health/ready
curl -i http://127.0.0.1:8080/api/v1/dh/sessions/current
# Oba powyższe żądania powinny być odrzucone (403), nie trafić do backendu.
docker compose logs --tail=100 web backend alice bob mallory
docker compose down
```

Dodatkowo sprawdzić 413 dla body >4 KiB, brak dostępu przez proxy do heartbeat,
ACK, forward i POST diagnostyki, CSP/no-store na sukcesach i błędach, odtwarzanie
po zmianie IP backendu oraz user/capabilities/read-only/limity przez Docker inspect.
Uruchomienie poleceń G01–G25 wymaga przyszłego kodu #68–71, nie obecnego v1.
Publiczna publikacja i testy obciążeniowe nie były wykonywane.
