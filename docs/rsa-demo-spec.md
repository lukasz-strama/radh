# Specyfikacja szyfrowania RSA i kontrakt API

Dokument opisuje edukacyjną wersję szyfrowania RSA używaną w projekcie RADH, interfejs funkcji w języku C wykonywanej na węźle oraz kontrakt komunikacji frontend – backend (HTTP i WebSocket). Jest źródłem prawdy dla implementacji węzła, backendu, frontendu i testów.

## 1. Opis i przyjęte ograniczenia

### 1.1. Operacja

Szyfrowanie RSA to potęgowanie modularne:

```
ciphertext = message ^ public_exponent mod modulus
```

Ta sama operacja (z wykładnikiem prywatnym) służy do deszyfrowania, dlatego rdzeń implementuje ogólne potęgowanie modularne. W zakresie tej specyfikacji udostępniamy wyłącznie **szyfrowanie**.

### 1.2. Ograniczenia edukacyjne

- Jest to tzw. *textbook RSA*: bez dopełnienia (padding, np. OAEP), więc **nie jest bezpieczne** i służy wyłącznie do nauki.
- Wiadomość jest pojedynczą liczbą całkowitą, a nie tekstem ani ciągiem bajtów.
- Moduł nie musi być iloczynem dwóch liczb pierwszych. Aplikacja tego nie sprawdza.
- Aplikacja nie weryfikuje, czy `public_exponent` jest względnie pierwszy z funkcją Eulera modułu.
- Rozmiary kluczy są celowo małe (do 32 bitów), co pozwala śledzić obliczenia ręcznie. Takie klucze można złamać w ułamku sekundy.
- Szyfrowanie jest deterministyczne: te same dane wejściowe zawsze dają ten sam wynik.

### 1.3. Zakres danych

Wszystkie wartości są liczbami całkowitymi bez znaku mieszczącymi się w `uint32_t` (od 0 do 4 294 967 295).

| Pole              | Warunek                | Uwagi                                     |
|-------------------|------------------------|-------------------------------------------|
| `message`         | `0 ≤ message < modulus` | Wartość spoza zakresu jest błędem, bez redukcji modulo. |
| `modulus`         | `modulus ≥ 2`          | Moduł 0 i 1 są niedozwolone.              |
| `public_exponent` | `public_exponent > 0`  | Wykładnik 0 jest niedozwolony.            |

Wynik `ciphertext` spełnia `0 ≤ ciphertext < modulus`, więc również mieści się w `uint32_t`.

### 1.4. Arytmetyka

Iloczyn dwóch wartości mniejszych od `modulus` może przekroczyć 32 bity. Ponieważ `(2^32 − 1)^2 < 2^64`, wszystkie mnożenia pośrednie wykonujemy w `uint64_t`, a redukcję modulo po każdym mnożeniu. Zalecany algorytm to szybkie potęgowanie modularne (square-and-multiply), bez obliczania pełnej potęgi.

## 2. Funkcja w języku C

### 2.1. Sygnatura

```c
#include <stdint.h>

typedef enum {
    RADH_STATUS_OK = 0,
    RADH_STATUS_INVALID_POINTER = 1,
    RADH_STATUS_INVALID_MODULUS = 2,
    RADH_STATUS_INVALID_EXPONENT = 3,
    RADH_STATUS_INVALID_MESSAGE = 4
} radh_status_t;

radh_status_t rsa_encrypt(
    uint32_t message,
    uint32_t modulus,
    uint32_t public_exponent,
    uint32_t *ciphertext
);
```

### 2.2. Zasady zwracania błędów

Funkcja jest wykonywana **na węźle**. Backend jej nie wywołuje, pełni wyłącznie rolę pośrednika (patrz sekcja 3).

- Funkcja zwraca kod `radh_status_t`, a wynik zapisuje przez wskaźnik `ciphertext`.
- Przy kodzie innym niż `RADH_OK` wartość pod `*ciphertext` **nie jest modyfikowana**.
- Funkcja nie używa wyjątków, `errno` ani zmiennych globalnych, jest czysta i bezpieczna wątkowo.
- Walidacja odbywa się w następującej kolejności (zwracany jest pierwszy napotkany błąd):

