# Release gate — RADH Public Beta

**Status na 2026-11-17: NO-GO dla publikacji publicznej.**
Lokalny Compose v1 nie spełnia auth, izolacji ani TLS bety.
Dokument jest mierzalnym planem odbioru, nie listą zabezpieczeń już wdrożonych.
Powiązania: #72/#73, [kontrakt](../architecture/multi-session.md),
[ryzyka](threat-model.md), [wdrożenie](../architecture/deployment.md).

Każde kryterium wymaga dowodu (SHA kodu, wynik/artefakt testu, konfiguracja,
data i osoba). Checkbox zaznacza reviewer po wykonaniu, nie autor na podstawie
samego projektu. Staging ma te same obrazy i domyślne limity co beta; osobna,
izolowana próba 100 retry w G05 jawnie podnosi wyłącznie testowe limity create
(opis poniżej), nie konfigurację publikacji. Testy wyłącznie na
lokalnym lub jawnie autoryzowanym stagingu, bez atakowania publicznych usług.

## Kryteria obowiązkowe — bez wyjątków dla podstawowych kontroli

| Gate | Mierzalny warunek odbioru | Dowód | Właściciel / zależność |
| --- | --- | --- | --- |
| G01 | 20 równoczesnych sesji (10 normal, 10 MITM), trzy rzeczywiste procesy; każdy rekord, wiadomość, log i K należą tylko do właściwego ID | Raport #71 z niezależnymi wynikami C i różnymi PID; brak procesu per sesja | #68–71 |
| G02 | Pełna macierz token właściciela A/B × odczyt/start/cancel/delete/events/diagnostics; cudzy token zawsze 404 i zero mutacji | Automatyczne testy BOLA/IDOR na własnym stagingu | #69/#71 |
| G03 | Brak/zły format tokenu →401; poprawny token: GET istniejącej aktywnej/zakończonej →200, expired w retencji →200 bez K, tombstone →410 SESSION_EXPIRED, brak rekordu/tombstone →404 SESSION_NOT_FOUND. Błędny token poprawnego formatu zawsze →404. Mutacje expired →409, DELETE właściciela →204; token poza URL/logami/SessionView | Test zegara: aktywna → expired → tombstone → brak; odczyty, mutacje i DELETE, macierz cudzych tokenów oraz audyt logów | #69/#70/#71 |
| G04 | Użytkownik nie publikuje/ACK/forward/heartbeat/K; token każdej roli nie wykonuje operacji pozostałych ról; publiczny proxy blokuje internal i legacy sesje v1 | Macierz metod i credential types, test portów ze stagingowego klienta | #69/#71 + operator |
| G05 | Równoległy start/retry/ACK/forward/diagnostics nie dubluje zdarzeń; zmiana treści daje 409; 100 retry tworzenia w 60 s przy jawnie podniesionych limitach testowych daje jedno ID/token; zaakceptowane retry przy limitach domyślnych również nie tworzy nowego ID/token | Testy wyścigów i utraty odpowiedzi; osobno 100 retry w konfiguracji testowej oraz integracja domyślnych limitów i 429 (G09) | #68/#69/#71 |
| G06 | Stara odpowiedź po zmianie ID, anulowaniu lub epoch nie zmienia UI/agenta; nie odtwarza sekretów ukończonej sesji; expired 200 usuwa K i zatrzymuje polling, zachowując ID/token do DELETE; 404/410 usuwa token | Testy opóźnionych odpowiedzi i AbortController | #68/#70/#71 |
| G07 | Testowe TTL z krótkimi czasami: po cleanupie brak agentów i K; kolekcje nigdy nie przekraczają 128 sesji/256 tombstone/128 create retry/4096 bucketów; old used_ids nie istnieje | Testy zegara monotonicznego i 1000 sekwencyjnych create/delete | #68/#69/#71 |
| G08 | 33. równoległy start →503 RUNNING_CAPACITY, 129. rekord →503 SESSION_CAPACITY; pełna kolejka C →503 CRYPTO_BUSY; pozostałe sesje działają | Raport limitów i sprawiedliwości; bez wymuszania OOM | #69/#71 |
| G09 | Limity IP/token/roli działają przed kosztowną walidacją; create 6/min/IP, burst 2 obejmuje każde retry przed cache i zwraca 429 + Retry-After; zły XFF nie omija limitera; body >4 KiB →413 bez C | Test proxy i backendu bezpośrednio w sieci stagingowej | #69/#71 + operator |
| G10 | Wygasły heartbeat, restart roli, duplikat procesu i restart backendu dają przewidywalne failed/404 i nowy epoch; brak cross-session writes | Testy rzeczywistych restartów i fencing | #68/#69/#71 |
| G11 | Wyłącznie 443 i 80 redirect/ACME dostępne publicznie; 8000/internal/metryki/docker.sock niedostępne; SSH ograniczone | Zatwierdzona konfiguracja firewall i proxy + lokalny test zewnętrznego interfejsu stagingu | operator |
| G12 | Poprawny certyfikat i hostname, TLS 1.2/1.3, redirect, HSTS po odbiorze; odnowienie sprawdzone; alert <14 dni | Raport konfiguracji TLS i próbnego odnowienia | operator, PBI wdrożeniowe |
| G13 | Unikalne 256-bitowe tokeny ról w oddzielnych plikach, brak w Git/build/dist/env dump/logach; odwołanie tokenu z kontrolowanym restartem w Sprincie A; przed publikacją także rotacja bez przestoju z ≤60 s grace odcina stary token | Skan sekretów, próba odwołania i rotacji wszystkich ról | #68/#69 (auth/odwołanie); operator + follow-up (rotacja bez przestoju) |
| G14 | Brak wildcard credentialed CORS; obcy Origin odrzucany; brak auth cookies; CSP bez unsafe-inline/eval, frame-ancestors none, no-store API, no-referrer | Test negatywny CSRF/CORS i nagłówków także przy 4xx/5xx | #69/#70/#71 + operator |
| G15 | Wszystkie wartości z API renderowane jako tekst; próby HTML/JS nie wykonują skryptu; tokeny tylko per karta; expired 200 usuwa K, zachowuje możliwość DELETE, token kasowany po DELETE/404/410 lub porzuceniu widoku | Testy UI na lokalnym buildzie produkcyjnym | #70/#71 |
| G16 | Runtime non-root, cap_drop ALL, no-new-privileges, read-only, brak mountu kodu/docker.sock; limity CPU/RAM/PID zweryfikowane w inspect | Raport runtime Compose na rzeczywistym Dockerze | operator, #73 konfiguracja |
| G17 | Ścisłe typy i zakresy Python/C, rozmiar/statusy ABI i zapis po sukcesie; sanitizer i cała regresja RSA/DH/keygen/MITM przechodzą | CTest + pytest + lint/build z konkretnego SHA | właściciele komponentów + QA |
| G18 | Metryki i alarmy z deployment.md są odbierane; próba alarmu rola offline i 5xx dochodzi do operatora; brak identyfikatorów/tokenów jako etykiet metryk | Kontrolowana próba awarii na stagingu, potwierdzenie alarmu | operator, osobne PBI operacyjne |
| G19 | Logi nie zawierają tokenów, Idempotency-Key, p/q/e z requestów, wykładników DH ani K; obejmuje proxy error log i APM, retencja ≤7 dni | Canary testy wycieku i przegląd rotacji/uprawnień | #69/#71 + operator |
| G20 | Obrazy po digest, skan CVE/SBOM, locki i audyt artefaktów; zero nierozpatrzonych podatności krytycznych/wysokich osiągalnych w runtime | Wynik skanera z datą i triage, zapis digestów i SHA | QA + operator, follow-up supply chain |
| G21 | Kontrolowany test 20 sesji/15 min i 32 sesji/5 min: 0 błędów izolacji, 0 OOM/restartów, p95 poprawnych żądań <2 s; dozwolone limity zwracają 429/503, nie 500 | Raport na VPS 2 vCPU/4 GiB z konfiguracją limitów | #71; wartości początkowe do walidacji |
| G22 | Po obciążeniu i upływie TTL mapy wracają do 0 żywych sesji/agentów, RSS stabilizuje się <80% limitu; 1000 create/delete nie daje liniowego wzrostu pamięci | Wykres RSS/liczności i kontrola reguł retencji | #71 + operator |
| G23 | Aktualizacja i rollback pełnego zestawu przećwiczone; znany dobry zestaw obrazów zachowany, użytkownik widzi utratę ulotnej sesji | Protokół stagingu z normal/MITM/RSA po rollback | operator |
| G24 | Poufny kanał zgłoszeń działa, jest opisany publicznie, ma właściciela i potwierdzony odbiór testowego zgłoszenia | Adres/URL i data próbnego kontaktu bez ujawniania treści zgłoszenia | #74 + operator |
| G25 | Ostrzeżenia „edukacyjne, 32-bitowe, nie do rzeczywistych danych”, zasady bety i retencji widoczne; brak obietnicy bezpieczeństwa RSA/DH | Przegląd UI/docs i akceptacja PO | #74 + #70 |

