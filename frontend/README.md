# RADH – frontend

Interfejs demonstratora RSA i wymiany kluczy Diffiego-Hellmana.
React + TypeScript + Vite.

Frontend nie wykonuje obliczeń kryptograficznych – wysyła dane do backendu
FastAPI i wyświetla jego odpowiedź.

## Interfejs

Aplikacja ma dwie zakładki: **RSA** (generowanie kluczy i szyfrowanie) oraz
**Diffie–Hellman** (wymiana kluczy, także w scenariuszu ataku MITM).
Zmiana zakładki nie usuwa wpisanych danych ani wyników.

Interfejs działa na komputerach, tabletach i telefonach (sprawdzony przy
szerokościach 360, 390, 768 i 1440 px):

- na wąskim ekranie panele układają się jeden pod drugim, formularz DH stoi
  nad przebiegiem sesji, a po starcie strona przewija się do wyniku;
- dziennik zdarzeń pokazuje każde zdarzenie jako kartę, a porównanie
  scenariuszy zostaje zwartą tabelą – bez przewijania w poziomie;
- przyciski, pola, zakładki i nagłówki zwijanych sekcji mają co najmniej
  44 px wysokości, wygodne do obsługi palcem;
- wszystko da się obsłużyć klawiaturą (zakładki strzałkami ←/→).

![Zakładka RSA: wygenerowana para kluczy i szyfrogram](docs/screenshots/rsa.png)

![Zakładka Diffie–Hellman: zakończona zwykła wymiana](docs/screenshots/dh-normal.png)

![Zakładka Diffie–Hellman: atak MITM i porównanie scenariuszy](docs/screenshots/dh-mitm.png)

Wspólny wygląd obu widoków:

- `src/index.css` – zmienne stylu: kolory (w tym uczestników i rodzajów danych),
  czcionki, rozmiary tekstu, odstępy, zaokrąglenia; jasny i ciemny motyw
  według ustawień systemu.
- `src/ui.tsx` – wspólne przyciski, plakietki („tajne”, „jawne”, stany)
  i komunikaty błędów oraz ostrzeżeń.
- Wersja w stopce pochodzi z pola `version` w `package.json`.

## Wymagania

- Node.js w wersji 20.19+ lub 22.12+ (razem z nim instaluje się `npm`).
  Sprawdzenie: `node -v`.

## Instalacja zależności

Z głównego katalogu:

```bash
cd frontend
npm install
```

Wystarczy raz po sklonowaniu repozytorium i ponownie, gdy zmieni się
`package.json`. Katalog `node_modules/` nie trafia do repozytorium.

## Uruchomienie w trybie deweloperskim

```bash
npm run dev
```

Aplikacja będzie dostępna pod adresem http://localhost:5173/.
Zmiany w plikach w `src/` widać od razu po zapisaniu.

### Połączenie z backendem

W trybie deweloperskim Vite przekierowuje żądania `/api/...` do backendu
pod adresem `http://127.0.0.1:8000` (ustawienie `server.proxy` w
`vite.config.ts`). Dzięki temu nie trzeba konfigurować CORS.

Aby szyfrowanie działało, backend FastAPI musi być uruchomiony na porcie 8000
– instrukcja w [`backend/README.md`](../backend/README.md). Frontend i backend
uruchamia się w dwóch osobnych terminalach.

Bez backendu interfejs się uruchomi, ale po kliknięciu „Szyfruj” pokaże
komunikat o braku połączenia z backendem.

Szybkie sprawdzenie: dla `m = 65`, `e = 17`, `n = 3233` interfejs powinien
pokazać szyfrogram `2790`.


### Generowanie kluczy RSA

Panel „Generowanie kluczy” wyznacza parę kluczy z podanych `p`, `q` i `e`.
Wszystkie wartości (`n`, `φ(n)`, `d`) liczy CryptoCore przez endpoint
`POST /api/v1/rsa/demo/keygen` – kontrakt i kody błędów w
[`backend/README.md`](../backend/README.md).

- Pierwszość `p` i `q`, zakres modułu oraz warunek `NWD(e, φ(n)) = 1` sprawdza
  backend; frontend pokazuje jego komunikat.
- Przycisk „Użyj klucza publicznego” wpisuje `e` i `n` do formularza szyfrowania.
- Po zmianie biblioteki C trzeba ją przebudować i zrestartować backend.
  Bez tego generowanie zwróci „Nie znaleziono zasobu” (stary backend) albo
  błąd niedostępnego CryptoCore (stara biblioteka).

Szybkie sprawdzenie: dla `p = 61`, `q = 53`, `e = 17` interfejs powinien pokazać
`n = 3233`, `φ(n) = 3120`, `d = 2753`, a po użyciu klucza publicznego
wiadomość `m = 65` zaszyfruje się do `2790`.

### Zakładka Diffie–Hellman

