# RADH – frontend

Interfejs demonstratora RSA i wymiany kluczy Diffiego-Hellmana.
React + TypeScript + Vite.

Frontend nie wykonuje obliczeń kryptograficznych – wysyła dane do backendu
FastAPI i wyświetla jego odpowiedź.

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

## Kompilacja produkcyjna

```bash
npm run build
```

Polecenie sprawdza typy TypeScript i buduje aplikację do katalogu `dist/`.
Podgląd zbudowanej wersji: `npm run preview`.

## Pozostałe polecenia

- `npm run lint` – sprawdzenie kodu linterem (oxlint).