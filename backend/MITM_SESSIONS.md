# Routing MITM — #41

Rozszerzenie [kontraktu sesji](DH_SESSIONS.md). Obliczenia Mallory dostarcza
#40 / PR #49 (`94c638e91527435d9578dcd02f4d55290d0cb910`). Backend nie generuje
X/Y, nie zna x/y i nie oblicza kluczy. `backend.dh_transport --role mallory`
działa w osobnym procesie i wywołuje `MalloryNode` zgodnie z `nodes/README.md`.
Do uruchomienia tego procesu wymagane jest scalenie #49; API działa bez niego.
Kod #40 nie jest kopiowany do tej zmiany. Frontend MITM należy dostosować w #42.

## Uruchomienie

Po zbudowaniu CryptoCore i instalacji zależności uruchom serwer w pierwszym
terminalu (z katalogu głównego projektu):

```sh
python -m uvicorn app.main:app --app-dir backend --workers 1
```

Trzy kolejne terminale, lokalny scenariusz referencyjny Linux/macOS:

```sh
RADH_NODE_TEST_SECRET=6 python -m backend.dh_transport --role alice --test-mode --allow-diagnostics
```

```sh
RADH_NODE_TEST_SECRET=15 python -m backend.dh_transport --role bob --test-mode --allow-diagnostics
```

```sh
RADH_MALLORY_TEST_X=7 RADH_MALLORY_TEST_Y=11 python -m backend.dh_transport --role mallory --test-mode --allow-diagnostics
```

W PowerShell ustaw odpowiednie `$env:RADH_MALLORY_TEST_X = '7'` i
`$env:RADH_MALLORY_TEST_Y = '11'`, następnie uruchom polecenie Pythona.
Sekrety są wyłącznie lokalną konfiguracją procesu, nigdy treścią HTTP.
Bez `--test-mode` procesy losują sekrety; usuń wtedy zmienne testowe.
Bez `--allow-diagnostics` proces nie odczytuje ani nie wysyła swoich K.
Samo `python -m nodes --role mallory` obsługuje JSON Lines, nie HTTP.

## Kontrakt dla #42

Utworzenie: `POST /api/v1/dh/sessions` z
`{"prime":23,"generator":5,"mode":"mitm"}`, następnie `POST /{id}/start`.
Tryb jest ustalony przy tworzeniu, nie ma operacji jego zmiany.
`normal` nadal działa bez Mallory i ma dotychczasowe 7 zdarzeń.

`GET /api/v1/dh/nodes` zawiera teraz trzy klucze: `alice`, `bob`, `mallory`.
Każdy ma dotychczasowe `online` i `last_seen`. Mallory wysyła
`POST /api/v1/dh/nodes/mallory/heartbeat` bez ciała (204), co 1 s w niezależnym
wątku. TTL wynosi 5 s. Start MITM przy braku świeżego heartbeat zwraca
409 `MALLORY_UNAVAILABLE`; sesja pozostaje `created` i może być uruchomiona
ponownie lub anulowana. Normalny start nie wymaga tego heartbeat.

`GET /sessions/{id}` zachowuje `participants.alice/bob` i dodaje
`interceptions` (pusta lista w trybie normal). Przykładowy rekord po dostarczeniu:

```json
{
  "message_id": "alice-public",
  "original_sender": "alice",
  "recipient": "bob",
  "original_value": 8,
  "delivered_value": 22,
  "intercepted_by": "mallory",
  "actual_sender": "mallory",
  "status": "processed"
}
```

Przed podmianą `delivered_value` i `actual_sender` są `null`.
Stany rekordu: `pending` → `forwarded` → `processed`.
`pending` oznacza skierowanie oryginału do kolejki Mallory, nie potwierdzenie,
że jej proces już go odebrał. `forwarded` oznacza otrzymaną od procesu podmianę,
a `processed` ACK odbiorcy po jego obliczeniu.

`messages[].status` ma nową wartość `intercepted`. Taka wiadomość jest widoczna
w publicznym podglądzie sesji, ale nigdy w kolejce Alice/Boba i nie można jej
potwierdzić. Początkowo `public_value` zawiera oryginał; po podmianie zawiera
wartość przeznaczoną do doręczenia, a status zmienia się na `queued`.
Po ACK jest `processed`. `sender` pozostaje deklarowaną tożsamością partnera
(podszycie); faktyczny nadawca i oryginał są jawne w `interceptions`.
**W trybie MITM publiczną wartość własną A/B należy brać z `original_value`,
a wartość otrzymaną z `delivered_value`, nie wyprowadzać obu z `messages`.**

Dziennik zachowuje `sequence`, `message_id`, `sender`, `recipient`,
`public_value`, `status`. Dwa nowe typy zdarzeń:

- `message_intercepted`: nadawca Alice/Bob, wartość oryginalna, status `intercepted`;
- `message_forwarded`: nadawca `mallory`, zamierzony odbiorca, wartość podmieniona,
  status `queued`.