G05: 100 ponowień tego samego żądania i klucza w <60 s uruchomić w izolowanym
środowisku z limiterem create np. 6000/min/IP, burst 128, także na testowym proxy.
Nie zmieniać 60 s cache; zapisać efektywną konfigurację w raporcie. Wszystkie
zaakceptowane odpowiedzi mają to samo ID/token, liczba utworzonych sesji wynosi 1.
Osobna integracja G09 używa domyślnych **6/min/IP, burst 2**: również trafienia
w cache podlegają limitowaniu, nadmiar daje 429 + Retry-After, a zaakceptowane
retry zachowuje ID/token. Idempotency-Key nigdy nie omija limitera. Testować
odnowienie budżetu i granicę 60 s kontrolowanym zegarem; nie osłabiać konfiguracji
produkcyjnej i nie traktować 429 jako niepowodzenia idempotencji.

G20: ewentualne wyjątki dotyczą tylko podatności z udokumentowanym brakiem
osiągalności albo jawną redukcją ryzyka, terminem i właścicielem. Nie służą do
zaakceptowania braku auth/izolacji/TLS. Macierz STRIDE aktualizowana po dowodach.
Próby G01/G21 uruchomić z co najmniej 5 kontrolowanych adresów klientów
stagingu, aby odtworzyć wielu użytkowników bez przekroczenia limitu 8 sesji/IP;
osobno sprawdzić odmowę dla jednego IP/NAT. Nie omijać limitów fałszywym XFF.
Wyniki progów obciążenia mogą wymagać ograniczenia MAX_RUNNING_SESSIONS; zmianę
zapisać w kontrakcie i ponowić próby, nie wyłączać asercji.

