# Raport implementacji #68

Gałąź: feat/68-multi-session-nodes, utworzona z a260a70 na gałęzi kontraktu #73.
Lokalny main był starszy i nie zawierał kontraktu; nie aktualizowano go ani nie
zakładano zdalnego statusu scalenia #81. Nie wykonano commitów, push ani zmian GitHub.

## Pliki

Nowe: nodes/internal_models.py, nodes/internal_http.py, nodes/multi_session.py,
nodes/multi_session_cli.py, nodes/MULTI_SESSION.md, ten raport,
tests/test_multi_session/test_nodes_v2.py i test_internal_http.py.
Zmienione: nodes/README.md, backend/DH_SESSIONS.md, backend/MITM_SESSIONS.md.
Nie zmieniono implementacji pojedynczych agentów, backendu, transportu v1,
CryptoCore/ABI, frontendu, Compose ani istniejących testów/CI.

## Decyzje i architektura

Szczegóły w [MULTI_SESSION.md](MULTI_SESSION.md). Stała pula dwóch workerów
usuwa potrzebę wątku per sesja. RLock chroni krótko rejestr; I/O i C są poza
blokadą. Maksymalnie dwa futures zapobiegają ukrytemu rozrostowi kolejki executora.
Osobny heartbeat i maks. cztery wywołania HTTP pozostają niezależne od C.
Dodatkowa generacja lokalna rejestru odrzuca stare odpowiedzi heartbeat/discovery,
również przy ponownej rejestracji w tym samym epoch; nie dodaje pola do API.
Sekrety są wyłącznie w niezależnych instancjach agentów w procesie danej roli.

## Faktycznie wykonana weryfikacja

| Polecenie / zakres | Wynik |
| --- | --- |
| cmake -S crypto-core -B crypto-core/build | OK |
| cmake --build crypto-core/build | OK |
| ctest --test-dir crypto-core/build --output-on-failure | 2/2 OK |
| python3 -m pytest tests/test_multi_session -q | 60 OK; mock internal + rzeczywisty C, bez TCP |
| Istniejące test_nodes, test_mallory_nodes, test_backend_unit | 250 OK, w tym dotychczasowe procesy agentów |
| Regresja agentów/adaptera i natywnego RSA/DH | 642 OK (komenda poniżej) |
| Istniejące testy odrzucania błędnej sesji/JSON w transporcie v1 | 7 OK, 47 niezwiązanych deselected |
| timeout 60s python3 -m pytest -q -o faulthandler_timeout=15 | Exit 124: zatrzymanie w istniejącym Starlette TestClient, fixture test_sessions.api; brak pełnego wyniku |
| tests/tests_mitm/test_mitm_transport_live.py | 2 errors w setup: PermissionError(1) przy tworzeniu socketu; środowisko nie pozwala uruchomić TCP |
| python3 -m nodes.multi_session_cli --help | OK |
| git diff --check | OK |

Regresja 642:

```sh
python3 -m pytest tests/test_dh_nodes/test_nodes.py tests/tests_mitm/test_mallory_nodes.py tests/test_dh_nodes/test_backend_unit.py tests/tests_rsa/test_core_valid.py tests/tests_rsa/test_core_invalid.py tests/tests_rsa/test_core_vs_reference.py tests/tests_dh/test_dh_core_valid.py tests/tests_dh/test_dh_core_invalid.py tests/tests_dh/test_dh_vs_reference.py -q
```

Nie sumować nakładających się zestawów jako liczby unikalnych testów. Nie dodano
skip/xfail ani nie osłabiono istniejących asercji. Nie wykonano pełnej integracji
z #69, frontendem lub publicznym środowiskiem. Wyniki dotyczą Python 3.14.8;
kod wykorzystuje składnię dostępną w Python 3.11+, ale 3.11 nie był tu uruchomiony.

## Mapowanie kryteriów akceptacji

