# Niezależne węzły DH — Issue #36

Każdy proces Alice/Bob ładuje CryptoCore przez istniejący adapter
`backend.app.crypto_core.CryptoCore`. `DhNode` przechowuje jedną ulotną sesję
i wyłącznie własny wykładnik. `start_session()` oblicza `g^secret mod p`,
a `receive_public()` oblicza `received_public^secret mod p`. Obie operacje
wywołują `radh_modexp_u32()` w C; nie używają centralnej wymiany DH.

`node.py` nie zależy od transportu. `__main__.py` jest lokalnym narzędziem
JSON Lines (jedno polecenie na linię stdin, jedna odpowiedź na linię stdout).
Nie jest serwerem ani koordynatorem. `testing.py` wydziela deterministyczne
ustawienie sekretu. Zwykły węzeł losuje go przez `secrets.randbelow(UINT32_MAX) + 1`
przy każdej nowej sesji. Losowanie może przypadkiem dać tę samą liczbę.

**Wyłącznie edukacja:** liczby 32-bitowe, brak uwierzytelniania, KDF i ochrony
przed MITM. To nie jest narzędzie do zabezpieczania rzeczywistych danych.

## Budowanie i uruchomienie

Wymagane: Python 3.11+, CMake 3.20+ i kompilator C11. Same węzły wymagają
wyłącznie biblioteki standardowej Pythona oraz skompilowanego CryptoCore.
Wszystkie polecenia wykonuj z katalogu głównego repozytorium:

```sh
cmake -S crypto-core -B crypto-core/build
cmake --build crypto-core/build
ctest --test-dir crypto-core/build --output-on-failure
```

Biblioteka jest wyszukiwana w `crypto-core/build`, także w podkatalogach
`Debug`, `Release`, `RelWithDebInfo`, `MinSizeRel`: `.so` na Linux,
`.dylib` na macOS i `.dll` na Windows. Można ustawić pełną ścieżkę przez
`RADH_CRYPTO_CORE_LIBRARY`. Dla generatorów wielokonfiguracyjnych dodaj
`--config Release` do budowania oraz `-C Release` do CTest.

Terminal Alice:

```sh
python -m nodes --role alice
```

Terminal Bob:

```sh
python -m nodes --role bob
```

W obu terminalach wpisz:

```json
{"op":"start","session_id":"demo-1","p":23,"g":5}
```

Odpowiedź zawiera `pid` oraz publiczny `state`, w tym `public_value`.
Przepisz wartość Boba do Alice, a wartość Alice do Boba:

```json
{"op":"receive","session_id":"demo-1","public_value":19}
```

Liczba 19 powyżej jest przykładem; w zwykłym trybie użyj faktycznej wartości
Boba. `{"op":"state"}` odczytuje bieżący stan. EOF lub Ctrl+C kończy proces;
ponowne uruchomienie zaczyna od `idle` bez poprzedniej sesji.
Na Windows EOF w terminalu to Ctrl+Z i Enter, na Linux/macOS Ctrl+D.

## Referencyjna wymiana i lokalny tryb testowy

Uruchom dwa osobne terminale Linux/macOS:

```sh
# Terminal Alice — tylko jej lokalny sekret
RADH_NODE_TEST_SECRET=6 python -m nodes --role alice --test-mode --allow-diagnostics
```

```sh
# Terminal Bob — tylko jego lokalny sekret
RADH_NODE_TEST_SECRET=15 python -m nodes --role bob --test-mode --allow-diagnostics
```

PowerShell, odpowiednio w każdym terminalu:

```powershell
$env:RADH_NODE_TEST_SECRET = '6'
python -m nodes --role alice --test-mode --allow-diagnostics
Remove-Item Env:RADH_NODE_TEST_SECRET
```

Dla Boba ustaw `15` i `--role bob`. Zmienna jest odczytywana tylko lokalnie;
nie jest polem polecenia `start` ani komunikatem koordynatora. Bez `--test-mode`
obecność zmiennej powoduje kontrolowany błąd konfiguracji. W trybie testowym
kolejne sesje celowo używają tej samej lokalnej wartości. Nie używaj prawdziwych
sekretów: środowisko procesu i historia terminala nie są bezpiecznym magazynem.

