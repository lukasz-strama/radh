## Testy

Testy sprawdzają rzeczywistą bibliotekę C (przez `ctypes`) oraz endpoint
`POST /api/v1/rsa/demo/encrypt`. Obejmują poprawne i błędne dane
(`modulus=0`, `public_exponent=0`, `message ≥ modulus`, wartości spoza zakresu
uint32) i porównują wyniki z `pow()` z Pythona.

### Wymagania

- CMake ≥ 3.20 i kompilator C11 (GCC, Clang lub MSVC),
- Python ≥ 3.12.

### Uruchomienie (z katalogu głównego repozytorium)

```bash
# 1. Zbuduj bibliotekę C i uruchom jej testy (CTest)
cmake -S crypto-core -B crypto-core/build
cmake --build crypto-core/build
ctest --test-dir crypto-core/build --output-on-failure

# 2. Zainstaluj zależności testów w środowisku wirtualnym
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r tests/requirements.txt

# 3. Uruchom testy pytest
python -m pytest
```

Testy Pythona szukają biblioteki w `crypto-core/build/`. Inną ścieżkę podaj
w zmiennej `RADH_CRYPTO_CORE_LIBRARY`. Przy generatorach wieloplatformowych
(Visual Studio) dodaj `--config Release` do budowania i `-C Release` do CTest.
Brak zbudowanej biblioteki powoduje błąd testów, a nie ich pominięcie.

Przydatne warianty:

```bash
python -m pytest -m "not live"      # bez testów z prawdziwym serwerem uvicorn
python -m pytest tests/test_core_valid.py -v
```

### Testy jednostkowe backendu

```sh
python -m pytest tests/test_backend_unit.py
```

Nie wymagają kompilacji ani ładowania biblioteki C. Sprawdzają adapter na
kontrolowanej atrapie ABI, modele Pydantic i mapowanie błędów HTTP.
Testy integracyjne DH należą do osobnego zadania QA #30.

### Zestaw testów

Testy RSA są w `tests/tests_rsa/`, testy DH w `tests/tests_dh/`. Wspólne pliki
(`conftest.py`, `native_core.py`, `reference.py`, `data/`) leżą w `tests/`.

| Plik | Zakres |
| --- | --- |
| `tests/tests_rsa/test_core_valid.py` | poprawne parametry RSA, szyfrowanie i deszyfrowanie, znane wartości |
| `tests/tests_rsa/test_core_invalid.py` | błędne parametry, kolejność walidacji, wskaźnik `NULL`, niezmieniony wynik po błędzie |
| `tests/tests_rsa/test_core_vs_reference.py` | porównanie z `pow()`: losowe i graniczne dane |
| `tests/test_backend_unit.py` | jednostkowe: adapter DH/RSA, statusy ABI, modele DH, błędy HTTP; bez biblioteki C |
| `tests/tests_rsa/test_api_rsa.py` | endpoint FastAPI: wyniki, kody błędów, format odpowiedzi |
| `tests/tests_rsa/test_api_robustness.py` | serwer po błędnych żądaniach, brak biblioteki (503), prawdziwy proces `uvicorn` |
| `tests/tests_dh/test_dh_core_valid.py` | DH: wektor `A=8, B=19, K=2`, niezależne wyznaczenie sekretu przez Alice i Boba (`B^a` oraz `A^b` przez `radh_modexp_u32`), wartości graniczne uint32 |
| `tests/tests_dh/test_dh_core_invalid.py` | DH: `prime` (0, 1, złożone, pseudopierwsze), `generator`, sekrety zerowe, kolejność walidacji, `NULL`, struktura bez zmian po błędzie, wartości spoza uint32 (adapter) |
| `tests/tests_dh/test_dh_vs_reference.py` | DH: porównanie z `pow()` — losowe (5000 przypadków na test) i graniczne dane, status zgodny z oracle |
| `tests/tests_dh/test_api_dh.py` | endpoint DH: wyniki, kody 422, błędne typy i zakresy, odporność serwera (4xx/503/500 bez awarii), równoległość, proces `uvicorn`, regresja RSA |

Przypadki testowe RSA są w `tests/data/rsa_cases.json`, a DH w
`tests/data/dh_cases.json` (sekcje `valid` i `invalid`; wartości oczekiwane
zweryfikowano przez `pow()`). Testy regresji defektu
#26 (z PR #27) sprawdzają wspólny format błędów 404/405/400; po naprawie
usunięto z nich oznaczenie `xfail`. Pozostała treść testów QA jest niezmieniona.
Statusy i nagłówki obsługi błędów są sprawdzane w testach jednostkowych backendu.

### CI

Workflow `.github/workflows/tests.yml` uruchamia te same kroki przy każdym
Pull Requeście i pushu do `main`. Podsumowanie wyników jest widoczne na stronie
przebiegu.

Pliki z testami DH wykonują się w tym samym kroku `pytest` co pozostałe testy,
więc nie trzeba zmieniać workflow. Niepowodzenie dowolnego testu DH lub RSA
powoduje czerwony wynik workflow.

### Błędy DH w odpowiedzi API

| Sytuacja | HTTP | `error.code` |
| --- | --- | --- |
| `prime` nie jest pierwsza | 422 | `INVALID_PRIME` |
| `generator < 2` lub `generator ≥ prime` | 422 | `INVALID_GENERATOR` |
| sekret Alice lub Boba równy 0 | 422 | `INVALID_SECRET` |
| typ/zakres uint32, brakujące lub dodatkowe pole, zły JSON | 422 | `INVALID_REQUEST` |
| brak zbudowanej biblioteki | 503 | `CRYPTO_CORE_UNAVAILABLE` |
| status C spoza kontraktu | 500 | `INTERNAL_ERROR` |
