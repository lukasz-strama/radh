# CryptoCore

Biblioteka współdzielona dla RADH wykonuje potęgowanie modularne, edukacyjne
szyfrowanie RSA i wymianę kluczy DH na liczbach `uint32_t`. Backend FastAPI może
ładować ją przez Python `ctypes`. Biblioteka i testy C nie wymagają zależności
zewnętrznych ani Pythona; implementacja nie alokuje pamięci dynamicznie.

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
│   ├── dh.c
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

Testy DH obejmują wektor `p=23, g=5, a=6, b=15` (wyniki `8, 19, 2, 2`),
generator niepierwotny, wynik 1, największą liczbę pierwszą `uint32_t`,
sekrety `UINT32_MAX`, liczby złożone (w tym kwadraty i pseudopierwsze),
`NULL`, kolejność błędów oraz niezmienność całej pamięci wyniku przy błędzie.
Dla małych argumentów porównują wyniki z liniowym potęgowaniem i jawną listą
liczb pierwszych. Testy RSA i modexp są uruchamiane w tym samym zestawie.

Konfiguracja Release z `NDEBUG`:

```sh
cmake -S crypto-core -B crypto-core/build/release -DCMAKE_BUILD_TYPE=Release
cmake --build crypto-core/build/release
ctest --test-dir crypto-core/build/release --output-on-failure
```

CMake włącza `-Wall -Wextra -Wpedantic` dla GCC/Clang/Apple Clang.

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

typedef struct {
    uint32_t alice_public;
    uint32_t bob_public;
    uint32_t alice_shared_key;
    uint32_t bob_shared_key;
} radh_dh_exchange_result_t;