| Kolejność | Warunek błędu              | Kod                             |
|-----------|----------------------------|---------------------------------|
| 1         | `ciphertext == NULL`       | `RADH_ERR_NULL_ARGUMENT`        |
| 2         | `modulus < 2`              | `RADH_ERR_INVALID_MODULUS`      |
| 3         | `public_exponent == 0`     | `RADH_ERR_INVALID_EXPONENT`     |
| 4         | `message >= modulus`       | `RADH_ERR_MESSAGE_OUT_OF_RANGE` |

## 3. Kontrakt komunikacji frontend – backend – węzeł

### 3.1. Przepływ

1. Frontend wysyła `POST /api/v1/nodes/{node_id}/commands` z typem operacji i `payload`.
2. Backend waliduje żądanie. Jeśli jest poprawne, odpowiada `202 Accepted` z `operation_id` i statusem `accepted`, a następnie przekazuje polecenie wskazanemu węzłowi przez WebSocket.
3. Węzeł wykonuje szyfrowanie (`rsa_encrypt`) i odsyła wynik do backendu.
4. Backend przekazuje wynik frontendowi przez WebSocket jako zdarzenie `rsa.encryption_completed`.
5. Jeśli wykonanie na węźle się nie powiodło, frontend dostaje zdarzenie błędu przez WebSocket (sekcja 3.5).

Backend nie wykonuje żadnych obliczeń kryptograficznych. Ten sam mechanizm (zmiana `type` i zawartości `payload`) posłuży później do deszyfrowania i Diffiego–Hellmana.

### 3.2. Żądanie

```
POST /api/v1/nodes/node-01/commands
Content-Type: application/json
```

```json
{
  "type": "rsa.encrypt",
  "payload": {
    "message": 65,
    "public_key": {
      "n": 3233,
      "e": 17
    }
  }
}
```

| Pole                    | Typ    | Opis                                        |
|-------------------------|--------|---------------------------------------------|
| `type`                  | string | Typ operacji. Dla tej specyfikacji: `rsa.encrypt`. |
| `payload.message`       | uint32 | Wiadomość (parametr `message` funkcji C).   |
| `payload.public_key.n`  | uint32 | Moduł (parametr `modulus` funkcji C).       |
| `payload.public_key.e`  | uint32 | Wykładnik publiczny (parametr `public_exponent` funkcji C). |

Wszystkie pola są wymagane. Każda wartość RSA musi być liczbą całkowitą JSON (nie tekstem, nie liczbą zmiennoprzecinkową, nie `null`) z zakresu od 0 do 4294967295. Nieznane pola są ignorowane.

### 3.3. Odpowiedź na żądanie (`202 Accepted`)

```json
{
  "operation_id": "b3f1c0de-5a47-4c1e-9d2b-7e8f6a1c2d34",
  "status": "accepted"
}
```

`202` oznacza wyłącznie przyjęcie polecenia do wykonania, a nie jego wynik. `operation_id` jest unikalnym identyfikatorem operacji (UUID w postaci tekstowej), po którym frontend łączy odpowiedź HTTP ze zdarzeniami WebSocket.

### 3.4. Zdarzenie powodzenia (WebSocket)

```json
{
  "type": "rsa.encryption_completed",
  "operation_id": "b3f1c0de-5a47-4c1e-9d2b-7e8f6a1c2d34",
  "node_id": "node-01",
  "ciphertext": 2790
}
```

`ciphertext` jest liczbą z zakresu `0 ≤ ciphertext < n`.

### 3.5. Zdarzenie błędu wykonania (WebSocket)

Błędy wykonania, czyli takie, które wystąpiły po przyjęciu żądania (węzeł odrzucił dane, błąd węzła, utrata połączenia), są zgłaszane przez WebSocket:

```json
{
  "type": "rsa.encryption_failed",
  "operation_id": "b3f1c0de-5a47-4c1e-9d2b-7e8f6a1c2d34",
  "node_id": "node-01",
  "error": {
    "code": "MESSAGE_OUT_OF_RANGE",
    "message": "Wiadomość musi być mniejsza od modułu."
  }
}
```

Pole `code` jest stałym identyfikatorem po angielsku (do obsługi w kodzie), a `message` komunikatem po polsku (do wyświetlenia użytkownikowi).

### 3.6. Błędy żądania (`400 Bad Request`)

Błędne żądania są odrzucane od razu kodem `400`, a polecenie nie trafia do węzła ani nie dostaje `operation_id`:

