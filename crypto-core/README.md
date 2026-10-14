# CryptoCore

Biblioteka współdzielona dla RADH wykonuje potęgowanie modularne i edukacyjne
szyfrowanie RSA na liczbach `uint32_t`. Backend FastAPI może ładować ją przez
Python `ctypes`. Biblioteka i testy C nie wymagają zależności zewnętrznych ani
Pythona; implementacja nie alokuje pamięci dynamicznie.

**Ta implementacja nie zapewnia bezpieczeństwa kryptograficznego.** Operuje na
liczbach co najwyżej 32-bitowych, nie ma paddingu, jest deterministyczna
i nie działa w stałym czasie. Służy wyłącznie do demonstracji matematycznej.

## Struktura

```text
crypto-core/
├── CMakeLists.txt
├── README.md
├── include/
│   ├── README.md
│   └── radh_crypto_core.h
├── src/
│   ├── modexp.c
│   └── rsa.c
└── tests/
    └── crypto_core_test.c
```

## Budowanie i testy

Wymagania: CMake 3.20 lub nowszy, kompilator C11 (GCC, Clang lub Apple Clang)
i narzędzie budowania, np. Make lub Ninja. Z katalogu głównego repozytorium:

```sh
cmake -S crypto-core -B crypto-core/build
cmake --build crypto-core/build
ctest --test-dir crypto-core/build --output-on-failure
```

Target `radh_crypto_core` jest biblioteką `SHARED`.
Buduj poza katalogiem źródeł. Katalog `build/` jest ignorowany przez Git.
Dla generatorów Make/Ninja biblioteka powstaje w:

- Linux: `crypto-core/build/libradh_crypto_core.so`.
- macOS: `crypto-core/build/libradh_crypto_core.dylib`.

CTest uruchamia `radh_crypto_core_tests`, linkowany z rzeczywistą biblioteką
współdzieloną. Testy obejmują znane wektory, granice `uint32_t`, mnożenie wymagające
64 bitów, walidację, pierwszeństwo błędów i zachowanie niezmienionego wyjścia.
Dodatkowo porównują małe obliczenia z niezależnym algorytmem liniowym. Sprawdzanie
wyników działa również w Release z `NDEBUG`. Testy można wyłączyć opcją
`-DBUILD_TESTING=OFF`.

Inny kompilator należy wybrać w osobnym katalogu budowania, np.:

```sh
cmake -S crypto-core -B crypto-core/build/clang -DCMAKE_C_COMPILER=clang
cmake --build crypto-core/build/clang
ctest --test-dir crypto-core/build/clang --output-on-failure
```

Przy generatorach z wieloma konfiguracjami dodaj `--config Release` do budowania
oraz `-C Release` do CTest; biblioteka może znajdować się w podkatalogu `Release/`.

## Publiczne API i ABI

Nagłówek: `include/radh_crypto_core.h`.

```c
radh_status_t radh_modexp_u32(
    uint32_t base,
    uint32_t exponent,
    uint32_t modulus,
    uint32_t *result
);

radh_status_t radh_rsa_encrypt_u32(
    uint32_t message,
    uint32_t public_exponent,
    uint32_t modulus,
    uint32_t *ciphertext
);
```

`radh_modexp_u32` oblicza `base^exponent mod modulus`:

- `base`: dowolny `uint32_t`, redukowany modulo `modulus`.
- `exponent`: dowolny `uint32_t`, w tym 0.
- `modulus`: od 1 do `UINT32_MAX`; 0 jest błędem.
- Wykładnik 0 daje `1 % modulus`, również dla podstawy 0 (konwencja pustego
  iloczynu). Moduł 1 zawsze daje 0.

`radh_rsa_encrypt_u32` oblicza `message^public_exponent mod modulus`:

- `modulus`: od 2 do `UINT32_MAX`.
- `message`: od 0 do `modulus - 1`.
- `public_exponent`: od 1 do `UINT32_MAX`.

RSA sprawdza wyłącznie te zakresy. Nie sprawdza, czy moduł jest iloczynem dwóch
liczb pierwszych ani czy wykładnik stanowi poprawny klucz RSA.

Obie funkcje zapisują wynik tylko po sukcesie. **Każdy błąd pozostawia parametr
wyjściowy bez zmian.** Wskaźnik `NULL` jest odrzucany; inny wskaźnik musi wskazywać
żywy, poprawnie wyrównany, zapisywalny obiekt `uint32_t`. C nie pozwala przenośnie
wykrywać dowolnych niepoprawnych adresów pamięci. Pamięć wyniku należy do
wywołującego; biblioteka nie przechowuje wskaźnika i nie wymaga zwalniania pamięci.
Brak współdzielonego stanu pozwala na równoległe wywołania z osobnymi wyjściami.

### Kody statusu

Publiczny enum `radh_status_t` ma jawne, stałe wartości:

| Nazwa | Wartość | Znaczenie |
| --- | ---: | --- |
| `RADH_STATUS_OK` | 0 | Sukces; wynik został zapisany. |
| `RADH_STATUS_INVALID_POINTER` | 1 | Wskaźnik wyjścia jest `NULL`. |
| `RADH_STATUS_INVALID_MODULUS` | 2 | Moduł 0 dla modexp albo moduł mniejszy niż 2 dla RSA. |
| `RADH_STATUS_INVALID_EXPONENT` | 3 | Wykładnik RSA jest równy 0. |
| `RADH_STATUS_INVALID_MESSAGE` | 4 | Wiadomość RSA jest większa lub równa modułowi. |

Kolejność walidacji to wskaźnik, moduł, wykładnik RSA, wiadomość RSA. Przy kilku
błędach funkcja zwraca pierwszy z nich; modexp sprawdza tylko wskaźnik i moduł.
Nie korzystamy z `errno`, wyjątków ani globalnego bufora błędów.

Kontrakt ABI dla Linux/macOS z GCC/Clang zakłada 32-bitowy `int` i enum wielkości
`int`; `restype` w `ctypes` to `c_int`. Nagłówek sprawdza rozmiary przez
`_Static_assert`, także w kodzie klienta C. C11 nie ustala sam rozmiaru enum,
więc nie wolno używać `-fshort-enums` ani innych opcji zmieniających ABI.
Wartości 0–4 nie będą przenumerowywane; klient powinien traktować każdy status
inny niż 0 jako błąd. Argumenty i wynik odpowiadają `ctypes.c_uint32`.

### Algorytm

Potęgowanie korzysta z binary exponentiation (square-and-multiply). Akumulator
zaczyna od `1 % modulus`, a czynnik od `base % modulus`. Dla kolejnych bitów
wykładnika od najmłodszego mnożymy akumulator przez czynnik, jeśli bit wynosi 1,
po czym podnosimy czynnik do kwadratu i przesuwamy wykładnik w prawo.
Każdy iloczyn redukujemy modulo `modulus`.

Rzutowanie na `uint64_t` następuje **przed mnożeniem**. Iloczyn dwóch wartości
`uint32_t` nie przekracza `(2^32 - 1)^2`, więc mieści się w `uint64_t`.
Nie używamy zmiennoprzecinkowych obliczeń ani `pow()`/`powf()`.
Złożoność czasowa to O(log exponent) dla dodatniego wykładnika (maksymalnie
32 iteracje), a pamięciowa O(1). Wykładnik 0 nie wymaga iteracji.

## Przykład C

```c
#include "radh_crypto_core.h"

#include <inttypes.h>
#include <stdio.h>

int main(void)
{
    uint32_t ciphertext = 0;
    radh_status_t status = radh_rsa_encrypt_u32(65, 17, 3233, &ciphertext);
    if (status != RADH_STATUS_OK) {
        fprintf(stderr, "RSA failed: %d\n", (int)status);
        return 1;
    }
    printf("%" PRIu32 "\n", ciphertext); /* 2790 */
    return 0;
}
```

Kod klienta w CMake powinien linkować target `radh_crypto_core`, który udostępnia
również katalog publicznego nagłówka przez `target_include_directories(PUBLIC)`.

## Przykład Python ctypes

Uruchom z katalogu głównego repozytorium po zbudowaniu biblioteki:

```python
import ctypes
import sys
from pathlib import Path

library_name = (
    "libradh_crypto_core.dylib" if sys.platform == "darwin"
    else "libradh_crypto_core.so"
)
library_path = (Path("crypto-core/build") / library_name).resolve()
core = ctypes.CDLL(str(library_path))

for name in ("radh_modexp_u32", "radh_rsa_encrypt_u32"):
    function = getattr(core, name)
    function.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    function.restype = ctypes.c_int

ciphertext = ctypes.c_uint32(0)
status = core.radh_rsa_encrypt_u32(65, 17, 3233, ctypes.byref(ciphertext))
if status != 0:
    raise ValueError(f"CryptoCore status: {status}")
print(ciphertext.value)  # 2790

result = ctypes.c_uint32(0)
status = core.radh_modexp_u32(15, 3, 13, ctypes.byref(result))
if status != 0:
    raise ValueError(f"CryptoCore status: {status}")
print(result.value)  # 8
```

Backend musi przed konwersją sprawdzać typy i zakres liczb Pythona
`0 <= value <= 4294967295`, ponieważ `ctypes.c_uint32` może zawijać wartości
ujemne i zbyt duże. Następnie musi sprawdzić status przed użyciem wyniku.
Docelową ścieżkę biblioteki należy ustalić przy wdrożeniu backendu; przykład
używa bezwzględnej ścieżki wyliczonej z katalogu roboczego.

## Wykorzystanie AI
Dokumentacja generowana na podstawie kodu [GPT-6-Astra], ręcznie sprawdzona i poprawiona.