radh_status_t radh_dh_exchange_u32(
    uint32_t prime,
    uint32_t generator,
    uint32_t alice_secret,
    uint32_t bob_secret,
    radh_dh_exchange_result_t *result
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

`radh_dh_exchange_u32` wykonuje demonstrację wymiany kluczy Diffiego–Hellmana:

- `prime` (`p`): liczba pierwsza mieszcząca się w `uint32_t`.
- `generator` (`g`): `2 <= generator < prime`; pierwotność nie jest sprawdzana.
- `alice_secret` (`a`) i `bob_secret` (`b`): od 1 do `UINT32_MAX`, również
  większe lub równe `prime`.
- `result`: struktura z `alice_public = g^a mod p`, `bob_public = g^b mod p`,
  `alice_shared_key = bob_public^a mod p` i
  `bob_shared_key = alice_public^b mod p`.

Pierwszość `prime = 2` jest poprawna, ale nie istnieje dla niej dopuszczalny
generator: funkcja zwróci `RADH_STATUS_INVALID_GENERATOR`. Najmniejsze poprawne
parametry to `prime = 3`, `generator = 2`. Największa obsługiwana liczba pierwsza
to `4294967291`; `UINT32_MAX` jest złożona. Wartości publiczne i wspólny sekret
równe 1 są dozwolone, np. gdy sekret jest wielokrotnością `prime - 1`.

Wszystkie funkcje zapisują wynik tylko po sukcesie. **Każdy błąd pozostawia parametr
wyjściowy bez zmian.** Wskaźnik `NULL` jest odrzucany; inny wskaźnik musi wskazywać
żywy, poprawnie wyrównany, zapisywalny obiekt `uint32_t` dla modexp/RSA lub
`radh_dh_exchange_result_t` dla DH. W DH niezmienność dotyczy całej struktury;
wyniki pośrednie są przechowywane lokalnie. C nie pozwala przenośnie
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
| `RADH_STATUS_INVALID_PRIME` | 5 | Parametr DH `prime` nie jest liczbą pierwszą (także 0 i 1). |
| `RADH_STATUS_INVALID_GENERATOR` | 6 | Parametr DH `generator` jest mniejszy niż 2 lub nie jest mniejszy niż `prime`. |
| `RADH_STATUS_INVALID_SECRET` | 7 | Co najmniej jeden sekret DH jest równy 0. |

Kolejność walidacji RSA to wskaźnik, moduł, wykładnik, wiadomość.
Modexp sprawdza tylko wskaźnik i moduł. DH sprawdza kolejno wskaźnik,
pierwszość `prime`, zakres `generator`, dodatniość `alice_secret`, dodatniość
`bob_secret`. Przy kilku błędach funkcja zwraca pierwszy z nich.
Nie korzystamy z `errno`, wyjątków ani globalnego bufora błędów.

Kontrakt ABI dla Linux/macOS z GCC/Clang zakłada 32-bitowy `int` i enum wielkości
`int`; `restype` w `ctypes` to `c_int`. Nagłówek sprawdza rozmiary przez
`_Static_assert`, także w kodzie klienta C. C11 nie ustala sam rozmiaru enum,
więc nie wolno używać `-fshort-enums` ani innych opcji zmieniających ABI.
Wartości 0–4 nie będą przenumerowywane; klient powinien traktować każdy status
inny niż 0 jako błąd. Argumenty liczbowe i poszczególne wartości wynikowe
odpowiadają `ctypes.c_uint32`. Struktura DH odpowiada `ctypes.Structure` z czterema
polami `c_uint32` w kolejności z nagłówka, z naturalnym wyrównaniem (bez `_pack_`).
W obsługiwanym ABI zajmuje 16 bajtów, a pola mają przesunięcia 0, 4, 8 i 12.
Testy C sprawdzają rozmiar i przesunięcia pól przez `_Static_assert`.

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

DH korzysta z czterech wywołań `radh_modexp_u32()`: oblicza obie wartości
publiczne, następnie niezależnie oba wspólne sekrety. Sprawdza status każdego
wywołania i przekazuje błąd bez zapisywania struktury wynikowej. Dopiero po
czterech sukcesach przypisuje całą lokalną strukturę do `*result`.

Test pierwszości jest deterministyczny dla całego zakresu `uint32_t`:
odrzuca wartości poniżej 2, obsługuje osobno 2 i pozostałe liczby parzyste,
a następnie sprawdza nieparzyste dzielniki od 3 przy warunku
`divisor <= prime / divisor`. Warunek uwzględnia pierwiastek dla kwadratów
i unika przepełnienia iloczynu `divisor * divisor`. Nie używa liczb
zmiennoprzecinkowych. Koszt walidacji to O(√prime), a całej wymiany
O(√prime + log alice_secret + log bob_secret); pamięć dodatkowa to O(1).

**DH jest wyłącznie demonstracją edukacyjną, a nie produkcyjną, bezpieczną
kryptograficznie implementacją.** Liczby 32-bitowe są za małe do ochrony danych,
obliczenia nie działają w stałym czasie, generator może mieć mały rząd,
a sekrety dostarcza wywołujący. Nie ma losowania sekretów, uwierzytelniania,
ochrony przed MITM ani funkcji wyprowadzania klucza (KDF). Zwracany wspólny
sekret jest liczbą ilustrującą DH, nie gotowym kluczem do szyfrowania danych.

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

Przykład DH:

```c
#include "radh_crypto_core.h"

#include <inttypes.h>
#include <stdio.h>

int main(void)
{
    radh_dh_exchange_result_t result = {0};
    radh_status_t status = radh_dh_exchange_u32(23, 5, 6, 15, &result);
    if (status != RADH_STATUS_OK) {
        fprintf(stderr, "DH failed: %d\n", (int)status);
        return 1;
    }
    printf("A=%" PRIu32 ", B=%" PRIu32 ", K_A=%" PRIu32 ", K_B=%" PRIu32 "\n",
        result.alice_public, result.bob_public,
        result.alice_shared_key, result.bob_shared_key);
    /* Wynik: A=8, B=19, K_A=2, K_B=2. */
    return 0;
}
```

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


class DhExchangeResult(ctypes.Structure):
    _fields_ = [
        ("alice_public", ctypes.c_uint32),
        ("bob_public", ctypes.c_uint32),
        ("alice_shared_key", ctypes.c_uint32),
        ("bob_shared_key", ctypes.c_uint32),
    ]


core.radh_dh_exchange_u32.argtypes = [
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.POINTER(DhExchangeResult),
]
core.radh_dh_exchange_u32.restype = ctypes.c_int

exchange = DhExchangeResult()
status = core.radh_dh_exchange_u32(23, 5, 6, 15, ctypes.byref(exchange))
if status != 0:
    raise ValueError(f"CryptoCore status: {status}")
print(exchange.alice_public, exchange.bob_public,
      exchange.alice_shared_key, exchange.bob_shared_key)  # 8 19 2 2
```

Backend musi przed konwersją sprawdzać typy i zakres liczb Pythona
`0 <= value <= 4294967295`, ponieważ `ctypes.c_uint32` może zawijać wartości
ujemne i zbyt duże. Następnie musi sprawdzić status przed użyciem wyniku.
Docelową ścieżkę biblioteki należy ustalić przy wdrożeniu backendu; przykład
używa bezwzględnej ścieżki wyliczonej z katalogu roboczego.

## Wykorzystanie AI
Dokumentacja generowana na podstawie kodu [GPT-6-Astra], ręcznie sprawdzona i poprawiona.
