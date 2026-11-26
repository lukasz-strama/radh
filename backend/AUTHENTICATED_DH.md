# Kontrakt uwierzytelnionego DH (#101–#103)

Dokument jest kontraktem integracyjnym backendu, węzłów i UI dla scenariusza
RSA + DH. Nie zmienia on uwierzytelniania HTTP: tokeny ról nadal chronią API
internal, a edukacyjne podpisy RSA uwierzytelniają wyłącznie transkrypt DH.

## Utworzenie i stany

`POST /api/v2/dh/sessions` przyjmuje nowe opcjonalne pole:

```json
{"prime":23,"generator":5,"mode":"normal","scenario":"authenticated"}
```

`scenario` ma wartość `classic` (domyślna, dotychczasowy protokół) albo
`authenticated`. Pole `mode` pozostaje niezależne: oba scenariusze obsługują
`normal` i `mitm`. Stare żądania bez `scenario` zachowują dotychczasowe
zachowanie i otrzymują w discovery jawną wartość `scenario="classic"`.

Każdy deskryptor zwracany przez
`GET /internal/v1/dh/nodes/{role}/sessions` zawiera wymagane pole
`scenario: "classic" | "authenticated"`. Proces węzła wybiera na tej podstawie
klasyczny przebieg albo RSA + DH przed rozpoczęciem operacji sesji. Modele węzłów
z #102 muszą przyjąć to pole przed równoległą integracją; nie należy wykrywać
scenariusza przez dodatkowe zapytanie ani kod błędu endpointu authentication.

Postęp uczestnika w scenariuszu uwierzytelnionym:

```text
waiting -> published -> verified
```

Pozytywna weryfikacja ustawia `verified`, a ACK po weryfikacji nie cofa tego
stanu. Wartość `received` pozostaje stanem klasycznego DH. Sesja
`authenticated` nie przechodzi do `completed`, dopóki:

1. oba zaufane klucze RSA są opublikowane,
2. obie wartości DH są dostarczone,
3. oba podpisy są opublikowane,
4. Alice i Bob zgłoszą pozytywną weryfikację podpisu partnera,
5. obie wiadomości DH zostaną potwierdzone po weryfikacji.

Negatywna weryfikacja atomowo ustawia `failed` z
`failure_code=SIGNATURE_VERIFICATION_FAILED`. Diagnostyka K jest wtedy zerowana;
nie jest prezentowana jako zaakceptowany sekret. Raport K uczestnika w sesji
uwierzytelnionej jest przyjmowany dopiero po `completed` i nadal wymaga obu
dotychczasowych opt-in.

## Operacje internal

Wszystkie operacje wymagają Bearer dokładnej roli, `X-Backend-Epoch`,
`X-Node-Instance` i przypisania instancji do sesji. Rola oraz pola
`session_id/backend_epoch` odpowiedzi pochodzą z backendu, nie z body.

| Metoda i ścieżka | Body / wynik |
| --- | --- |
| `POST /internal/v1/dh/sessions/{id}/trusted-keys` | `{modulus,public_exponent}` → zaufany klucz roli |
| `GET /internal/v1/dh/sessions/{id}/authentication` | maks. 2 klucze, 2 podpisy i 2 weryfikacje |
| `POST /internal/v1/dh/sessions/{id}/signatures` | `{transcript_hash,signature}` → podpis roli |
| `POST /internal/v1/dh/sessions/{id}/verifications` | `{signer,transcript_hash,verified}` → wynik weryfikacji partnera |

Mallory nie ma dostępu do tych operacji. Może podmieniać wyłącznie
wiadomości DH przez istniejący endpoint forward. Nie może publikować ani
podmieniać kluczy, podpisów lub wyników weryfikacji Alice/Boba.

Klucz wymaga `255 < modulus <= UINT32_MAX` oraz
`1 < public_exponent < modulus`. Podpis musi być mniejszy od modułu klucza
sygnatariusza. `transcript_hash` to 64 małe znaki hex SHA-256.

Identyczne retry zwraca zapisany obiekt bez nowego zdarzenia. Zmieniony klucz,
podpis lub raport tej samej roli daje odpowiednio `TRUSTED_KEY_CONFLICT`,
`SIGNATURE_CONFLICT` albo `VERIFICATION_CONFLICT`. Restart/fencing i obcy token
roli są odrzucane przed dostępem do rekordu, jak w klasycznym v2.

## Kanoniczny transkrypt v1

Węzeł podpisuje SHA-256 dokładnie następujących bajtów ASCII, z `LF` pomiędzy
liniami i bez końcowego `LF`:

```text
RADH-SIGNED-DH-V1
session_id=<32 lowercase hex>
backend_epoch=<32 lowercase hex>
signer=<alice|bob>
prime=<decimal uint32>
generator=<decimal uint32>
alice_public=<decimal uint32>
bob_public=<decimal uint32>
alice_rsa_n=<decimal uint32>
alice_rsa_e=<decimal uint32>
bob_rsa_n=<decimal uint32>
bob_rsa_e=<decimal uint32>
```

Nie ma spacji, lokalizacji, zer wiodących ani dodatkowych pól. Wartości RSA
są z zaufanej kolekcji koordynatora uporządkowane Alice, potem Bob.
`alice_public` i `bob_public` są lokalnym widokiem podpisującego: jego własna
oryginalna wartość i wartość partnera faktycznie mu dostarczona. W normalnym
przebiegu oba węzły widzą te same A/B. Po podmianie MITM widoki różnią się,
więc weryfikacja podpisu partnera musi zakończyć się niepowodzeniem.

Reprezentant podpisu to:

```text
h = int.from_bytes(SHA-256(transcript), "big") mod signer_rsa_n
```

CryptoCore #101 wykonuje wyłącznie operację podpisu/weryfikacji RSA na `h`.
Pełny 32-bajtowy hash jest publikowany jako `transcript_hash`; koordynator nie
oblicza podpisu i nie przechowuje prywatnego `d`, czynników RSA ani sekretów DH.

Weryfikator buduje transkrypt dla roli partnera ze swojego lokalnego widoku.
Przy `verified=true` backend wymaga zgodności lokalnego hasha z hashem
opublikowanego podpisu. Przy `verified=false` zapisuje oba hashe, co pozwala UI
pokazać kontrolowaną rozbieżność bez ujawniania K.

## Limity i zdarzenia

Kolekcje są częścią rekordu sesji, nie globalnego stanu: maksymalnie 2 klucze,
2 podpisy i 2 weryfikacje. TTL, retencja, limit sesji i blokada per rekord są
bez zmian. Limit historii pozostaje `MAX_EVENTS=32`; nie trzeba go zwiększać.
Najdłuższy poprawny przebieg authenticated+MITM zajmuje najwyżej 15 zdarzeń.

Nowe typy zdarzeń: `trusted_key_published`, `signature_published`,
`signature_verified`, `signature_rejected`. Zdarzenia nie zawierają klucza,
podpisu, hashy, tokenów ani K. Pełne publiczne dane uwierzytelnienia są widoczne
wyłącznie w `SessionView` chronionym tokenem właściciela; klucze prywatne nigdy
nie są polem modeli API.
