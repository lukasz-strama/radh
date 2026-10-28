# Sesje i transport DH — #37

Koordynator przechowuje jedną bieżącą sesję w pamięci procesu. Przekazuje
w protokole wyłącznie wartości publiczne i metadane. Opcjonalna diagnostyka
edukacyjna K jest przechowywana osobno. Nie tworzy procesów Alice/Bob,
nie wywołuje `CryptoCore.exchange()` i nie oblicza kluczy. Dotychczasowe
endpointy RSA i `/api/v1/dh/demo/exchange` pozostają bez zmian.

## Uruchomienie

Z katalogu głównego repozytorium, po instalacji `backend/requirements.txt`:

```sh
python -m uvicorn app.main:app --app-dir backend --workers 1
```

Swagger UI: `http://127.0.0.1:8000/docs`. Wymagany jest jeden worker;
procesy nie współdzielą pamięci. Restart usuwa sesję i historię identyfikatorów.
Po restarcie używaj nowego identyfikatora (domyślnie generowany UUID).
Nie stosujemy bazy, WebSocketów ani uwierzytelniania — zgodnie z PBI-012.

## Klient transportu i zależność od #36

`backend/dh_transport.py` jest cienką pętlą HTTP, uruchamianą w osobnym
procesie dla każdej roli. Korzysta z `DhNode.start_session()` i
`DhNode.receive_public()` dostarczanych przez #36. Nie implementuje obliczeń,
losowania sekretów. Opcjonalnie publikuje wynik `diagnostics()` przez osobny
endpoint po włączeniu flagi `--allow-diagnostics`. Wymaga obecności modułu `nodes` i adaptera
z #36 (sprawdzono draft #44, commit `40ec537b786ede29be3fe5158bc40502a9037b20`).
Na samym `main` sprzed scalenia #36 klient zgłasza brak modułu; API sesji działa
niezależnie i może być sprawdzane przez Swagger lub dowolnych klientów HTTP.

Po integracji #36 zbuduj CryptoCore zgodnie z jego README. Następnie uruchom
przed utworzeniem sesji, w dwóch terminalach z katalogu głównego projektu:

```sh
python -m backend.dh_transport --role alice
```

```sh
python -m backend.dh_transport --role bob
```

Opcja `--url http://127.0.0.1:8000` wskazuje koordynatora. Agenty odpytują go
co 0,5 s, oczekują na sesję `running`, wysyłają własną wartość, pobierają wartość
partnera i potwierdzają dopiero po poprawnym lokalnym obliczeniu. Nadal działają
po zakończeniu i mogą obsłużyć następną sesję z nowym ID. Timeout żądania: 5 s.
Brak sesji, chwilowa niedostępność koordynatora i utrata odpowiedzi podlegają
ponowieniu; sekret nie jest generowany ponownie przy ponowieniu tego samego ID.

