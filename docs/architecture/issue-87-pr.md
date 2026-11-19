Tytuł: chore(deploy): zintegruj wielosesyjne DH z Compose i reverse proxy

## Opis zmian

Przełączono lokalny Compose na istniejący koordynator i frontend DH v2 oraz
niezależne procesy Alice/Bob/Mallory. Wyłączono legacy session API, zachowując
endpointy RSA/keygen i matematyczne demo DH.

## Powiązane Issue

Realizuje #87. Powiązane: #68 / #82, #69 / #85, #70 / #86, #73 / #81 i #71.
Baza: origin/feat/70-multi-session-ui (5ca0454); PR zależy od zmian #86.

## Wprowadzone zmiany

- Compose: pięć usług, multi_session_cli, niezależne pliki tokenów, legacy=false,
  Origins zależne od portu i zaufanie Uvicorn wyłącznie do ustalonego IP web.
- Inicjalizacja tokenów bez nadpisywania; UID/GID 10001, tryb 0400, mounty read-only,
  SELinux z, wykluczenie sekretów z Git i build context. Web nie dostaje tokenów.
- Proxy: ścisła allowlista v2 i ID 32 hex, blokada internal/v1/protokołu/nieznanych
  metod, przekazywanie poświadczeń i Retry-After bez logowania, no-store.
- Healthcheck gotowości koordynatora/C, procesu i roli węzła oraz rzeczywistych
  uprawnień/mountów sekretów; zachowane non-root, read-only i limity usług.
- Minimalna poprawka requestJson: błędy proxy bez epoch nie usuwają tokenu;
  sukces bez poprawnego epoch jest błędem kontraktu. Dodano 9 przypadków regresji.
- Smoke rzeczywistych usług: RSA, normal/MITM, idempotencja, auth, izolacja,
  diagnostyka i cleanup; raportuje obserwację running osobno od startów równoległych.
- CI uruchamia również backend/tests/unit, zachowując dotychczasowy zestaw.
- Zaktualizowano instrukcje Fedora, sekretów, diagnostyki, restartu i wyniki testów.

## Testy

PASS: CMake/CTest (2/2), backend/tests/unit (66), procesy/agenci (219),
pokrywająca się regresja C/agentów bez HTTP (642), npm test (37), lint/build,
walidacja Compose (domyślna i port 18080/diagnostyka), składnia i git diff --check.

NOT COMPLETE: pełny pytest przerwany po 60 s w istniejącym TestClient.
NOT RUN runtime: build obrazów, nginx -t, up/ps, oba smoke, mounty/SELinux,
restart i SIGTERM — środowisko blokuje Docker socket oraz sockety TCP.
Dokładne wyniki i komendy hostowe są w docs/architecture/verification.md.
Nie deklarujemy pięciu healthy ani zaliczenia smoke na podstawie konfiguracji.

## Checklista

- [x] Kod kompiluje się / uruchamia poprawnie w sprawdzonym zakresie lokalnym
- [ ] Odpowiednie testy przechodzą — pełny pytest i runtime wymagają hosta
- [ ] Zmiany nie powodują regresji — pełna integracja Compose do potwierdzenia
- [x] Zaktualizowano dokumentację
- [x] Nie dodano sekretów ani danych poufnych
- [x] Kod jest gotowy do code review z jawnymi ograniczeniami weryfikacji

## Dodatkowe uwagi

Przed scaleniem wykonać hostowe komendy z verification.md i potwierdzić wszystkie
punkty runtime DoD. Wymagany rootful Docker bez userns-remap; rootless wymaga
osobnej walidacji UID. Podsiec 172.30.87.0/24 musi być wolna; adres proxy jest
konfigurowalny wraz z podsiecią. Nie zmieniono ABI, algorytmów, koordynatora ani
transportu #68. Wskazano rozbieżność: #69 wysyła skrócony TTL completed, ale
#68 liczy lokalną retencję od obserwacji zamiast użyć tego TTL. Wymaga uzgodnienia
z właścicielem węzłów przed odbiorem gate. Nie dostarczono TLS ani pełnego odbioru QA #71.
Publiczna beta nadal **NO-GO** do spełnienia release gate.