## Procedura incydentu — minimum przed startem bety

1. Wyznaczyć dyżurnego operatora i zastępcę oraz prywatny kanał kontaktu (#74).
   W #73 nie skonfigurowano żadnego prawdziwego adresu ani powiadomień.
2. Operator potwierdza alarm, blokuje tworzenie nowych sesji lub zamyka ingress
   w ciągu 30 minut od otrzymania alarmu podczas ogłoszonych godzin obsługi bety.
   Godziny i brak SLA 24/7 opisać przed publikacją.
3. Zabezpiecza tylko zredagowane logi i metadane wersji (bez dumpu sekretów),
   ustala zasięg; nie prosi użytkowników o tokeny lub prawdziwe klucze.
4. Podejrzenie wycieku tokenu roli → odwołanie i rotacja, zakończenie dotkniętych
   sesji, sprawdzenie innych ról; podejrzenie hosta → izolacja hosta i odbudowa
   z zaufanego obrazu. Restart nie przywraca utraconych sesji.
5. Naprawa lub rollback, testy negatywne, ponowny gate właściwych zagrożeń.
   Komunikat o wpływie na użytkowników uzgadnia PO; bez ujawniania exploita i danych.
6. Post-mortem z przyczyną, działaniami i właścicielami do 5 dni roboczych.
   Operator i PO ustalają obowiązki dotyczące ewentualnych danych osobowych.

Poufny kanał: operator może włączyć prywatne zgłaszanie podatności na GitHubie
lub opublikować dedykowaną skrzynkę; **dopóki nie ma sprawdzonego kanału, G24
pozostaje otwarte**. Zwykłe publiczne issue nie jest kanałem dla tokenów, danych
użytkowników i szczegółów niezałatanej podatności. Pierwsza beta nie potrzebuje
własnego systemu ticketowego. Jeśli powstanie, T06/D06/I06 wymagają osobnego
projektu: brak załączników/fetch URL, limity, escaping, moderacja i retencja.

## Odpowiedzialność za otwarte prace

- **Sprint A, #68–70:** implementacja izolacji, auth sesji i ról, fencing,
  rejestrów z limitami, TTL/cleanup, idempotencji i klientów v2. Nie sama akceptacja
  dokumentu; żadna z tych podstawowych kontroli nie jest odroczona.
- #71: testy izolacji, wyścigów, limitów i restartów. #73 nie przejmuje ich implementacji.
- #74: zasady bety, zakres dostępności, prywatność/retencja i kanał poufny.
- Osobne PBI operacyjne przed publikacją: domena/TLS/monitoring, secret provisioning,
  skan i digesty, uruchomienie na VPS, przyjęcie runbooka oraz rollback.
  Rotacja bez przerywania usług z G13 może być wykonana po Sprincie A, ale
  nadal blokuje publikację do czasu odbioru. W Sprincie A wymagane jest auth
  i skuteczne odwołanie tokenów z kontrolowanym zatrzymaniem/restartem.
- Odbiór G21/G22 na VPS i pełnego gate wymaga udziału operatora po gotowości
  implementacji. Przyszłe HA, trwałość i centralne dashboardy są poza pierwszą
  betą; podstawowy monitoring i alarmy G18 pozostają obowiązkowe.
- Właściciel #72 zatwierdza GO na podstawie kompletu dowodów; brak dowodu = NO-GO.

Bieżące lokalne wyniki #73 są w [verification.md](../architecture/verification.md).
Nawet zaliczenie smoke v1 nie spełnia G01–G15 dla wielosesyjnej publicznej bety.