W obu procesach:

```json
{"op":"start","session_id":"reference","p":23,"g":5}
```

Alice zwraca `public_value: 8`, Bob `public_value: 19`.
Do Alice wyślij:

```json
{"op":"receive","session_id":"reference","public_value":19}
```

Do Boba wyślij:

```json
{"op":"receive","session_id":"reference","public_value":8}
```

Oba stany to `complete`. W każdym terminalu jawnie odczytaj wynik lokalny:

```json
{"op":"diagnostics"}
```

Alice zwraca `{"diagnostics":{"participant":"alice","session_id":"reference","shared_secret":2}}`,
Bob analogicznie `participant: "bob"` i `shared_secret: 2`.
Diagnostyka wymaga `--allow-diagnostics`, nie ujawnia wykładnika i nie jest
komunikatem wymiany. Nie przekazuj jej do partnera ani dziennika koordynatora.
Standardowe odpowiedzi nigdy nie zawierają wykładnika ani wspólnego sekretu.

## Interfejs integracyjny dla Daniela (#37)

W sprawdzonych opisach #16, #36, #37 oraz komentarzach #37 nie ma jeszcze
uzgodnionego schematu HTTP. Poniższy kontrakt dotyczy obliczeń i lokalnego
uruchomienia; nie narzuca endpointów HTTP ani schematu zdarzeń.

```python
from nodes import DhNode

node = DhNode("alice")  # tworzony wewnątrz procesu Alice
state = node.start_session(session_id="session-1", p=23, g=5)
# Transport wysyła wyłącznie state.public_value i publiczne metadane.
state = node.receive_public(session_id="session-1", public_value=19)
state = node.state
# Wyłącznie jawna lokalna diagnostyka edukacyjna:
result = node.diagnostics()
```

| Operacja | Wejście | Wynik i zachowanie |
| --- | --- | --- |
| `DhNode(participant, core=None)` | lokalna nazwa uczestnika, opcjonalny istniejący adapter | stan `idle`; brak sekretu partnera |
| `start_session(session_id, p, g)` | niepusty identyfikator do 128 znaków, liczby całkowite uint32 | nowy sekret i `NodeState` w fazie `public_ready` |
| `receive_public(session_id, public_value)` | identyfikator aktywnej sesji i `1 <= value < p` | `NodeState` w fazie `complete` |
| `state` | brak | niemutowalny `NodeState`, bez sekretów |
| `diagnostics()` | jawne lokalne wywołanie po ukończeniu | uczestnik, sesja, wspólny sekret; nigdy wykładnik |

`NodeState` zawiera dokładnie: `participant`, `session_id`, `phase`, `p`, `g`,
`public_value`, `received_public`. Przed inicjalizacją pola sesji są `None`.
Przekazuj stan przez `dataclasses.asdict(node.state)`, nie serializuj wnętrza
obiektu `DhNode`. Nazwa uczestnika może być innym identyfikatorem Pythona,
co pozwala wykorzystać ten sam moduł obliczeń w #40 bez implementowania MITM tutaj.
CLI obsługuje także Mallory, opisany poniżej.

Zasady sesji:

- `p` musi być pierwsza; `2 <= g < p`; generator nie musi być pierwotny.
  Sekret lokalny mieści się w `1..UINT32_MAX`. `bool`, `float`, `str` jako
  liczby są odrzucane. Publiczna wartość 1 jest dozwolona.
- Ponowny start z aktywnym identyfikatorem zwraca `SESSION_ALREADY_STARTED`.
  Nowy identyfikator rozpoczyna nową sesję i usuwa poprzedni wynik.
- Odbiór przed startem daje `NOT_INITIALIZED`; obca sesja `SESSION_MISMATCH`.
  Identyczny duplikat odbioru jest idempotentny. Inna wartość po ukończeniu
  daje `PUBLIC_VALUE_CONFLICT`.
- Błąd walidacji lub C zachowuje ostatni poprawny stan i wynik. Stan jest
  podmieniany dopiero po zakończeniu obliczenia C.