Zakładka DH pokazuje sesję wymiany kluczy między dwoma osobnymi procesami
węzłów, Alice i Bobem, koordynowaną przez backend. Oprócz backendu trzeba
więc uruchomić oba węzły, każdy w osobnym terminalu – instrukcja
w [`backend/DH_SESSIONS.md`](../backend/DH_SESSIONS.md).

- Gdy któryś węzeł nie działa, przycisk „Rozpocznij sesję” jest nieaktywny,
  a pod nim widać, który proces trzeba uruchomić.
- Wspólny sekret K widać tylko wtedy, gdy węzły uruchomiono z opcją
  `--allow-diagnostics`. Bez niej panel pokazuje „K – obliczony, zna go tylko
  proces …” – to nie jest błąd.

Szybkie sprawdzenie: dla `p = 23`, `g = 5` i węzłów w trybie testowym
z sekretami 6 i 15 interfejs powinien pokazać `A = 8`, `B = 19`,
a z diagnostyką `K = 2` po obu stronach.

#### Scenariusz „Atak MITM”

Scenariusz ataku wymaga trzeciego procesu – Mallory – uruchomionego obok
Alice i Boba, w osobnym terminalu. Instrukcja w
[`backend/MITM_SESSIONS.md`](../backend/MITM_SESSIONS.md).

- Bez działającego procesu Mallory przycisk „Rozpocznij sesję” jest nieaktywny
  w tym scenariuszu; zwykła wymiana działa bez niej.
- Sekrety Mallory (K<sub>MA</sub>, K<sub>MB</sub>) widać tylko wtedy, gdy jej proces
  też uruchomiono z `--allow-diagnostics`.
- Tabela „Porównanie scenariuszy” pokazuje ostatnią zakończoną sesję każdego
  scenariusza, więc oba trzeba uruchomić po kolei – koordynator obsługuje
  jedną sesję naraz.

Szybkie sprawdzenie: z węzłami jak wyżej i Mallory w trybie testowym
z sekretami 7 i 11 interfejs powinien pokazać, że Alice otrzymała `X = 17`,
a Bob `Y = 22`, oraz `K_A = K_MA = 12`, `K_B = K_MB = 22`.

## Kompilacja produkcyjna

```bash
npm run build
```

Polecenie sprawdza typy TypeScript i buduje aplikację do katalogu `dist/`.
Podgląd zbudowanej wersji: `npm run preview`.

## Pozostałe polecenia

- `npm run lint` – sprawdzenie kodu linterem (oxlint).
## Wielosesyjny klient DH (#70)

Zakładka DH korzysta z koordynatora API v2 z #69 / PR #85 oraz procesów
wielosesyjnych z #68 / PR #82. Uruchomienie wszystkich komponentów wymaga
wspólnej migracji. Transport i tokeny ról opisuje `backend/MULTI_SESSION.md`.

Klient pobiera epoch z `GET /api/v2/dh/nodes`, tworzy sesję z
`Idempotency-Key` i `X-Backend-Epoch`, a następnie zachowuje
`session_id`, token właściciela oraz epoch w `sessionStorage` danej karty.
Każdy odczyt i zapis własnej sesji używa Bearer. Odświeżenie strony odzyskuje
wyłącznie tę sesję. Reset usuwa własny rekord przez DELETE i pozwala świadomie
porzucić niepotwierdzoną próbę tworzenia.

Próba create zapisuje klucz i parametry przed wysłaniem. Kolejne świadome
kliknięcie może powtórzyć ją przez maksymalnie 60 sekund z tym samym kluczem.
Zmiana parametrów, epoch lub przekroczenie czasu wymaga Reset.
Błąd startu zachowuje poświadczenie, umożliwiając ponowienie albo usunięcie.

Żądania mają timeout i AbortController. Reset/nowa operacja zwiększa numer
żądania i przerywa poprzednią operację. Polling stanu i historii jest sekwencyjny,
co 2 sekundy. Przejściowe błędy respektują Retry-After, z ograniczonym
30-sekundowym oknem ponowień od utraty kontaktu. Obcy ID nie może dostać
poświadczenia zapisanej sesji. Spóźniony błąd starego ID nie usuwa nowszego tokenu.

Diagnostyka K wymaga jawnego zaznaczenia pola przed utworzeniem sesji oraz
zgody węzła. Expired czyści K z widoku i zatrzymuje polling, zachowując możliwość
DELETE w czasie retencji. Odpowiedź 404/410 lub zmiana epoch usuwa stare
poświadczenie. Własne ukończone scenariusze nadal można porównywać w pamięci karty.

Testy jednostkowe klienta API i poświadczeń uruchamia polecenie:

```sh
npm test -- tests/dhApi.unit.test.tsx
```

Testy używają atrap fetch i storage. Weryfikacja dwóch rzeczywistych przeglądarek
i procesów z backendem należy do QA #71. Build i lint uruchamia się standardowymi
poleceniami `npm run build` i `npm run lint`.
