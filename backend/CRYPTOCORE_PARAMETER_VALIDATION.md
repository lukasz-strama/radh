# Kontrakt CryptoCore dla losowania parametrów (#95/#96)

Ten dokument opisuje brakujący element CryptoCore potrzebny backendowi z #96.
Kod backendu jest już przygotowany na ten addytywny symbol. Istniejące ABI i
zachowanie `radh_dh_exchange_u32` nie mogą się zmienić.

## Zadanie dla implementacji CryptoCore

Do publicznego nagłówka `crypto-core/include/radh_crypto_core.h` dodaj:

```c
/* Waliduje parametry grupy multiplikatywnej modulo prime.
 * Kolejność walidacji: prime jest pierwsza, 2 <= generator < prime,
 * generator ma dokładnie rząd prime - 1.
 * Funkcja nie zapisuje danych i nie przechowuje argumentów.
 */
radh_status_t radh_dh_validate_parameters_u32(
    uint32_t prime,
    uint32_t generator
);
```

Funkcja ma być eksportowana z biblioteki współdzielonej pod dokładną nazwą
`radh_dh_validate_parameters_u32`. Adapter `ctypes` przekazuje dwa `uint32_t`,
oczekuje wyniku o ABI `int` i nie przekazuje bufora wyjściowego.

## Statusy

Należy użyć istniejących wartości, bez zmiany numeracji enum:

| Wynik | Wartość | Warunek |
| --- | ---: | --- |
| `RADH_STATUS_OK` | 0 | `prime` jest pierwsza, a `generator` ma rząd `prime - 1` |
| `RADH_STATUS_INVALID_PRIME` | 5 | `prime` nie jest liczbą pierwszą |
| `RADH_STATUS_INVALID_GENERATOR` | 6 | generator jest poza zakresem albo nie ma pełnego rzędu |

Nie dodajemy nowego kodu statusu. Dzięki temu adapter zachowuje zgodność z
dotychczasowym mapowaniem błędów. Dla `prime = 2` nie istnieje dozwolony
generator i funkcja zwraca `RADH_STATUS_INVALID_GENERATOR`.

## Wymagana walidacja pełnego rzędu

Dla pierwszego `p` rozłóż `p - 1` na unikalne czynniki pierwsze. `g` ma pełny
rząd wtedy i tylko wtedy, gdy dla każdego czynnika `q` zachodzi:

```text
g^((p - 1) / q) mod p != 1
```

Potęgowanie modularne powinno korzystać z istniejącej implementacji CryptoCore.
Implementacja musi być deterministyczna, nie alokować nieograniczonej pamięci i
zakończyć się dla każdego wejścia `uint32_t`.

Minimalne wektory kontraktowe:

| `prime` | `generator` | Oczekiwany status |
| ---: | ---: | --- |
| 23 | 5 | `OK` |
| 23 | 4 | `INVALID_GENERATOR` (rząd 11) |
| 23 | 1 | `INVALID_GENERATOR` (zakres) |
| 23 | 23 | `INVALID_GENERATOR` (zakres) |
| 21 | 2 | `INVALID_PRIME` |
| 2 | 2 | `INVALID_GENERATOR` |
| 65 521 | 17 | wynik zgodny z niezależną kontrolą rzędu |

## Testy i integracja

1. Dodaj testy CTest symbolu, kolejności walidacji oraz granic `uint32_t`.
2. Nie zaostrzaj `radh_dh_exchange_u32`: tryb ręczny nadal dopuszcza generator,
   który nie jest pierwiastkiem pierwotnym.
3. Zbuduj bibliotekę i uruchom `python -m pytest`. Test backendu automatycznie
   przestanie używać atrapy, gdy symbol będzie obecny.
4. Bez symbolu tylko `POST /api/v1/dh/demo/parameters` zwraca kontrolowane
   `503 CRYPTO_CORE_UNAVAILABLE`; dotychczasowa wymiana DH nadal działa.

RSA nie wymaga nowego ABI. Backend zatwierdza wylosowane `p`, `q` i `e` przez
istniejące `radh_rsa_keygen_u32` i nie zwraca z niego prywatnych `d` ani `phi`.
