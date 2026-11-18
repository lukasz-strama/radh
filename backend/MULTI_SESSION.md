# Wielosesyjny koordynator DH — #69

Implementacja odpowiada kontraktowi w `docs/architecture/multi-session.md`
i modelom internal z PR #82 / #68. Jeden proces FastAPI przechowuje wiele
ulotnych sesji, a procesy Alice/Bob/Mallory zachowują własne wykładniki i agentów.
Koordynator nie oblicza kluczy sesji. RSA/keygen i matematyczne demo DH
korzystają z dotychczasowego ABI C.

## Organizacja backendu

- `multi_models.py` definiuje ścisłe żądania oraz schematy odpowiedzi v2/internal.
- `coordinator.py` zarządza sesjami, przypisaniami instancji, wiadomościami,
  idempotencją, historią i diagnostyką.
- `coordinator_limits.py` waliduje konfigurację oraz ogranicza mapy limiterów
  i liczbę równoczesnych wywołań C.
- `coordinator_http.py` uwierzytelnia role, ogranicza żądania przed parsowaniem
  JSON, dodaje no-store/epoch i uruchamia cleanup w lifespan.
- `multi_api.py` wystawia operacje właścicieli i węzłów w osobnych przestrzeniach.

Blokada rejestru poprzedza blokadę rekordu. Właściwa mutacja protokołu używa
blokady konkretnej sesji. Operacje admission/start/cleanup synchronizują również
rejestr. Backend wykonuje walidację matematyczną i C poza blokadami rejestru.
Każdy snapshot ma własne kopie modeli. Nie przechowujemy surowego IP twórcy
ani jawnego tokenu właściciela w rekordzie. Wyjątkiem dla tokenu jest ograniczony
60-sekundowy cache odpowiedzi tworzenia, potrzebny do odzyskania odpowiedzi.

## Konfiguracja lokalna

Role używają odrębnych plików tokenów `RADH_ALICE_TOKEN_FILE`,
`RADH_BOB_TOKEN_FILE`, `RADH_MALLORY_TOKEN_FILE`. Każdy token to 43 znaki
base64url wygenerowane przez `secrets.token_urlsafe(32)`, z opcjonalnym końcowym
newline. Operator przechowuje je poza repozytorium i udostępnia odpowiedniej
usłudze. Backend odczytuje pliki przy starcie i zachowuje wyłącznie skróty SHA-256.
Niepoprawny plik lub token współdzielony między rolami blokuje start.
Brak pliku oznacza wyłączone uprawnienia danej roli. Rotacja wymaga restartu.

`RADH_ALLOWED_ORIGINS` przyjmuje originy rozdzielone przecinkami. Domyślnie
dozwolone są localhost i 127.0.0.1 na portach 5173 oraz 8000. Dla wdrożenia
należy ustawić właściwy origin HTTPS. CLI bez Origin jest obsługiwane.
Źródłowe IP pochodzi z ASGI client. Reverse proxy i Uvicorn muszą ufać nagłówkom
forwarded wyłącznie od zaufanego proxy, zgodnie z dokumentacją wdrożenia.

Konfiguracja liczbowa używa nazw pól `Settings` zapisanych wielkimi literami,
np. `MAX_SESSIONS`, `MAX_RUNNING_SESSIONS`, `MAX_SESSIONS_PER_IP`,
`SESSION_CREATED_TTL_SECONDS`, `SESSION_MAX_AGE_SECONDS`,
`SESSION_RETENTION_SECONDS`, `TOMBSTONE_TTL_SECONDS`, `MAX_TOMBSTONES`,
`MAX_CREATE_RETRIES`, `CREATE_RETRY_TTL_SECONDS`, `NODE_LEASE_SECONDS`,
`PARTICIPANT_TIMEOUT_SECONDS`, `DIAGNOSTICS_RETRY_SECONDS`, `CLEANUP_SECONDS`,
`CREATE_RATE_PER_MINUTE`, `CREATE_RATE_BURST`, `CRYPTO_RATE_PER_MINUTE`,
`CRYPTO_RATE_BURST`, `READ_TOKEN_RATE_PER_MINUTE`, `READ_IP_RATE_PER_MINUTE`,
`INTERNAL_RATE_PER_MINUTE`, `INTERNAL_RATE_BURST`, `MAX_RATE_BUCKETS`,
`RATE_BUCKET_TTL_SECONDS`, `MAX_CRYPTO_JOBS` i `MAX_CRYPTO_WAITERS`.
Wartości domyślne odpowiadają tabeli limitów #73. Typy, dodatniość i twarde
maksima kontraktu są sprawdzane przy starcie. Limity rekordów i rozmiarów
można obniżyć, bez rozszerzania schematów klienta #68.
Przy zmianie lease należy uzgodnić konfigurację z klientem #68, którego model
Heartbeat w PR #82 oczekuje domyślnej wartości 10 sekund.

