# Model zagrożeń RADH — STRIDE

Data: 2026-11-17. Podstawa kodu: main a37d066. Zakres: aplikacja WWW,
Python/ctypes/C, procesy DH, kontenery, przyszła wielosesyjność i kanał zgłoszeń.
Dokument jest oceną projektową; nie wynikiem pentestu. Nie wykonywano ataków
na publiczne usługi. Schemat przepływów i granic: [deployment](../architecture/deployment.md).
Kontrakt planowanych zabezpieczeń: [multi-session](../architecture/multi-session.md).

## Aktywa, podmioty i powierzchnie

**Aktywa:** dostępność wspólnego VPS, integralność demonstracji, izolacja sesji,
capability tokeny właścicieli, tokeny ról i klucze TLS, lokalne wykładniki a/b/x/y,
opcjonalne K, logi i diagnostyka, buildy/locki/obrazy, przyszłe zgłoszenia i dane kontaktowe.
Parametry p/g/A/B/X/Y są publiczne kryptograficznie, lecz widok cudzej sesji
nadal wymaga autoryzacji aplikacyjnej.

**Podmioty:** anonimowy użytkownik/właściciel, inny lub złośliwy użytkownik,
przeglądarka/rozszerzenie, procesy Alice/Bob/Mallory, przejęty proces jednej roli,
reverse proxy, operator hosta (zaufany), dostawca VPS, rejestry obrazów/npm/PyPI,
przyszły moderator zgłoszeń. Nie ufamy danym klienta nawet po uwierzytelnieniu.

**Powierzchnie:** każde HTTP body/URL/header i polling; tworzenie, start, ACK,
forward i diagnostyka; JavaScript i browser storage; przekazywanie typów przez
ctypes i ładowanie .so; C i jego nakład CPU; Docker build/runtime/network,
logi/APM, CI i zależności. Przyszłe formularze/załączniki/webhooki zgłoszeń.

**Granice:** Internet ↔ TLS/proxy; proxy ↔ backend; publiczny router ↔ internal;
rola ↔ inna rola; użytkownik ↔ sesja innego użytkownika; Python ↔ natywne C;
proces/container ↔ host; aplikacja ↔ system zgłoszeń; zależności ↔ build.
Prywatna sieć bez auth nie jest wystarczającą granicą roli.

## Metoda oceny 5×5

Prawdopodobieństwo P: 1 rzadkie/wymaga uprawnień operatora, 2 mało prawdopodobne,
3 możliwe, 4 łatwe/powtarzalne, 5 trywialne z publicznego HTTP.
Skutek S: 1 kosmetyczny, 2 jedna demonstracja, 3 wiele sesji/krótka przerwa,
4 wyciek tokenów lub istotna awaria, 5 przejęcie usług/hosta lub trwały wyciek.
Ryzyko R=P×S: 1–4 niskie, 5–9 średnie, 10–16 wysokie, 17–25 krytyczne.
To ryzyko **przed planowanymi mitygacjami dla ekspozycji publicznej aktualnego kodu**.
Nie podajemy fikcyjnej oceny resztkowej: QA i operator wyznaczą ją po dowodach.
Każde wysokie/krytyczne ryzyko oraz brak wymaganej kontroli dostępu blokuje betę.

Statusy: **istnieje** = sprawdzone w kodzie; **częściowo** = istnieje ograniczona
kontrola, reszta planowana; **planowane** = brak implementacji; **poza zakresem
algorytmów** = cel edukacyjny, wymaga ostrzeżeń i ograniczeń użycia.
Właściciel oznacza obszar realizacji, nie zdalne przypisanie issue.

## Rejestr zagrożeń

