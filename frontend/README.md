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

## Kompilacja produkcyjna

```bash
npm run build
```

Polecenie sprawdza typy TypeScript i buduje aplikację do katalogu `dist/`.
Podgląd zbudowanej wersji: `npm run preview`.

## Pozostałe polecenia

- `npm run lint` – sprawdzenie kodu linterem (oxlint).