Dotychczasowe `message_processed` identyfikuje deklarowanego nadawcę i odbiorcę,
zawiera już podmienioną wartość. `message_id` łączy wszystkie zdarzenia z rekordem
przechwycenia. Pełna wymiana MITM ma 9 zdarzeń: utworzenie, start, po dwa
przechwycenia, podmiany i ACK, zakończenie. Kolejność A/B może być dowolna.
Frontend musi rozszerzyć walidację typów zdarzeń, statusu wiadomości i roli
nadawcy zdarzenia. Dotychczasowy frontend #38 obsługuje nadal tryb normal.

## Kontrakt transportu Mallory

Prefiks `/api/v1/dh/sessions/{id}`:

| Żądanie | Wynik |
| --- | --- |
| `GET /interceptions` | Lista wszystkich oryginałów wraz ze stanem podmiany |
| `POST /interceptions/{message_id}/forward` z `{"public_value":22}` | 200, aktualny rekord przechwycenia |
| `GET /diagnostics/mallory` | `{"shared_with_alice":12,"shared_with_bob":22}` lub wartości null |
| `POST /diagnostics/mallory` z obiema wartościami K | 204 |

W pętli transport odbiera wyłącznie sesje MITM. Wywołuje lokalnie
`start_session(id, prime, generator)`, następnie dla każdego oryginału
`receive_public(id, source=original_sender, public_value=original_value)`.
Dla oryginalnego A skierowanego do Boba odsyła `substitute_to_bob` (Y).
Dla B skierowanego do Alice odsyła `substitute_to_alice` (X).
Instancja agenta jest obsługiwana sekwencyjnie; heartbeat nie dotyka jej stanu.

Wiadomość jest uwalniana do kolejki ofiary atomowo z zapisem podmiany i zdarzenia.
Nie można ustawić odbiorcy ani nadawcy w żądaniu `forward` — wynikają z oryginału.
Identyczne ponowienie jest bezpieczne również po `completed`; sprzeczna wartość
daje 409 `REPLACEMENT_CONFLICT`. Ponowienie publikacji A/B jest porównywane
z oryginałem, nie z wartością już podmienioną. Przed podmianą ACK daje
409 `INTERCEPTION_REQUIRED`. Nieznane ID to 404 `MESSAGE_NOT_FOUND`.
Zła wartość daje 422 `INVALID_MESSAGE`, błędny typ/dodatkowe pola
422 `INVALID_REQUEST`. Operacje przechwycenia w `normal` dają 409 `MITM_REQUIRED`.
Zachowany jest wspólny format `{"error":{"code":"...","message":"..."}}`.

## Diagnostyka i niepełna wymiana

Dotychczasowe `/diagnostics` Alice/Boba pozostaje bez zmian.
Dwa K Mallory mają osobny endpoint i osobny magazyn, bez wpisów w protokole/logu.
Transport publikuje je tylko za flagą, po odebraniu obu oryginałów i przekazaniu
obu podmian; ponawia także po `completed`. API wymaga obu podmian
(409 `FORWARD_REQUIRED`), zakresu `1 <= K < prime` (422 `INVALID_DIAGNOSTIC`)
i zgodności powtórzeń (409 `DIAGNOSTIC_CONFLICT`). Odczyt bez raportu daje null.
Nowa sesja usuwa poprzednią diagnostykę. `completed` nadal oznacza dwa ACK,
nie obecność ani potwierdzenie poprawności K przez serwer.

Utrata kontaktu z Mallory w trakcie sesji nie uruchamia routingu bez ataku.
Oczekujące oryginały pozostają zablokowane; API pokazuje niepełny stan sesji
oraz osobno dostępność procesu. Można poczekać na powrót połączenia lub anulować
sesję istniejącym `/cancel`. Nie wprowadzamy automatycznego timeoutu sesji.
Po restarcie procesu losowe sekrety są utracone; sprzeczność z wcześniejszą
podmianą jest odrzucana. W takim przypadku należy anulować i stworzyć nową sesję.
Anulowana sesja odrzuca nowe podmiany i diagnostykę, stary identyfikator po
utworzeniu kolejnej sesji daje 404.

To lokalny demonstrator bez uwierzytelniania. Kontrola routingu zapobiega
przypadkowemu doręczeniu oryginału przez API kolejek; nie uwierzytelnia klienta
wywołującego `forward` ani nie ukrywa publicznych wartości w podglądzie sesji.

## Testy

```sh
python -m pytest tests/test_mitm_sessions.py -q
python -m pytest tests/test_mitm_transport_live.py -q
python -m pytest -q
```

Testy API sprawdzają brak obejścia, konflikty i atomowość podmian, walidację,
wygaśnięcie heartbeat, anulowanie, niepełną wymianę i oddzielną diagnostykę.
Testy transportu z dublerem publicznych wartości sprawdzają utratę odpowiedzi
przed/po przyjęciu operacji, ponowienia i odrzucanie uszkodzonych odpowiedzi.
Test procesowy uruchamia prawdziwe Alice/Bob/Mallory i CryptoCore: normal → MITM
→ normal po wyłączeniu Mallory, z diagnostyką oraz bez niej. Ten test jest
jawnie pomijany, jeśli nie ma jeszcze modułu #40. Po scaleniu #49 zwykły pytest
w istniejącym CI uruchamia go automatycznie. Nie zastępuje pełnego zakresu #43.