Rejestr działa w jednym workerze Uvicorn. Restart usuwa sesje i zmienia epoch.
Cleanup działa co 5 sekund oraz przed operacjami. Sam odczyt, heartbeat i
idempotentne retry nie przedłużają deadline sesji ani terminu postępu protokołu.

## Informacje dla frontendu — #70

1. Odczytaj `GET /api/v2/dh/nodes` i nagłówek `X-Backend-Epoch`.
2. Wyślij `POST /api/v2/dh/sessions` z tym epoch oraz
   `Idempotency-Key` (43 znaki base64url, 32 losowe bajty). Ciało zawiera
   `prime`, `generator`, opcjonalne `mode` i `diagnostics_enabled`.
3. Odpowiedź 201 ma kształt `{session: SessionView, session_token: string}`.
   Zapisz ID i token per karta. Każda dalsza operacja właściciela używa
   `Authorization: Bearer <session_token>`.
4. Stan/start/cancel/events/diagnostics/DELETE korzystają z własnego ID
   pod `/api/v2/dh/sessions/{id}`. Zdarzenia mają paginację after/limit.
5. Obsłuż stany failed/expired. Istniejący expired jest czytelny jako 200,
   diagnostyka zwraca null. Zachowaj poświadczenie do DELETE.
   Tombstone zwraca 410, obcy lub nieznany zasób 404. Po 404/410 usuń poświadczenie.
6. Powtórzenie create w ciągu 60 s zwraca pierwotną odpowiedź 201. Każde retry
   przechodzi limiter IP. Po 60 s kod CREATE_RETRY_EXPIRED wymaga świadomej
   nowej próby. Zmiana epoch daje BACKEND_EPOCH_MISMATCH.
7. Po DELETE ten sam klucz create daje CREATION_GONE. Nie odtwarzaj takiej próby.
   Odpowiedzi 429/503 mają Retry-After. Polling nie wydłuża TTL.

Nowe routery zastępują niezabezpieczone endpointy v1 sesji i heartbeat.
Stare moduły pozostają dostępne jako kod referencyjny i dla dotychczasowych
testów jednostkowych, lecz aplikacja ich nie rejestruje.
Aktualny frontend/Compose v1 wymaga wspólnego przełączenia z #68/#70.
Zmiana #69 nie oznacza gotowości istniejącego klienta v1 do pracy z API v2.

## Informacje dla węzłów — #68 / PR #82

Heartbeat pod `/internal/v1/dh/nodes/{role}/heartbeat` przyjmuje
`{instance_id}` i Bearer roli. Pozostałe operacje wymagają również
`X-Backend-Epoch` i `X-Node-Instance`. Start sesji przypina aktualne
instancje wymaganych ról. Nowa instancja nie przejmuje starych running.

Discovery zwraca pełny snapshot przypisań własnej instancji. Normalne sesje
nie trafiają do Mallory. Publikacja zawiera wyłącznie message_id/type/public_value.
Backend wyznacza nadawcę i odbiorcę z uwierzytelnionej roli. ACK ma puste ciało.
Forward i raporty diagnostyczne odpowiadają modelom z PR #82.

Doprecyzowania dwóch punktów wskazanych w raporcie Łukasza:

- Retry publikacji MITM zwraca aktualną wiadomość, w tym wartość doręczoną
  po forward. Backend porównuje request z zachowanym oryginałem przechwycenia.
- Dla completed `remaining_ttl_seconds` deskryptora jest minimum czasu do
  końca sesji i pozostałego okna diagnostyki liczonego od terminalizacji.
  Dzięki temu klient PR #82 usuwa agenta w terminie serwera mimo późniejszego
  discovery, bez dodawania pola do ścisłego modelu Descriptor.
  Po 30 s backend odrzuca raport diagnostyczny z INVALID_SESSION_STATE.
  Publiczna historia i już zapisane K pozostają dostępne do końca retencji.

## Weryfikacja jednostkowa i zadanie QA — #71

Nowe testy w `backend/tests/unit` korzystają z ręcznie przesuwanego zegara
oraz atrap ASGI i CryptoCore. Sprawdzają wyłącznie jednostki backendu, bez
TestClient, serwera HTTP, procesów uczestników, przeglądarki i biblioteki C.

```sh
python -m pytest backend/tests/unit tests/test_dh_nodes/test_backend_unit.py -q
```

Dotychczasowe testy jednostkowe adaptera pozostają częścią tej komendy.
Standardowe `pytest.ini` zbiera katalog `tests`, więc nowy katalog backendowych
testów jednostkowych wymaga jawnego wskazania jak wyżej.

QA #71 obejmuje współpracę realnych procesów z API, UI i pełną regresję.
Istniejące testy integracyjne sesji v1 odwołują się do wycofanych endpointów.
Przy migracji QA musi dostosować je do create/token/heartbeat/discovery v2.
Samo przejście testów jednostkowych nie potwierdza pełnego CI ani integracji
#68–70 i nie zastępuje bramek bezpieczeństwa publicznej bety.
