# Wielosesyjne procesy DH — #68

Źródło prawdy: [kontrakt #73](../docs/architecture/multi-session.md).
Ta implementacja jest klientem przyszłego koordynatora #69. Nie dodaje serwera,
nie zmienia v1, Compose, CryptoCore ani frontendu. Weryfikacja z mockiem nie
stanowi pełnego end-to-end z backendem Daniela ani testów systemowych #71.

## Architektura i synchronizacja

Jeden proces każdej roli, wewnątrz niego `MultiSessionTransport`:

- `internal_models.py`: ścisłe modele discovery, wiadomości, przechwyceń,
  heartbeat i odpowiedzi fail; dodatkowe pola i niewłaściwe typy są odrzucane.
- `internal_http.py`: synchroniczny klient HTTP(S), bez redirectów i proxy z env.
  Maks. 4 operacje HTTP, connect 3 s, całe żądanie 5 s, body 4096 B,
  odczyt odpowiedzi maks. 131072 B przed JSON. Ograniczony do liczby żądań timer
  zamyka kierunek socketu po deadline, także przy powolnych nagłówkach.
- `multi_session.py`: ograniczona mapa `(backend_epoch, session_id)` oraz
  stała pula dwóch zadań. Jeden wpis ma najwyżej jedno zadanie. Brak kolejki
  ponad dwa zgłoszone futures; rotacja wpisów daje round-robin. Każdy nowy
  agent jest nowym `DhNode` / `MalloryNode`; obliczenia nadal wykonuje C.
- Główny wątek pobiera discovery co 1 s ±20%; osobny wątek wysyła heartbeat
  co 2 s. Dwa wątki sesyjne mogą czekać na sieć/C bez zatrzymywania heartbeat.
  Wątki timerów HTTP są krótkotrwałe i ograniczone do czterech; nie ma wątku
  ani procesu per sesja. Semafor ogranicza HTTP niezależnie od liczby agentów.
- Krótki `RLock` chroni rejestr, rezerwacje, aktualność i planowanie. Sieć/C
  nie są wykonywane pod tym lockiem. `busy` rezerwuje wpis do zakończenia
  zadania; tylko jego worker zmienia stan protokołu. Discovery aktualizuje
  deskryptor i może unieważnić wpis. Przed/po HTTP i C sprawdzana jest jego
  tożsamość w mapie, epoch, rejestracja, deadline i stan terminalny.

Wpis przechowuje własne flagi publikacji, ACK, zbiór maks. dwóch forwardów,
stan diagnostyki, deadline, retry oraz agenta. Jego repr nie serializuje sekretów.
Limit agentów/rezerwacji to `MAX_NODE_AGENTS` (1..128, domyślnie 128).
Metadane odmowy/terminalizacji pozostają ograniczone pełnym snapshotem (128),
aby nie regenerować agentów po błędzie. NODE_CAPACITY wysyłany jest przez /fail;
nie nadpisuje istniejącego agenta. Nie ma rosnącego used_ids.

## Uruchomienie dopiero z #69

Zbuduj C zgodnie z README i zainstaluj `backend/requirements.txt` (Pydantic).
Operator generuje oddzielny losowy token 256-bitowy base64url dla każdej roli,
np. `secrets.token_urlsafe(32)`, i zapisuje w osobnych plikach poza repozytorium.
Pliki wymagają uprawnień odczytu tylko odpowiednich użytkowników usług. Backend
musi mieć odpowiadające im skróty i przypisania ról. Nie kopiuj plików do obrazu.

Trzy osobne terminale (ścieżki są przykładami, pliki musi dostarczyć operator):

```sh
RADH_ALICE_TOKEN_FILE=/run/secrets/alice python -m nodes.multi_session_cli --role alice --url http://127.0.0.1:8000
RADH_BOB_TOKEN_FILE=/run/secrets/bob python -m nodes.multi_session_cli --role bob --url http://127.0.0.1:8000
RADH_MALLORY_TOKEN_FILE=/run/secrets/mallory python -m nodes.multi_session_cli --role mallory --url http://127.0.0.1:8000
```

| Konfiguracja | Znaczenie |
| --- | --- |
| `RADH_ALICE_TOKEN_FILE` / `RADH_BOB_TOKEN_FILE` / `RADH_MALLORY_TOKEN_FILE` | Plik tokenu wybranej roli, 43 znaki base64url, opcjonalny końcowy newline |
| `RADH_COORDINATOR_URL` / `--url` | Domyślnie http://127.0.0.1:8000; bez credentials/query/path; HTTPS poza zaufaną siecią |
| `MAX_NODE_AGENTS` | Liczba agentów/rezerwacji 1..128 |
| `--allow-diagnostics` | Lokalny opt-in; wymagane też diagnostics_enabled sesji |
| `RADH_CRYPTO_CORE_LIBRARY` | Dotychczasowa ścieżka do biblioteki C |

Nowy CLI nie akceptuje zmiennych deterministycznych sekretów. Testy wstrzykują
fabrykę z `nodes.testing`, nigdy nie przesyłają wykładników do koordynatora.
SIGINT/SIGTERM zatrzymuje planowanie, pozwala ograniczonym timeoutami zadaniom
wrócić i usuwa rejestr. Python nie gwarantuje fizycznego wyzerowania pamięci.
Odwołanie tokenu: zatrzymać usługę, wymienić plik i kontrolowanie uruchomić ją
ponownie (nowe instance_id); bez rotacji na gorąco w #68.

## HTTP, retry i fencing

Heartbeat wysyła `{instance_id}` i Bearer roli. Inne operacje dodatkowo wysyłają
X-Backend-Epoch i X-Node-Instance. Każda odpowiedź musi zawierać epoch zgodny
z treścią; nowy epoch może przyjąć tylko poprawny heartbeat. Wykrycie zmiany
unieważnia całą mapę i wymusza rejestrację; stare wyniki nie wracają do rejestru.
Nowa instancja procesu nigdy nie wczytuje starych sekretów z dysku.

Publikacja używa `{message_id,type,public_value}`, ACK nie ma ciała, forward
ma wyłącznie `{public_value}`. Nie ma recipient/sender w żądaniach v2.
Identyfikatory alice-public/bob-public są lokalne dla sesji. Ponowienie zachowuje
agenta, wykładnik i wyliczone wartości. Mallory przetwarza tylko MITM; oryginalne
A kieruje do swojego agenta Alice, ale podstawia Y Bobowi; dla B odwrotnie.
Sprawdza też zgodność już zapisanych podmian przed kolejnym forward.

Błędy sieci/odpowiedzi: backoff 0,5/1/2/4/8 s ±20%, Retry-After do 30 s;
po 30 s nieudanego kroku zgłasza LOCAL_STATE_LOST, ponowienia fail są ograniczone.
Pojedynczy poprawny odczyt nie zeruje retry nieudanego ACK/forward.
401 / ROLE_FORBIDDEN zatrzymuje całą rolę, ROLE_NOT_ASSIGNED tylko dany wpis,
DIAGNOSTICS_DISABLED wyłącza raportowanie danego wpisu. 404/410/422 oraz
terminalne konflikty wyłączają wpis. Błąd C raportuje CRYPTO_CORE_ERROR bez
argumentów i bez nadpisania wyniku innych sesji. Kolejne operacje wymagają
żywego lease; po jego utracie (10 s) proces kończy się z błędem zamiast losować
sekrety dla tych samych aktywnych sesji. Pierwsza rejestracja ma budżet 30 s.
To zachowanie zachowawcze; nadzorca może uruchomić proces z nowym instance_id.

Zniknięcie ze snapshotu usuwa wpis; cancelled/expired/failed usuwa agenta.
Lokalny deadline bieżącej sesji nie jest wydłużany odczytem. Completed nie
uruchamia nowego agenta. Istniejący agent pozostaje na diagnostykę maks. 30 s
od pierwszej obserwacji completed, bez przedłużania okna kolejnym discovery;
przy braku opt-in / potwierdzonym raporcie jest usuwany od razu.

## Uzgodnienie i wspólna integracja z Danielem

1. Potwierdzić dokładne modele i nagłówki internal z multi-session.md. W #69
   Discovery jest pełnym, maks. 128-elementowym snapshotem przypisań instancji,
   nie stroną/paginacją i nie listą globalnie widoczną wszystkim rolom.
2. Koordynator musi przypinać instance_id przy starcie, odrzucać stare epoch
   i instancje, kończyć sesje po utracie lease oraz nie przypisywać starych
   running do nowego procesu. Sam klient nie może dowieść, że świeży deskryptor
   po restarcie dotyczy sekretów utraconej instancji.
3. Zapewnić idempotentny POST messages/ACK/forward/diagnostics i /fail, oraz
   participant_status=received po ACK, także przy utracie jego odpowiedzi.
4. Niejednoznaczność kontraktu: Descriptor nie zawiera terminal_at, więc ścisły
   czas 30 s od terminalizacji serwera nie jest wyznaczalny. Implementacja
   ogranicza retencję do 30 s od pierwszej obserwacji. Nie dodano pola API;
   przed integracją uzgodnić z #69 sposób skrócenia okna o opóźnienie discovery.
5. Uzgodnić odpowiedź publikacji w MITM po retry już podmienionej wiadomości:
   obecny Message z v1 może zawierać wartość doręczoną. Klient nie porównuje
   jej z oryginalną A/B w MITM; forward jest weryfikowany z oryginałem osobno.
6. Po scaleniu #69 połączyć rzeczywiste trzy procesy z API, wykonać równoległe
   normal/MITM, test restartów/fencing/obcych ról i pełną macierz #71. Dopiero
   wspólnie z #70 przełączyć uruchomienie/Compose na v2. Bez fallbacku do v1.

## Testy komponentowe

```sh
cmake -S crypto-core -B crypto-core/build
cmake --build crypto-core/build
ctest --test-dir crypto-core/build --output-on-failure
python -m pytest tests/test_multi_session -v
python -m pytest tests/test_dh_nodes/test_nodes.py tests/tests_mitm/test_mallory_nodes.py -v
python -m pytest
```

Testowy koordynator jest w test_nodes_v2.py, granica HTTP w test_internal_http.py.
To kontrolowane mocki, bez socketów. Wektory DH i MITM wylicza rzeczywisty C;
transportowe odpowiedzi mocka nie wpisują kluczy do agentów. Nie dowodzi to
jeszcze współpracy HTTP z niezaimplementowanym #69.