```json
{
  "error": {
    "code": "INVALID_MODULUS",
    "message": "Moduł musi być co najmniej równy 2."
  }
}
```

### 3.7. Kody błędów

| `error.code`           | Kiedy                                                                 | Gdzie zgłaszany        | Odpowiada kodowi C              |
|------------------------|-----------------------------------------------------------------------|------------------------|---------------------------------|
| `INVALID_REQUEST`      | Niepoprawny JSON, brak pola, zły typ, wartość poza `uint32_t`         | HTTP 400               | -                               |
| `UNSUPPORTED_OPERATION`| Nieznany `type`                                                       | HTTP 400               | -                               |
| `INVALID_MODULUS`      | `n < 2`                                                               | HTTP 400 lub WebSocket | `RADH_ERR_INVALID_MODULUS`      |
| `INVALID_EXPONENT`     | `e == 0`                                                              | HTTP 400 lub WebSocket | `RADH_ERR_INVALID_EXPONENT`     |
| `MESSAGE_OUT_OF_RANGE` | `message >= n`                                                        | HTTP 400 lub WebSocket | `RADH_ERR_MESSAGE_OUT_OF_RANGE` |
| `INTERNAL_ERROR`       | `RADH_ERR_NULL_ARGUMENT`, nieznany kod z węzła lub inny błąd wykonania | WebSocket              | `RADH_ERR_NULL_ARGUMENT`        |

Reguły dziedzinowe (moduł, wykładnik, wiadomość) są sprawdzane w dwóch miejscach: backend odrzuca je wcześnie kodem `400`, a węzeł i tak weryfikuje je w `rsa_encrypt` i w razie potrzeby zgłasza błąd przez WebSocket.

## 4. Wektory testowe

### 4.1. Przypadki poprawne

| `message`   | `modulus`    | `public_exponent` | `ciphertext` | Opis                                       |
|-------------|--------------|-------------------|--------------|--------------------------------------------|
| 65          | 3233         | 17                | 2790         | Klasyczny przykład (p = 61, q = 53, d = 413) |
| 2790        | 3233         | 413               | 65           | Deszyfrowanie powyższego (wykładnik prywatny) |
| 0           | 2            | 1                 | 0            | Wartości minimalne                         |
| 3232        | 3233         | 17                | 3232         | `message = modulus − 1`, wykładnik nieparzysty |
| 4294967294  | 4294967295   | 1                 | 4294967294   | Maksymalny moduł, brak przepełnienia       |
| 2           | 4294967295   | 32                | 1            | Maksymalny moduł, potęgowanie z redukcją   |

### 4.2. Przypadki błędne

| `message`   | `modulus`    | `public_exponent` | Oczekiwany kod                  |
|-------------|--------------|-------------------|---------------------------------|
| 0           | 1            | 1                 | `RADH_ERR_INVALID_MODULUS`      |
| 0           | 0            | 1                 | `RADH_ERR_INVALID_MODULUS`      |
| 5           | 3233         | 0                 | `RADH_ERR_INVALID_EXPONENT`     |
| 3233        | 3233         | 17                | `RADH_ERR_MESSAGE_OUT_OF_RANGE` |
| 4294967295  | 4294967295   | 17                | `RADH_ERR_MESSAGE_OUT_OF_RANGE` |

Dodatkowo test `ciphertext == NULL` oraz sprawdzenie, że po błędzie wartość wynikowa pozostaje nietknięta.

### 4.3. Przykład żądania z błędem

Żądanie `POST /api/v1/nodes/node-01/commands`:

```json
{
  "type": "rsa.encrypt",
  "payload": { "message": 3233, "public_key": { "n": 3233, "e": 17 } }
}
```

Odpowiedź `400 Bad Request`:

```json
{
  "error": {
    "code": "MESSAGE_OUT_OF_RANGE",
    "message": "Wiadomość musi być mniejsza od modułu."
  }
}
```

## 5. Poza zakresem

- Generowanie kluczy (wybór liczb pierwszych, obliczanie wykładnika prywatnego).
- Dopełnienie (padding) i kodowanie tekstu na liczby.
- Liczby większe niż 32 bity.
- Wymiana kluczy Diffiego–Hellmana i deszyfrowanie (osobne typy operacji w tym samym mechanizmie).
- Protokół WebSocket pomiędzy backendem a węzłem oraz adres kanału WebSocket dla frontendu (osobne ustalenia).
