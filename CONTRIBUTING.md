# Zasady

## 1. Konwencja językowa

**Język polski:**
- Dokumentacja, README i instrukcje.
- Komentarze w kodzie i docstringi.
- Tytuły i opisy GitHub Issues oraz Pull Requests.
- Opisy commitów (bez technicznych prefiksów).
- Komunikaty interfejsu użytkownika.

**Język angielski:**
- Kod źródłowy i identyfikatory.
- Nazwy funkcji, klas, zmiennych i stałych.
- Nazwy plików, katalogów i branchy.
- Endpointy API i pola JSON.
- Logi diagnostyczne.
- Prefiksy Conventional Commits.

Wszystkie pliki tekstowe zapisujemy w UTF-8.

## 2. Branche

Główna gałąź projektu to `main`.

Nie wprowadzamy zmian bezpośrednio do `main`. Każda zmiana powstaje na osobnej gałęzi i trafia do głównej przez Pull Request.

Format nazw:

`typ/numer-issue-krotki-opis`

Przykłady:
- `feat/12-rsa-keygen`
- `fix/18-modexp-overflow`
- `test/22-dh-validation`
- `docs/25-update-readme`

Typy branchy:
- `feat` – nowa funkcjonalność.
- `fix` – poprawka błędu.
- `test` – dodanie lub poprawa testów.
- `docs` – zmiany w dokumentacji.

## 3. Commity

Stosujemy Conventional Commits z polskimi opisami.

Format:

`typ(moduł): opis po polsku`

Przykłady:
- `feat(rsa): dodaj generowanie kluczy`
- `fix(dh): popraw walidację parametrów`
- `test(core): dodaj testy arytmetyki modularnej`
- `docs: uzupełnij opis architektury`

Commity powinny być małe, logiczne i jednoznaczne.

## 4. Pull Requests

Każda zmiana trafiająca do `main` wymaga:
- Pull Requesta powiązanego z odpowiednim Issue.
- Przeglądu kodu przez co najmniej jedną inną osobę.
- Przejścia odpowiednich testów.
- Rozwiązania uwag blokujących integrację.

Preferowany sposób integracji: **Squash and merge**.

Po scaleniu usuwamy branch roboczy (powinno się to robić automatycznie).

## 5. Jakość i testowanie

Wszystkie prace uznawane za ukończone muszą spełniać wspólną Definition of Done oraz kryteria akceptacji odpowiedniej funkcjonalności.

Definition of Done zostanie uzgodniona przez zespół i udokumentowana osobno.

## 6. Bezpieczeństwo

Nie commitujemy:
- Haseł i tokenów dostępowych.
- Rzeczywistych kluczy prywatnych.
- Plików `.env` zawierających sekrety.
- Danych poufnych lub osobowych bez uzasadnienia i zgody.
