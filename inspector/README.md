# RADH Inspector

RADH Inspector to opcjonalna aplikacja desktopowa do obserwowania backendu RADH podczas pracy z istniejącym interfejsem WWW. Pokazuje wykonane operacje i zmiany stanu sesji, a także pozwala powiązać je z żądaniami HTTP. Interfejs WWW i biblioteka C działają tak samo bez Inspectora.

## Budowanie na Linuksie

Potrzebne są CMake 3.23+, kompilator z obsługą C++23, Git, nagłówki libcurl 7.85+, biblioteki deweloperskie OpenGL/X11 i działająca sesja graficzna X11 lub XWayland. Aplikacja korzysta z systemowych fontów DejaVu Sans i DejaVu Sans Mono. Przykładowy zestaw pakietów dla Ubuntu 24.04:

~~~sh
sudo apt-get install build-essential cmake git libcurl4-openssl-dev \
  libgl1-mesa-dev libx11-dev libxcursor-dev libxi-dev libxinerama-dev libxrandr-dev fonts-dejavu-core
cmake -S inspector -B build/inspector -DCMAKE_BUILD_TYPE=Release
cmake --build build/inspector -j
ctest --test-dir build/inspector --output-on-failure
~~~

CMake pobiera CPPFX v0.33.2 (commit `38cf694525cfa1ae0b997d94e84a98e1d997dceb`). CPPFX używa raylib 6.0 i pobiera ją, jeśli nie znajdzie zgodnego pakietu. CMake korzysta z zainstalowanego nlohmann/json 3.11+ lub pobiera 3.12.0. Testy modelu i lokalnego gniazda TCP działają bez okna. Sam model i testy można zbudować z `-DRADH_INSPECTOR_GUI=OFF`.

## Włączanie telemetrii

### Backend uruchomiony bez Dockera

Zbuduj CryptoCore i zainstaluj zależności backendu według [głównej instrukcji RADH](../README.md). Zastąp zwykłe uruchomienie backendu poniższymi poleceniami, wykonywanymi z głównego katalogu repozytorium. Przykład zakłada istniejące środowisko `backend/.venv`.

~~~sh
export RADH_DEBUG_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
RADH_DEBUG_ENABLED=true backend/.venv/bin/python -m uvicorn app.main:app \
  --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log &
radh_backend_pid=$!
until curl --fail --silent --output /dev/null http://127.0.0.1:8000/openapi.json; do
  kill -0 "$radh_backend_pid" || break
  sleep 0.2
done
./build/inspector/radh-inspector
kill "$radh_backend_pid"
unset RADH_DEBUG_TOKEN
~~~

Pierwsze żądanie HTTP do backendu uruchamia osobny nasłuch diagnostyczny. Dzięki temu główny serwer ma pierwszeństwo, nawet przy omyłkowym użyciu tego samego portu. Przykład wykorzystuje domyślny adres `http://127.0.0.1:8001`. Inspector uruchomiony w tym samym terminalu używa tokenu z otoczenia i łączy się automatycznie. W innym terminalu uruchom plik wykonywalny, otwórz **Ustawienia**, wklej token w maskowanym polu i kliknij **Połącz**. Opcjonalnie `RADH_INSPECTOR_URL` ustawia początkowy adres Inspectora, a `RADH_DEBUG_PORT` zmienia port nasłuchu natywnego backendu. Użyj dwóch różnych portów dla WWW i SSE.

Frontend uruchom standardowo na porcie 5173. W zakładce RSA wygeneruj klucz dla p=61, q=53, e=17 lub uruchom szyfrowanie tekstu. W Inspectorze wybierz **RSA** albo **Monitor API**, a następnie kliknij zdarzenie, aby przejrzeć skorelowane etapy. Przy uruchomionych węzłach DH użyj zwykłego formularza WWW i otwórz **Diffie–Hellman**.

### Docker Compose

Po [standardowej inicjalizacji wdrożenia i poświadczeń węzłów](../README.md) w osobnym terminalu wykonaj:

~~~sh
export RADH_DEBUG_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
sudo --preserve-env=RADH_DEBUG_TOKEN docker compose -f compose.yaml -f compose.inspector.yaml up -d --build --wait
./build/inspector/radh-inspector
~~~

SSE jest publikowane na hoście pod `127.0.0.1:8001`. Opcjonalne `RADH_INSPECTOR_HOST_PORT` zmienia port hosta. Ustaw wówczas ten sam port w adresie Inspectora. Backend zachowuje wewnętrzną sieć `services` i dołącza do osobnej sieci `inspector`, ponieważ Docker pomija publikację portów kontenerów podłączonych wyłącznie do sieci `internal`. Jawne `RADH_DEBUG_BIND=0.0.0.0` pozwala przekazać ruch do portu 8001 w kontenerze. Interfejs WWW nadal używa portu z podstawowego Compose. Do wyłączenia telemetrii przywróć wdrożenie podstawowe i usuń token z otoczenia:

~~~sh
sudo docker compose up -d --wait
unset RADH_DEBUG_TOKEN
~~~

## Widoki

| Widok | Dane |
| --- | --- |
| Przegląd | Stan połączenia, żądania, zakończenia operacji i błędy odebrane po wybraniu **Połącz**, sesje z bieżącej historii i ostatnia aktywność |
| Dziennik | Przewijanie, filtr poziomu, wyszukiwanie, wstrzymanie widoku, automatyczne przewijanie, czyszczenie historii i szczegóły |
| Monitor API | Metoda, szablon trasy, status, czas i powiązane zdarzenia dla identyfikatora żądania |
| RSA | Generowanie kluczy, szyfrowanie, deszyfrowanie, parametry publiczne oraz podsumowanie wywołań ABI dla tekstu |
| Diffie–Hellman | Sesje v1 i v2, zmiany stanu, jawne parametry, przesłanie i przekazanie wartości, zgłoszenie obliczenia sekretu przez węzeł oraz jednorazowe demo DH |
| Ślad kryptograficzny | Zarejestrowane rozpoczęcia i wyniki operacji w Pythonie oraz rzeczywiste wywołania ABI C |
| Wydajność | Zliczenie, minimum, maksimum, średnia i wykres ostatnich 240 dostępnych próbek na zakres czasu |
| System | Adres, stan, wersje, moment uruchomienia backendu, zajętość buforów, straty i odrzucone ramki |

Zatrzymanie dziennika zamraża kopię lokalnego widoku. Odbiór z sieci trwa dalej. Po wznowieniu wraca bieżąca historia. Kółko przewija tabele i szczegóły, a przycisk automatycznego przewijania wraca do najnowszych wpisów. Czyszczenie usuwa lokalną historię. Jawne połączenie rozpoczyna nową obserwację i zeruje jej liczniki.

## Transport i schemat

Główny proces FastAPI publikuje zdarzenia z middleware HTTP, nakładek Pythona na CryptoCore i istniejącego dziennika koordynatora DH. Oddzielny nasłuch tego samego procesu obsługuje `GET /api/v1/debug/events` z nagłówkami `Accept: text/event-stream` i `Authorization: Bearer …`. Klient libcurl odbiera ramki na osobnym wątku. Główny wątek opróżnia kolejkę i obsługuje okno CPPFX/raylib.

Każda ramka `data:` zawiera obiekt JSON w UTF-8, np.:

~~~json
{
  "schema_version": 1,
  "event_id": 148,
  "timestamp": "2026-11-26T12:32:04.130Z",
  "level": "DEBUG",
  "source": "crypto.rsa",
  "event": "rsa.encrypt.completed",
  "request_id": "c2fa539993d64efaa6b03c1cd387de72",
  "duration_ns": 12400,
  "data": {"scope": "python", "modulus": "3233", "public_exponent": "17"}
}
~~~

- `event_id` rośnie dla zdarzeń w danym procesie. Wartość 0 oznacza komunikat sterujący. `timestamp` jest w UTC, a `request_id` to losowy identyfikator nadany przez backend lub `null` dla zdarzeń niezależnych od HTTP.
- `data` zawiera jawnie dopuszczone pola zależnie od zdarzenia. Szablony tras mają postać np. `/api/v2/dh/sessions/{session_id}/start`. Żądania odrzucone przed routerem i nieznane trasy mogą mieć ogólną etykietę `/api/*` lub `/internal/*`.
- Publiczne liczby kryptograficzne są zapisane jako dziesiętne łańcuchy. `session` to pseudonim sesji ważny tylko dla życia procesu backendu. Identyfikatory w SSE różnią się od publicznych identyfikatorów API.
- `duration_ns` jest czasem monotonicznym w nanosekundach lub `null`. `http` obejmuje obsługę w middleware i przekazanie odpowiedzi ASGI. `python` mierzy nakładkę wraz z walidacją i wywołaniami C. `ffi` mierzy wywołanie funkcji przez ctypes wraz z przejściem granicy ABI. `ffi_sum` to suma tych pomiarów dla wielobajtowej operacji tekstowej RSA. Pomiar czasu po stronie klienta sieciowego i przeglądarki jest poza tymi zakresami.
- Zdarzenia obejmują `system.started`, `http.request.completed`, `http.error`, etapy `rsa.*` i `dh.exchange.*`, wyniki symboli `radh_*` z `return_status` oraz m.in. `dh.session.created`, `dh.public.value` i `dh.secret.reported`. Zgłoszenie sekretu potwierdza przyjęcie raportu węzła, jeśli dana sesja ma włączone istniejące raportowanie.
- Backend utrzymuje 1024 zdarzenia w pamięci i obsługuje do 8 obserwatorów. Nowe połączenie zaczyna od bieżącej pozycji w buforze. Co ok. 5 s serwer wysyła heartbeat i `telemetry.status`. Do wznowienia służy identyfikator SSE `instancja:pozycja` w nagłówku `Last-Event-ID`. Wyparte zdarzenia zgłasza `telemetry.gap`, a zmienioną instancję lub niepoprawną pozycję sygnalizuje `telemetry.reset`. Inspector przechowuje kolejkę 1024 zdarzeń i historię 3000 wpisów.

