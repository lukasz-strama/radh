# RADH – frontend

Interfejs demonstratora RSA i wymiany kluczy Diffiego-Hellmana.
React + TypeScript + Vite.

Frontend nie wykonuje obliczeń kryptograficznych – wysyła dane do backendu
FastAPI i wyświetla jego odpowiedź.

## Wymagania

- Node.js w wersji 20.19+ lub 22.12+ (razem z nim instaluje się `npm`).
  Sprawdzenie: `node -v`.

## Instalacja zależności

W katalogu `frontend/`:

```bash
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
pod adresem `http://localhost:8000` (ustawienie `server.proxy` w
`vite.config.ts`). Dzięki temu nie trzeba konfigurować CORS.

Aby szyfrowanie działało, backend FastAPI musi być uruchomiony na porcie 8000.
Bez niego interfejs się uruchomi, ale po kliknięciu „Szyfruj” pokaże komunikat
o braku połączenia z backendem.

## Kompilacja produkcyjna

```bash
npm run build
```

Polecenie sprawdza typy TypeScript i buduje aplikację do katalogu `dist/`.
Podgląd zbudowanej wersji: `npm run preview`.

## Pozostałe polecenia

- `npm run lint` – sprawdzenie kodu linterem (oxlint).

## Struktura

- `src/App.tsx` – układ aplikacji: ekran wizualizacji i panel z formularzem RSA.
- `src/api.ts` – komunikacja z backendem (`POST /api/v1/rsa/demo/encrypt`).
- `src/validation.ts` – podstawowa walidacja danych z formularza.
- `vite.config.ts` – konfiguracja Vite, w tym proxy do backendu.