Lokalny przykład deterministyczny (wyłącznie mechanizm testowy z #36):

```sh
# Terminal Alice (Linux/macOS)
RADH_NODE_TEST_SECRET=6 python -m backend.dh_transport --role alice --test-mode
# Terminal Bob
RADH_NODE_TEST_SECRET=15 python -m backend.dh_transport --role bob --test-mode
```

W PowerShell ustaw `$env:RADH_NODE_TEST_SECRET = '6'` (u Boba `'15'`), a następnie
uruchom odpowiednie polecenie z `--test-mode`. Sekret jest odczytywany lokalnie;
żadne żądanie HTTP go nie zawiera. Bez flagi `--allow-diagnostics` klient transportu nie eksportuje diagnostyki K.

## Kontrakt HTTP

Prefiks: `/api/v1/dh/sessions`.

| Metoda i ścieżka | Wejście | Odpowiedź |
| --- | --- | --- |
| `POST /` (bez końcowego `/`) | `session_id` opcjonalny, `prime`, `generator`, `mode` opcjonalny | 201: sesja `created` |
| `GET /current` | brak | bieżąca sesja albo 404 |
| `GET /{id}` | ID sesji | stan, uczestnicy, wiadomości i zdarzenia |
| `POST /{id}/start` | bez ciała | sesja `running` |
| `POST /{id}/cancel` | bez ciała | sesja `cancelled` |
| `POST /{id}/messages` | wiadomość opisana poniżej | przyjęta wiadomość ze statusem |
| `GET /{id}/messages?recipient=bob` | `alice` lub `bob` | lista niepotwierdzonych wiadomości, także pusta |
| `POST /{id}/messages/{message_id}/ack` | `{"recipient":"bob"}` | wiadomość `processed` |
| `GET /{id}/events?after=0` | nieujemny numer ostatnio widzianego zdarzenia | zdarzenia z większym numerem |

Przykładowe utworzenie:

```json
{"session_id":"reference-1","prime":23,"generator":5,"mode":"normal"}
```

Następnie `POST /api/v1/dh/sessions/reference-1/start`. Przy wcześniej
uruchomionych klientach nie trzeba ręcznie wysyłać kolejnych wiadomości.

Wiadomość Alice:

```json
{"message_id":"alice-public","sender":"alice","recipient":"bob","type":"public_value","public_value":8}
```

Wiadomość Boba ma `sender: "bob"`, `recipient: "alice"`,
`message_id: "bob-public"`, `public_value: 19`.
ID sesji pochodzi ze ścieżki, więc nie ma drugiego, sprzecznego ID w ciele.
Numery `message_id` są unikalne w obrębie sesji, nie globalnie.

Parametry i publiczne wartości są ścisłymi liczbami całkowitymi uint32
(bez bool, float i string). `prime` jest pierwsza, `2 <= generator < prime`,
`1 <= public_value < prime`; wartość 1 jest dopuszczalna. Pierwotność generatora
nie jest sprawdzana. Backend waliduje publiczne parametry bez obliczania DH.
Identyfikatory mają 1–64 znaków z `a-z A-Z 0-9 _ -`; `current` jest zarezerwowany
jako ID sesji. Dodatkowe pola żądań modeli są odrzucane, w tym sekrety i klucze.

## Stany, potwierdzenia i log

Sesja: `created → running → completed` lub `created/running → cancelled`.
Druga sesja jest odrzucana do zakończenia lub anulowania pierwszej. Nowa sesja
zastępuje jej dane i log; zużyte identyfikatory pozostają zarezerwowane do restartu.
Wiadomości do poprzedniej sesji zwracają 404. Reset to anulowanie i utworzenie
nowej sesji z nowym ID, nigdy ponowny start starej.

Uczestnik: `waiting → published → received`. `published` oznacza przyjęcie jego
wartości publicznej przez koordynatora. `received` oznacza potwierdzenie
przetworzenia wartości partnera. ACK jest dopuszczalny po publikacji własnej
wartości. Dwa ACK kończą sesję. `completed` oznacza dwa potwierdzenia, nie dowód
równości sekretów ani ich weryfikację przez serwer.

Odczyt kolejki nie usuwa wiadomości. Do czasu ACK zwracana jest ponownie.
Identyczny POST z tym samym `message_id` oraz ponowny ACK są idempotentne,
również po ukończeniu. Nie dopisują zdarzeń. Inna treść tego samego ID albo
ponowna publikacja pod nowym ID zwraca 409. Dopuszczamy obie kolejności A/B.
Blokada obejmuje walidację stanu, zapis i nadanie numeru zdarzenia.

Zdarzenia mają `sequence`, `type`, `sender`, `recipient`, `public_value`,
`message_id`, `status`. Typy:

- `session_created`, `session_started`;
- `public_value` ze statusem `queued`;
- `message_processed` ze statusem `processed`;
- `session_completed`, `session_cancelled`.

Zdarzenia sesji mają pola nadawcy/odbiorcy/wartości/ID wiadomości równe `null`.
Log jest dopisywany i uporządkowany; wcześniejsze zdarzenie `queued` nie jest
nadpisywane po ACK. Aktualny status wiadomości znajduje się w `messages`.
Brak wiadomości daje pustą kolejkę; sesja czeka, można ją anulować. Nie zgłaszamy
fikcyjnej niedostępności węzła na podstawie pustej kolejki. #37 nie implementuje
automatycznego przerywania sesji po utracie heartbeatów. Dostępność procesów
ma osobny endpoint opisany poniżej.

## Błędy i zakres integracji

Każdy błąd ma istniejący format `{"error":{"code":"...","message":"..."}}`.

| HTTP | Kod | Przypadek |
| --- | --- | --- |
| 404 | `SESSION_NOT_FOUND`, `MESSAGE_NOT_FOUND` | obcy/stary identyfikator |
| 409 | `SESSION_BUSY`, `SESSION_ID_IN_USE` | aktywna sesja lub ponowne ID |
| 409 | `INVALID_SESSION_STATE` | operacja przed startem lub po anulowaniu |
| 409 | `MESSAGE_ID_CONFLICT`, `PUBLIC_VALUE_ALREADY_SENT` | sprzeczne duplikaty |
| 409 | `PUBLIC_VALUE_REQUIRED` | ACK przed publikacją własnej wartości |
| 409 | `MITM_NOT_IMPLEMENTED` | próba startu MITM przed zadaniem M2 |
| 422 | `INVALID_REQUEST` | błędne typy, role, dodatkowe/brakujące pola |
| 422 | `INVALID_PRIME`, `INVALID_GENERATOR` | całkowite parametry o błędnej wartości |
| 422 | `INVALID_MESSAGE`, `INVALID_RECIPIENT` | wartość spoza zakresu, zły odbiorca |

Błędne żądania nie zmieniają stanu ani nie zapisują dowolnej treści wejścia w logu.
Tryb `mitm` można zapisać przy tworzeniu sesji; start zwraca jawne 409 do M2.
Nie wykonujemy zwykłej wymiany pod etykietą MITM.

#38 powinno mapować odpowiedzi do swojego widoku: `session_id` to ID,
`prime/generator` to p/g, `participants` to potwierdzony postęp, `messages`
i `events` to publiczne wartości i rzeczywiste zdarzenia. Nie trzeba zmieniać
starego endpointu. Dostępność procesów i diagnostyka edukacyjna klucza mają osobne endpointy
opisane poniżej; nie są częścią standardowych wiadomości ani zdarzeń.

## Weryfikacja

```sh
python -m pytest tests/test_sessions.py -q
python -m pytest
```

Test backendu uruchamia dwa niezależne procesy klientów HTTP przed startem sesji
i sprawdza transport A=8/B=19. Używa stałych publicznych wartości, więc nie
zastępuje testów obliczeń ani pełnej integracji agentów z #39. Osobne testy
obejmują walidację, kolejność, konflikty, ponowienia po utracie odpowiedzi,
atomowość duplikatów, stare ID i schemat błędów OpenAPI.

### Walidacja odpowiedzi klienta

Modele kontraktu są współdzielone przez API i klienta w `app/session_models.py`.
Klient sprawdza wymagane pola sesji, schemat całej kolejki, role nadawcy i odbiorcy,
status i zakres wartości przed wywołaniem obliczeń lub ACK. Odpowiedź uszkodzona,
niepełna albo skierowana do innej roli nie trafia do węzła. Błędny JSON i zerwane
połączenie są obsługiwane bez zakończenia pętli; diagnostyka nie wypisuje ich treści.


## Dostępność węzłów — kontrakt integracyjny #38

- `POST /api/v1/dh/nodes/{role}/heartbeat`, bez ciała, odpowiedź **204**.
- `GET /api/v1/dh/nodes` zwraca np.:

```json
{"alice":{"online":true,"last_seen":"2026-10-28T12:00:00Z"},"bob":{"online":false,"last_seen":null}}
```

Klient wysyła heartbeat co 1 s w osobnym wątku, z timeoutem 2 s. Obsługa
wymiany, ponowienia ACK i diagnostyki nie blokują tego wątku. Po błędzie sieci
kolejna próba następuje w następnej iteracji; opóźnione próby nie są kolejkowane.
Wątek nie dotyka stanu `DhNode`; wszystkie obliczenia pozostają sekwencyjne.
`online` wygasa po 5 s bez kontaktu. TTL jest liczony zegarem monotonicznym,
więc zmiana czasu systemowego go nie zaburza. `last_seen` nadaje serwer w UTC;
`null` oznacza brak zgłoszenia od uruchomienia serwera. Dostępność nie jest
powiązana z resetem sesji i nie zmienia jej stanu ani logu. Frontend może
odpytywać co 3 s i blokować start, gdy brakuje węzła. Sam heartbeat nie
jest gwarancją, że proces wykona następną operację.

## Opcjonalna diagnostyka edukacyjna K

Flaga klienta transportu to dokładnie **`--allow-diagnostics`**. Domyślnie
wyłączona; zwykłe komunikaty i `GET /sessions/{id}` pozostają bez zmian.

- `POST /api/v1/dh/sessions/{id}/diagnostics`, ciało
  `{"participant":"alice","shared_secret":2}`, odpowiedź **204**.
- `GET /api/v1/dh/sessions/{id}/diagnostics` zwraca
  `{"alice":2,"bob":null}`. `null` oznacza brak opublikowanego wyniku.

Serwer przyjmuje raport tylko po ACK danego uczestnika, w stanie `running`
lub `completed`. Wymaga ścisłej liczby całkowitej `1 <= K < prime`. Wynik jest
osobnym polem magazynu, poza modelem sesji, `messages` i `events`. Nie dodaje
zdarzeń i nie jest wysyłany partnerowi przez klienta. GET diagnostyki jest
jawnym odczytem edukacyjnym dla UI; API nie ma uwierzytelniania ani kontroli
uprawnień, więc nie stanowi prywatnego kanału dostępu do K.

Identyczny raport jest idempotentny (204), sprzeczny zwraca
`409 DIAGNOSTIC_CONFLICT`; przed ACK zwracamy `409 ACK_REQUIRED`. Zła wartość
numeryczna daje `422 INVALID_DIAGNOSTIC`, błędny typ lub dodatkowe pola —
`422 INVALID_REQUEST`. Anulowana sesja odrzuca zapis. Nowa sesja usuwa poprzednią
diagnostykę, a zapis/odczyt pod starym ID zwraca 404.

Klient publikuje po ACK i ponawia przy utracie odpowiedzi, także po `completed`.
Odczyt stanu uczestnika pozwala odzyskać sytuację utraty odpowiedzi na ostatni ACK.
Po potwierdzonym zapisie nie publikuje ponownie. Bez flagi nie wywołuje
`diagnostics()` i nie wysyła raportów. Frontend może odpytywać diagnostykę
w trakcie sesji i do 10 s po `completed`; brak K nie jest błędem wymiany.
Koordynator przechowuje zadeklarowane wyniki, nie potwierdza ich poprawności.

Przykład po integracji modułu węzłów z #44, dwa osobne terminale Linux/macOS:

```sh
RADH_NODE_TEST_SECRET=6 python -m backend.dh_transport --role alice --test-mode --allow-diagnostics
```

```sh
RADH_NODE_TEST_SECRET=15 python -m backend.dh_transport --role bob --test-mode --allow-diagnostics
```

W PowerShell ustaw lokalnie `$env:RADH_NODE_TEST_SECRET = '6'` (u Boba `'15'`)
i uruchom odpowiednie polecenie `python -m backend.dh_transport ...` z obiema
flagami. Prywatne wykładniki nie są przesyłane do serwera. Przy `p=23, g=5`
wartości publiczne to A=8/B=19, diagnostyka zwraca oba K=2, a log nadal ma
7 zdarzeń.

## Kolejność integracji

#45 nie zawiera kodu obliczeń z #44. API koordynatora działa samodzielnie,
ale klient transportu wymaga #44. Dla pełnego uruchomienia na `main` należy
scalić #44 przed uruchamianiem klientów (zalecana kolejność: #44, #45, #46).
Nie jest wymagane łączenie zmian w jeden PR. Samo zatwierdzenie kontraktu nie
scala żadnego PR; integrację wykonują opiekunowie repozytorium.