| Kryterium | Implementacja i dowód komponentowy |
| --- | --- |
| Wiele sesji normal/MITM, wspólne message_id bez konfliktu | Osobne Entry/DhNode/MalloryNode; test_two_parallel_sessions_real_c dla trzech ról, test_reference_mitm_two_sessions_matches_real_mallory_substitutes |
| Normal i MITM równocześnie | test_normal_and_mitm_discovery_keeps_agents; niezależne mapy i stan usuwania |
| Prywatne wykładniki i brak regeneracji | Fabryka per wpis; testy tożsamości agentów, ponownego discovery i utraty odpowiedzi; protokół nie zawiera wykładników |
| Publikacja/ACK/forward/retry diagnostyki | Flagi per Entry, deterministyczne ID, test_lost_response_retry_preserves_secret i test_lost_last_ack_after_completion |
| Limit 128 i cleanup jednej sesji | MAX_NODE_AGENTS walidowany 1..128; test_capacity_no_overwrite, nieograniczone used_ids nie istnieje |
| Epoch i spóźnione wyniki | Testy zmiany epoch podczas HTTP, usunięcia wpisu podczas C/HTTP i starej generacji heartbeat/discovery |
| Auth roli i odmowa diagnostyki | test_error_scopes i test_both_diagnostic_opt_ins_required; testy pliku sekretu/nagłówków; brak tokenów właściciela |
| Timeouty i ograniczone retry | Limit 3/5 s klienta, test_socket_timeout_controlled, test_timeout_backoff_and_ttl i Retry-After maks. 30 s |
| Brak odtwarzania terminalnych agentów | Test pięciu statusów i test_diagnostic_retention_never_extended |
| Współbieżność i kolejki | test_scheduler_two_jobs_no_overlap_and_independent_heartbeat: max. 2 zadania, obsługa 10 sesji, osobny heartbeat, kontrolowane zamknięcie |
| Walidacja odpowiedzi | Cały snapshot przed zmianą mapy; test_invalid_discovery_atomic, test_invalid_inbox_before_c_and_ack, limity body, JSON, status, epoch i rozmiaru odpowiedzi |
| Błąd C zachowuje inne sesje | test_c_failure_preserves_other_session_and_reports_failure; obliczenia nie są zastępowane Pythonowym pow |
| Integracja z rzeczywistym #69 / pełna macierz bezpieczeństwa | Otwarta zależność; wymagane wspólne testy #71, nie potwierdzone mockiem |

## Zależności i uzgodnienia z Danielem

- Rzeczywisty koordynator internal nie został dodany w #68. Musi dostarczyć
  discovery, przypisanie instance_id, epoch na każdej odpowiedzi, role auth,
  idempotentne mutacje i cleanup opisane w nadrzędnym kontrakcie.
- Descriptor bez terminal_at nie pozwala określić dokładnej chwili ukończenia
  na serwerze. Lokalne okno 30 s liczy się od pierwszej obserwacji completed.
  Wymaga to uzgodnienia interpretacji z #69; nie zmieniono samodzielnie API.
- Message publikacji MITM po retry może zawierać wartość już podmienioną.
  Oryginał i forward są rozdzielone; zachowanie potwierdzić z implementacją #69.
- Utrata lease kończy proces zamiast kontynuować z utraconym stanem; nadzorca
  restartuje go z nowym instance_id, a backend musi zakończyć stare przypisania.
- Atomowe przełączenie v1 → v2 wymaga #68–70; plan wspólnej integracji i komendy
  startu trzech ról są w MULTI_SESSION.md. Bez fallbacku i bez publikacji v1.

## Proponowany PR

Tytuł: `feat(nodes): dodaj wielosesyjny transport internal dla Alice, Boba i Mallory`

### Opis zmian

Dodano osobno uruchamiany klient internal v2 obsługujący wiele niezależnych
sesji w jednym procesie każdej roli. Zachowano transport v1 i Compose do czasu
atomowej migracji #68–70. Matematyka nadal korzysta z CryptoCore C11.

### Powiązane Issue

Realizuje #68. Powiązane: #69, #70, #71 i kontrakt #73 / PR #81.

### Wprowadzone zmiany

- Ograniczony rejestr epoch/session_id, dwa zadania, cztery operacje HTTP,
  niezależny heartbeat, round-robin i cleanup.
- Tokeny ról z plików, ścisłe modele internal, fencing, bounded retry,
  idempotencja i opcjonalna diagnostyka per sesja.
- Testy komponentowe z prawdziwym C, mock koordynatora i instrukcje integracji.

### Testy

CTest 2/2, nowa warstwa 60 testów, istniejąca regresja bez HTTP 642 testy oraz
7 testów walidacji transportu v1 — zaliczone. Pełny pytest przerwany po 60 s
w istniejącym TestClient; testy live blokuje tworzenie socketów (2 błędy setup).
Pełne end-to-end z #69 pozostaje do wspólnej weryfikacji.

### Checklista

- [x] Kod kompiluje się / uruchamia poprawnie w sprawdzonym zakresie komponentowym
- [ ] Odpowiednie testy przechodzą — pełny zestaw wymaga środowiska HTTP
- [ ] Zmiany nie powodują regresji — pełna regresja HTTP pozostaje do potwierdzenia
- [x] Zaktualizowano dokumentację
- [x] Nie dodano sekretów ani danych poufnych
- [x] Kod jest gotowy do code review

### Dodatkowe uwagi

Nie zmieniono koordynatora, C/ABI ani frontendu. Przed integracją uzgodnić
retencję completed bez terminal_at w Descriptor oraz odpowiedź publikacji MITM.
Nie przełączono domyślnego transportu. Status publicznej bety pozostaje NO-GO.