| ID | Kategoria STRIDE | Zagrożenie | Zasób | Prawdopodobieństwo | Skutek | Ryzyko | Mitigacja | Właściciel | Status |
| --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- |
| S01 | Spoofing | Podszycie pod Alice/Bob przez sender/recipient w body | Wiadomości i ACK | 5 | 4 | 20 krytyczne | Token per rola, sender z tożsamości serwera, macierz uprawnień internal | Daniel #69 + Łukasz #68 | planowane; blokuje |
| S02 | Spoofing | Fałszywy heartbeat Mallory odblokowuje MITM | Obecność i start | 5 | 3 | 15 wysokie | Uwierzytelniony heartbeat, instance_id, lease i przypisanie przy starcie | #68/#69 | planowane; blokuje |
| S03 | Spoofing | Przejęty stary proces kontynuuje sesję po restarcie/duplikacie roli | Sekrety i poprawność przebiegu | 3 | 4 | 12 wysokie | Epoch, fencing instance_id, odmowa drugiej żywej instancji; fail zamiast odtworzenia sekretu | #68/#69 | planowane; blokuje |
| T01 | Tampering | Odczyt/mutacja cudzej sesji po poznaniu ID | Sesja, log, K | 5 | 4 | 20 krytyczne | Oddzielny Owner Bearer, hash tokenu, kontrola każdego endpointu, brak publicznej listy/current | Daniel #69 | planowane; blokuje |
| T02 | Tampering | Dowolny klient podmienia forward lub diagnostykę | X/Y, K i demonstracja | 5 | 4 | 20 krytyczne | Wyłącznie rola Mallory może forward, raport K tylko własnej roli, Owner read-only dla protokołu | #69 | częściowo: walidacja i konflikty są, auth brak; blokuje |
| T03 | Tampering | Duplikaty lub równoległe żądania nadpisują dobry wynik | Stan sesji | 3 | 3 | 9 średnie | Blokady, porównanie treści i idempotencja istnieją w v1; przenieść per sesja, testy wyścigów | #69/#71 | częściowo |
| T04 | Tampering | Stara odpowiedź HTTP zapisuje dane innej sesji w UI/agencie | Izolacja i interfejs | 4 | 3 | 12 wysokie | ID+epoch+requestId, cancellation, rewalidacja przy commit; osobne instancje per sesja | #68/#70 | częściowo: requestId w UI i kontrola ID w DhNode; blokuje |
| T05 | Tampering | Modyfikacja zależności lub obrazu w łańcuchu dostaw | Kod runtime, host | 3 | 5 | 15 wysokie | npm ci, snapshot pip, digesty, hashe artefaktów, SBOM i przegląd aktualizacji, brak sekretów builda | Operator + QA | częściowo: npm lock; reszta gate |
| R01 | Repudiation | Brak śladu kto anulował/zapisał/podmienił | Rozliczalność incydentu | 4 | 3 | 12 wysokie | Oddzielne operacyjne logi roli/operacji/request_id i pseudonimu sesji, retencja 7 dni; auth | #69 + operator | częściowo: log edukacyjny istnieje, nie dowodzi tożsamości; blokuje |
| R02 | Repudiation | Użytkownik traktuje completed jako dowód zgodności kluczy | Rzetelność demonstracji | 3 | 2 | 6 średnie | Classic: completed=2 ACK; authenticated: dodatkowo 2 pozytywne weryfikacje podpisu. K nadal jest deklaracją procesów, nie dowodem serwera | Szymon #70/#104 | kontrakt backendu istnieje; komunikat UI otwarty |
| I01 | Information Disclosure | Globalna sesja i publiczne GET ujawniają dane obcych użytkowników | Wiadomości, diagnostyka | 5 | 4 | 20 krytyczne | Wielosesyjny rejestr + token przy każdym GET, v1 router odcięty, no-store | #69/#70 | planowane; blokuje |
| I02 | Information Disclosure | Prywatne wykładniki/klucze/tokeny w logach, błędach, APM | Sekrety | 3 | 5 | 15 wysokie | Redakcja nagłówków/body/query, brak traceback do klienta, osobne opt-in K, testy wycieku | #68/#69/#71 + operator | częściowo: wyjątki kontrolowane i prywatne wykładniki lokalne; blokuje |
| I03 | Information Disclosure | Poświadczenia usług w env dump, obrazie, repo lub współdzielonym pliku | Tokeny ról, TLS | 3 | 5 | 15 wysokie | Oddzielne pliki _FILE, poprawne UID/tryby, bez ARG/ENV w buildzie, rotacja i skan sekretów | Operator + #68/#69 | planowane; blokuje |
| I04 | Information Disclosure | Cache proxy/browser przechowuje token lub diagnostykę | Owner token, K | 3 | 4 | 12 wysokie | no-store API i create; token w headerze, brak tokenów w URL i serwisie analitycznym | #69/#70 + operator | planowane; blokuje |
| I05 | Information Disclosure | Odczyt pamięci/sekretów innej sesji przez współdzielony obiekt | Wykładniki i K | 4 | 4 | 16 wysokie | Mapy epoch/ID, bez centralnego obiektu z sekretami, cleanup i niemutowalne snapshoty | #68/#69/#71 | planowane wielosesyjnie; blokuje |
| D01 | Denial of Service | Sesje, used_ids, cache retry lub mapy limiterów rosną bez końca | Pamięć i dostępność | 5 | 4 | 20 krytyczne | Twarde limity każdej kolekcji, TTL monotoniczne, cleanup, admission control i 429/503 | #69/#68 | planowane: v1 used_ids bez limitu; blokuje |
| D02 | Denial of Service | Równoległa walidacja pierwszości/RSA nasyca CPU i threadpool | Backend, węzły | 5 | 4 | 20 krytyczne | Rate limit przed walidacją, bounded kolejka/pula C, max workers, CPU quotas | #69 + operator | częściowo: uint32 ogranicza koszt pojedynczego wywołania; blokuje |
| D03 | Denial of Service | Nadmierny polling i odczyt ogromnych odpowiedzi | CPU, sieć, pamięć | 5 | 3 | 15 wysokie | Ograniczone discovery/zdarzenia/body, backoff/jitter, jedna prośba w locie, limit role/IP | #68/#69/#70 | częściowo: UI nie nakłada swojego pollingu, brak limitów serwera; blokuje |
| D04 | Denial of Service | Zawieszenie węzła, utrata odpowiedzi, restart/OOM | Dostępność i sesje | 4 | 3 | 12 wysokie | Timeouts, lease, terminal failed, bounded retry, restart, komunikat o nowej sesji | #68/#69 + operator | częściowo: retry/heartbeat istnieją; blokuje |
| D05 | Denial of Service | Duże/wolne body lub nadmiar połączeń | Proxy i FastAPI | 4 | 4 | 16 wysokie | Body cap 4 KiB także backend, read/connect timeouts, limit połączeń i 413 ErrorResponse | Operator + #69 | częściowo w lokalnym Compose #73; publiczne gate |
| E01 | Elevation of Privilege | Użytkownik używa endpointu węzła lub token jednej roli daje inną rolę | Uprawnienia protokołu | 5 | 4 | 20 krytyczne | Oddzielne routery/tokeny/scopes, proxy deny internal, brak publicznych mutacji protokołu | #69/#68 | planowane; blokuje |
| E02 | Elevation of Privilege | Uszkodzenie pamięci na granicy Python/C lub podmieniona .so | Proces backendu/węzła | 2 | 5 | 10 wysokie | Ścisłe typy/range, argtypes/restype, własność bufora, kontrole ABI, sanitizer, .so read-only z obrazu | Łukasz + QA + operator | częściowo: walidacja i ABI istnieją, runtime hardening #73, gate skanu |
| E03 | Elevation of Privilege | XSS kradnie bearer z sessionStorage i wykonuje akcje właściciela | Capability i sesja | 3 | 4 | 12 wysokie | React escaping, bez innerHTML, CSP self bez unsafe-inline/eval, brak zewnętrznych skryptów, krótki TTL | Szymon #70 + operator | częściowo: React escaping; CSP/proof przed betą; blokuje |
| E04 | Elevation of Privilege | CSRF/CORS pozwala obcej stronie wykonywać operacje | Sesja właściciela | 3 | 4 | 12 wysokie | Brak auth cookies, jawny Bearer, JSON, same-origin CORS, weryfikacja Origin i negatywne testy | #69/#70/#71 | planowane; blokuje |
| E05 | Elevation of Privilege | Błędne proxy wystawia backend/internal, ufa dowolnemu XFF | Role, limity i host | 4 | 5 | 20 krytyczne | Allowlista tras/metod, prywatny listener, firewall, test zewnętrzny portów, zaufane konkretne proxy | Operator + #69 | częściowo lokalny Compose; publiczne gate |
| E06 | Elevation of Privilege | Zależność z CVE lub kontener root/docker.sock daje przejęcie hosta | Host i wszystkie sesje | 3 | 5 | 15 wysokie | Skan CVE/SBOM, non-root, cap_drop, no-new-privileges, brak docker.sock/mount kodu | Operator + QA | częściowo Compose #73; bez wykonanego skanu; blokuje |
| T06 | Tampering | Przyszłe zgłoszenia zawierają HTML/linki/załączniki/webhook SSRF | Moderator, sieć wewnętrzna | 3 | 4 | 12 wysokie | Na start tekst ograniczony do 4 KiB; brak załączników i fetch URL; escaping i auth moderatora | #74 + przyszły właściciel zgłoszeń | planowane; funkcja wyłączona do przeglądu |
| T07 | Tampering | Podmiana wartości DH lub powtórzenie podpisu z obcej sesji | Integralność uwierzytelnionego DH | 4 | 3 | 12 wysokie | Transkrypt wiąże sesję, epoch, rolę, p/g, lokalne A/B i oba klucze. Każdy ACK wymaga zgodności pełnego SHA-256 i podpisu RSA. Completed wymaga obu ACK. | #101–#103 | zaimplementowane w węzłach i koordynatorze, QA procesowe wymagane |
| T08 | Tampering | Mallory lub obca rola publikuje klucz, podpis albo wynik weryfikacji ofiary | Zaufane klucze i wynik protokołu | 3 | 4 | 12 wysokie | Rola wynika z Bearer i przypisania instance/epoch. Dostęp Mallory jest ograniczony do podmiany DH. Retry ma kontrolę konfliktu treści. | #102/#103 | zaimplementowane w koordynatorze, QA procesowe wymagane |
| I08 | Information Disclosure | Prywatny klucz RSA lub zaakceptowany K trafia do widoku/logu po błędzie podpisu | Klucze prywatne i sekret sesji | 3 | 5 | 15 wysokie | Prywatne klucze lokalne. Diagnostyka każdej roli po completed i podwójnym opt-in. Failed czyści diagnostykę i odrzuca jej ponowne zgłoszenie. | #102/#103 | zaimplementowane w węzłach i koordynatorze, QA procesowe wymagane |
| D06 | Denial of Service | Spam, flooding lub boty w systemie zgłoszeń | Poczta, pamięć, koszty | 4 | 3 | 12 wysokie | Rate limit, limity liczby/retencji zgłoszeń, moderacja; nie łączyć z kolejką protokołu DH | #74 + operator | planowane; nie uruchamiać funkcji bez limitów |
| I06 | Information Disclosure | Zgłoszenie zawiera dane osobowe lub podatność opublikowaną publicznie | Prywatność i zgłoszenia bezpieczeństwa | 3 | 4 | 12 wysokie | Jasna polityka zbierania/retencji, poufny kanał, ograniczenie dostępu; bez tokenów i danych sesji w formularzu | #74 + operator | planowane; gate kanału poufnego |
| I07 | Information Disclosure | Ktoś używa 32-bitowych kluczy RADH do realnych danych | Dane poza demonstratorem | 4 | 5 | 20 krytyczne użycie poza przeznaczeniem | Ostrzeżenia w UI/API/docs, brak reklamowania bezpieczeństwa, brak funkcji przechowania prawdziwych danych | PO #74 + Szymon | poza zakresem algorytmów; ostrzeżenia istnieją, utrzymać |