- `NodeError` udostępnia `code` i `message`; kody walidacji to
  `INVALID_PARTICIPANT`, `INVALID_SESSION`, `INVALID_PRIME`, `INVALID_GENERATOR`,
  `INVALID_SECRET`, `INVALID_PUBLIC_VALUE`. Diagnostyka przed ukończeniem:
  `NOT_COMPLETE`. Adapter zgłasza istniejące `CryptoCoreLoadError`,
  `CryptoCoreInputError`, `CryptoCoreCallError` (z `status` i `code`).
- Wywołania jednej instancji muszą być sekwencyjne. Adapter HTTP powinien
  serializować obsługę poleceń w procesie węzła. Nie twórz Alice i Boba
  we wspólnym procesie FastAPI.
- Węzeł pamięta tylko bieżącą sesję. Koordynator zapewnia unikalne identyfikatory
  i odrzuca ponowne użycie dawnych identyfikatorów oraz spóźnione polecenia startu.
  Restart traci całą sesję; koordynator musi rozpocząć nową.

Lokalny JSON Lines przyjmuje dokładnie pola pokazanych wyżej poleceń
`start`, `receive`, `state`, `diagnostics`; dodatkowe pola (także sekret)
są odrzucane. Błędy mają postać `{"error":{"code":"...","message":"..."}}`
i nie zawierają danych wejściowych. Proces po błędzie czyta następne polecenie.
PID jest lokalną diagnostyką procesu, nie polem przyszłego komunikatu HTTP.

Zakres #37: rejestr sesji FastAPI, transport HTTP w procesach, walidacja
nadawcy/odbiorcy i ról, routing, kolejność wiadomości, historia zdarzeń,
statusy dla frontendu i mapowanie błędów HTTP. Wymiana przez HTTP oraz frontend
z PBI-012 pozostają do integracji. Zakres #36 kończy się na obliczeniach,
interfejsie agenta i lokalnym uruchamianiu/testowaniu niezależnych procesów.
Dotychczasowe endpointy `/api/v1/rsa/demo/encrypt` oraz
`/api/v1/dh/demo/exchange` pozostają bez zmian.

## Testy

Po kompilacji C, w środowisku z zależnościami testowymi projektu:

```sh
python -m pip install -r tests/requirements.txt
python -m pytest
python -m pytest tests/test_nodes.py -v
python -m pytest tests/test_nodes.py -k subprocess -v
```

Test procesowy uruchamia dwa jednocześnie działające procesy przez `subprocess`,
sprawdza różne PID, przekazuje tylko publiczne liczby, osobno odczytuje lokalne
K i sprawdza `A=8`, `B=19`, `K_A=K_B=2`. Wykorzystuje limity czasu i sprząta
procesy. Sprawdza też błędne polecenia, brak sekretów w standardowych odpowiedziach,
zatrzymanie i restart. Pozostałe testy sprawdzają walidację, reset, niezależność
stanów, ABI adaptera i zachowanie po błędzie C. Istniejący workflow CI zbiera
nowy plik przez zwykłe `python -m pytest`.

## Mallory — Issue #40

`MalloryNode` z `nodes/mallory.py` składa się z dwóch prywatnych instancji
`DhNode`. Pierwsza losuje x do wymiany z Alice, druga y do wymiany z Bobem.
Obie używają istniejącego adaptera i C. Nowa sesja zastępuje starą dopiero po
udanym wyliczeniu obu wartości publicznych. Błąd C lub walidacji zachowuje
ostatni poprawny stan. Losowania są niezależne (mogą przypadkiem dać tę samą
liczbę). Restart procesu usuwa sesję. Python nie gwarantuje fizycznego
wyzerowania zwolnionej pamięci.

Normalne uruchomienie trzeciego terminala, po kompilacji opisanej powyżej:

```sh
python -m nodes --role mallory
```

Lokalny test referencyjny Linux/macOS:

```sh
RADH_MALLORY_TEST_X=7 RADH_MALLORY_TEST_Y=11 python -m nodes --role mallory --test-mode --allow-diagnostics
```

PowerShell:

```powershell
$env:RADH_MALLORY_TEST_X = '7'
$env:RADH_MALLORY_TEST_Y = '11'
python -m nodes --role mallory --test-mode --allow-diagnostics
Remove-Item Env:RADH_MALLORY_TEST_X, Env:RADH_MALLORY_TEST_Y
```

Obie zmienne są wymagane w trybie testowym Mallory. Bez `--test-mode`
ich obecność jest błędem konfiguracji. Mallory odrzuca
`RADH_NODE_TEST_SECRET`; zmienne Mallory są odrzucane dla roli Alice/Bob.
Nie przesyłaj konfiguracji sekretów przez JSON ani koordynator.
W trybie testowym wartości są celowo ponownie używane w kolejnych sesjach.

Wpisz po jednej linii:

```json
{"op":"start","session_id":"attack-1","p":23,"g":5}
{"op":"receive","session_id":"attack-1","source":"alice","public_value":8}
{"op":"receive","session_id":"attack-1","source":"bob","public_value":19}
{"op":"state"}
{"op":"diagnostics"}
```

Start daje `substitute_to_alice=17` (X) i `substitute_to_bob=22` (Y).
Po odbiorze stan zawiera `original_from_alice=8` (A),
`original_from_bob=19` (B). Diagnostyka zwraca:

```json
{"diagnostics":{"participant":"mallory","session_id":"attack-1","shared_with_alice":12,"shared_with_bob":22}}
```

Alice z lokalnym a=6, otrzymując X=17, obliczy K_A=12.
Bob z lokalnym b=15, otrzymując Y=22, obliczy K_B=22.
Mallory zna tylko x, y oraz publiczne A, B: K_MA=12, K_MB=22.
Zwykły stan i odpowiedzi nie zawierają x, y ani K. Diagnostyka CLI wymaga
`--allow-diagnostics` i ukończenia obu wymian; wcześniej daje
`DIAGNOSTICS_DISABLED` lub `NOT_COMPLETE`. Wyników diagnostycznych nie
należy przekazywać jako wiadomości protokołu.

### Kontrakt obliczeń dla #41

```python
from nodes import MalloryNode

node = MalloryNode()
node.start_session("attack-1", 23, 5)
node.receive_public("attack-1", source="alice", public_value=8)
node.receive_public("attack-1", source="bob", public_value=19)
state = node.state
# Wyłącznie na jawne żądanie diagnostyki lokalnej:
diagnostics = node.diagnostics()
```

`MalloryState` jest niemutowalny i zawiera dokładnie:
`participant`, `session_id`, `phase`, `p`, `g`,
`original_from_alice`, `original_from_bob`,
`substitute_to_alice`, `substitute_to_bob`.
Przed startem pola sesji mają wartość `None`.
Fazy: `idle`, `public_ready`, `partial` (odebrana jedna strona),
`complete` (obie strony). A i B można dostarczyć w dowolnej kolejności.

`source` jest obowiązkowe tylko dla polecenia odbioru Mallory.
Dopuszczalne wartości to dokładnie `alice` i `bob`; inne dają
`INVALID_SOURCE`. Pozostałe reguły walidacji i kody błędów pochodzą z
`DhNode`: identyczny duplikat jest idempotentny, konflikt odrzucany,
stary identyfikator niedopuszczalny, ponowny start aktywnego ID odrzucany.
Nowe ID resetuje obie strony i oba wyniki. Wywołania muszą być sekwencyjne.

Routing #41 powinien dostarczyć oryginalne A/B do odpowiedniej strony Mallory,
a Alice wysłać X i Bobowi Y. Rzeczywisty routing MITM, HTTP, heartbeat Mallory
i ewentualny osobny format diagnostyki koordynatora pozostają zakresem #41.
Obecny `backend.dh_transport` oraz modele HTTP obsługują Alice/Bob;
nie uruchamiaj nimi Mallory przed implementacją #41.
To nadal demonstracja edukacyjna na liczbach 32-bitowych.

Testy lokalne:

```sh
python -m pytest tests/test_mallory_nodes.py -v
python -m pytest tests/test_nodes.py -v
python -m pytest
```