## Bezpieczeństwo i ograniczenia

- Telemetria domyślnie jest wyłączona. Do jej uruchomienia potrzebne są `RADH_DEBUG_ENABLED=true` i odrębny 43-znakowy token base64url. Token można wygenerować poleceniem z instrukcji. Ustawienia Inspectora i token pozostają w pamięci procesu. Autoryzacja używa stałoczasowego porównania. Nagłówki proxy i CORS nie uczestniczą w decyzji o dostępie.
- Osobny nasłuch przyjmuje domyślnie połączenia z IPv4 loopback. Publiczny Nginx i proxy Vite kierują ruch do portu głównego backendu, gdzie trasa SSE jest niedostępna. Tryb Compose publikuje port diagnostyczny na loopbackie hosta i wymaga autoryzacji również dla połączeń wewnątrz Dockera. Używaj go w środowisku deweloperskim. Polecenie `docker compose config --quiet` sprawdza konfigurację bez wypisywania poświadczeń.
- Inspector przesyła token wyłącznie w nagłówku HTTP. Akceptuje HTTP dla adresu loopback oraz HTTPS z weryfikacją certyfikatu. Wyłącza przekierowania i pośredników z konfiguracji libcurl. Backend Inspectora udostępnia lokalny HTTP. Jeżeli potrzebny jest zdalny dostęp deweloperski, można zestawić tunel SSH do loopbacka.
- Zdarzenia obejmują metadane i parametry publiczne. Klucze prywatne, czynniki RSA, sekrety DH, szyfrogramy, tekst, treści HTTP i poświadczenia są wyłączone z telemetrii. Osobny tryb demonstracyjny z sekretami, zapis do pliku, pomiary wewnątrz oddzielnych procesów węzłów i stany wewnętrzne algorytmów są poza zakresem. Jeden proces backendu obsługuje jeden strumień diagnostyczny.
- Debugowanie obejmuje ruch od chwili połączenia oraz dostępny zakres wznowienia. Nie ma automatycznej rekonstrukcji wcześniej utworzonych sesji. Windows nie był weryfikowany.

## Rozwiązywanie problemów

- **Odmowa połączenia**. Sprawdź port Inspectora i wykonaj pierwsze zwykłe żądanie HTTP do backendu. Zły token startowy lub zajęty port zostawi ostrzeżenie w zwykłym logu backendu i nie przerwie jego pracy. Przy utracie połączenia Inspector ponawia je co 1–16 s.
- **HTTP 401**. Wklej pełny token z procesu backendu. **HTTP 404** zwykle oznacza podanie portu głównej aplikacji WWW lub backendu.
- **Połączenie jest aktywne, a lista pusta**. Wykonaj nową operację w aplikacji WWW. Sprawdź wyszukiwanie, filtr poziomu i wstrzymanie dziennika.
- **Licznik utraconych zdarzeń rośnie**. Bufor backendu lub kolejka Inspectora wyparły wpisy. Widok **System** pokazuje osobne liczniki, odrzucone ramki i wyparte pozycje historii.
- **Brak czcionki o stałej szerokości lub polskich znaków**. Zainstaluj pakiet DejaVu Sans i DejaVu Sans Mono. Przy braku czcionek aplikacja użyje czcionki raylib.

## Biblioteki

Część graficzna korzysta z [CPPFX](https://github.com/OryginalnaNazwa/CPPFX/tree/v0.33.2) Szymona Maćkowiaka i [raylib 6.0](https://github.com/raysan5/raylib/tree/6.0), udostępnianych na licencji zlib. Kod źródłowy i noty licencyjne pozostają w pobranych zależnościach. Transport korzysta z [libcurl](https://curl.se/libcurl/) (licencja curl), a dekodowanie z [nlohmann/json](https://github.com/nlohmann/json) (MIT).

