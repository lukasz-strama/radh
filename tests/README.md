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

| Plik | Zakres |
| --- | --- |
| `tests/test_core_valid.py` | poprawne parametry RSA, szyfrowanie i deszyfrowanie, znane wartości |
| `tests/test_core_invalid.py` | błędne parametry, kolejność walidacji, wskaźnik `NULL`, niezmieniony wynik po błędzie |
| `tests/test_core_vs_reference.py` | porównanie z `pow()`: losowe i graniczne dane |
| `tests/test_backend_unit.py` | jednostkowe: adapter DH/RSA, statusy ABI, modele DH, błędy HTTP; bez biblioteki C |
| `tests/test_api_rsa.py` | endpoint FastAPI: wyniki, kody błędów, format odpowiedzi |
| `tests/test_api_robustness.py` | serwer po błędnych żądaniach, brak biblioteki (503), prawdziwy proces `uvicorn` |

Przypadki testowe RSA są w `tests/data/rsa_cases.json`. Testy regresji defektu
#26 (z PR #27) sprawdzają wspólny format błędów 404/405/400; po naprawie
usunięto z nich oznaczenie `xfail`. Pozostała treść testów QA jest niezmieniona.
Statusy i nagłówki obsługi błędów są sprawdzane w testach jednostkowych backendu.

### CI

Workflow `.github/workflows/tests.yml` uruchamia te same kroki przy każdym
Pull Requeście i pushu do `main`. Podsumowanie wyników jest widoczne na stronie
przebiegu