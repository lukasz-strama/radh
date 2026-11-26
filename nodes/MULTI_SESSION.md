# Wielosesyjne procesy DH

Procesy łączą się z koordynatorem v2 przez istniejący transport HTTP.
Scenariusze `classic` i `authenticated` korzystają z tych samych procesów,
puli zadań i mechanizmów izolacji. [Kontrakt wielosesyjny](../docs/architecture/multi-session.md) ·
[Kontrakt podpisanego DH](../backend/AUTHENTICATED_DH.md)

## Architektura i synchronizacja

Jeden proces każdej roli, wewnątrz niego `MultiSessionTransport`:

- `internal_models.py`: ścisłe modele discovery, wiadomości, przechwyceń,
  heartbeat, uwierzytelniania i odpowiedzi fail. Dodatkowe pola i niewłaściwe
  typy są odrzucane.
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

## Uruchomienie

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
od pierwszej obserwacji completed, w granicach okna koordynatora raportowanego
w discovery. Przy braku opt-in lub potwierdzonym raporcie jest usuwany od razu.

## Przebieg scenariusza uwierzytelnionego

Przy `scenario=authenticated` Alice i Bob generują osobne klucze RSA i DH dla
każdej sesji. Najpierw publikują `n,e`, potem własną wartość DH.
W kolejnych iteracjach odczytują zaufane klucze oraz faktycznie doręczoną
wartość partnera. Wartość czeka w lokalnym stanie do zakończenia weryfikacji.
Węzeł podpisuje reprezentant lokalnego transkryptu przez CryptoCore, zapisuje
podpis do ponowień i zwalnia prywatny wykładnik RSA.

Po otrzymaniu podpisu partnera węzeł buduje transkrypt dla jego roli z
własnego widoku DH. Weryfikacja wymaga poprawnego podpisu RSA i zgodności
pełnych skrótów SHA-256, również gdy same reprezentanty są identyczne.
Po negatywnym raporcie koordynator oznacza sesję jako
`SIGNATURE_VERIFICATION_FAILED`, a węzły zwalniają stan bez obliczania K
na podstawie odrzuconej wartości. Po zaakceptowaniu pozytywnego raportu
węzeł oblicza K i wysyła ACK. Odpowiedź discovery z `verified` potwierdza
raport weryfikacji. Powtórzenie ACK używa zachowanego identyfikatora
wiadomości, nawet po globalnym `completed`.

Brak danych partnera kończy bieżącą iterację. Odpowiedź
`PUBLIC_VALUES_REQUIRED` po próbie publikacji podpisu podlega ograniczonemu
retry, gdy jeszcze trwa doręczanie wartości DH. Powtórzenia wysyłają
identyczne klucze, podpisy i raporty. Mallory przetwarza dotychczasowe
przechwycenia DH. W scenariuszu podpisanym diagnostyka każdej roli jest
dozwolona dopiero po `completed` i podwójnym opt-in.

Zaufanie do publicznych kluczy przekazywanych przez koordynator jest założeniem
demonstracji. Dostęp do API nadal opiera się na tokenach. Edukacyjne podpisy
RSA służą wyłącznie transkryptowi DH.

## Testy komponentowe i procesowe

```sh
cmake -S crypto-core -B crypto-core/build
cmake --build crypto-core/build
ctest --test-dir crypto-core/build --output-on-failure
python -m pytest tests/test_multi_session -v
python -m pytest tests/test_dh_nodes/test_nodes.py tests/test_dh_nodes/test_secret_range.py tests/tests_mitm/test_mallory_nodes.py -v
python -m pytest tests/test_multi_session_live/test_ms_authenticated.py -v
python -m pytest
```

Testy komponentowe sprawdzają klienta i rzeczywiste CryptoCore bez sieci.
Testy procesowe uruchamiają Uvicorn i trzy węzły, wymagają więc lokalnych gniazd TCP.
To kontrolowane mocki, bez socketów. Wektory DH i MITM wylicza rzeczywisty C;
transportowe odpowiedzi mocka nie wpisują kluczy do agentów. Nie dowodzi to
jeszcze współpracy HTTP z niezaimplementowanym #69.