## Zabezpieczenia istniejące a planowane

Istniejące: strict uint32/extra-forbid w modelach, walidacja ctypes przed C,
C bez alokacji i zapisu wyniku po błędzie, kontrolowane statusy i ErrorResponse,
idempotentne identyczne retry w v1, blokada mutacji, lokalne losowanie secrets,
atomowy start Mallory, oddzielna diagnostyka i test-mode lokalnie, walidacja
odpowiedzi transportu, React renderujący tekst, npm lock, CTest i pytest.

Planowane, nie „dostarczone dokumentem”: Owner Bearer i role service tokens,
wielosesyjna izolacja, fencing epoch/instance, TTL/cleanup/admission limits,
pełny rate limiting i kolejki C, TLS produkcyjne, bezpieczne logi operacyjne,
rotacja poświadczeń, CVE/SBOM i testy izolacji. Non-root, prywatna sieć, read-only
oraz proxy w #73 są konfiguracją do lokalnej walidacji; brak uruchomienia kontenerów
nie jest dowodem, że runtime hardening działa na VPS.

## Co blokuje publiczne wdrożenie

S01–S03, T01–T02/T04–T05, R01, I01–I06, D01–D05 i E01–E06 wymagają dowodów
z release gate lub udokumentowanej redukcji ryzyka. Żadna akceptacja nie może
zastąpić podstawowej izolacji/Owner auth/node auth/TLS. T03 i R02 pozostają
w regresji. T06/D06/I06 blokują włączenie systemu zgłoszeń, nie wymagają
implementowania go w #73; poufny kanał zgłaszania podatności jest osobnym gate.

**Kontrolowana Mallory nie jest włamaniem do infrastruktury.** W aplikacji
wie ona, jaką rolę wykonuje, i jest ograniczona do sesji MITM. Demonstracja
pokazuje brak uwierzytelnienia matematycznej wymiany DH między ofiarami;
uprawnienia HTTP muszą nadal uniemożliwiać podszycie się użytkownika pod
proces Mallory. 32-bitowe A/B pozwalają praktycznie odzyskiwać wykładniki:
izolacja aplikacji nie zmienia tego w bezpieczną kryptografię produkcyjną.
Nie wolno używać edukacyjnego RSA do podpisywania tokenów usług lub TLS RADH.

W scenariuszu podpisanym koordynator jest zaufanym źródłem kluczy n/e.
Model demonstracji zakłada poprawność przypisania klucza do roli i wyklucza
przejęcie koordynatora lub poświadczeń usług. Węzły sprawdzają pełny SHA-256,
ponieważ redukcja modulo małe n traci informację i może dać ten sam reprezentant
dla dwóch różnych transkryptów. Uwierzytelnianie HTTP i TLS działają osobno.

## Przegląd i źródła

Model aktualizować przy zmianie auth, routerów, trwałości, roli/transportu,
liczby workerów, zależności i uruchomieniu zgłoszeń. Każde zagrożenie ma właściciela,
dowód redukcji i datę ponownego przeglądu; wynik po testach dopisać w osobnym PR.

- [Microsoft STRIDE](https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-getting-started) — sześć kategorii użytych do przeglądu przepływów i granic.
- [OWASP REST Security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html) — autoryzacja per operacja, TLS i zakaz sekretów w URL.
- [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) — lifecycle tokenów i ryzyko dostępu JavaScript do browser storage.
