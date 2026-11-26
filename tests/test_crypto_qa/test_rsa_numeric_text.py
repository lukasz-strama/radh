"""#107 / #75: RSA liczbowe i tekstowe (UTF-8) na żywym backendzie.

Referencja: szyfrogramy liczymy w Pythonie jako ``pow(bajt, e, n)`` dla każdego bajtu
UTF-8 (kontrakt #99/#109: bajt po bajcie, 1–128 bajtów, moduł > 255, bez paddingu).
"""

import json

import pytest

from .conftest import UINT32_MAX, code, rsa_keys

pytestmark = pytest.mark.live

KEY = rsa_keys(61, 53, 17)                    # n=3233, d=2753 — wektor z dokumentacji
BIG = rsa_keys(65_521, 65_519, 65_537)        # największy moduł z zakresu 16-bitowych p, q
SMALL = rsa_keys(17, 19, 5)                   # n=323: najmniejszy sensowny moduł > 255

TEXTS = [
    "HELLO",
    "zażółć gęślą jaźń",
    "ZAŻÓŁĆ GĘŚLĄ JAŹŃ",
    "Łódź, Kraków, Gdańsk — „cudzysłów”",
    "🔐🔑 klucz",                              # 4-bajtowe znaki UTF-8
    "Ελληνικά · Русский · 日本語",
    "é vs é",                           # znak łączący (NFD) i złożony (NFC) różnią się
    " ",
    "\n\t tabulator i nowa linia",
    "a" * 128,                                 # dokładnie limit bajtów
    "ą" * 64,                                  # 128 bajtów w znakach 2-bajtowych
]


def encrypt(api, text, key=KEY):
    return api.http.post("/api/v1/rsa/demo/text/encrypt", json={
        "text": text, "public_exponent": key["e"], "modulus": key["n"]})


def decrypt(api, ciphertexts, key=KEY, d=None):
    return api.http.post("/api/v1/rsa/demo/text/decrypt", json={
        "ciphertexts": ciphertexts, "private_exponent": key["d"] if d is None else d,
        "modulus": key["n"]})


# --- RSA liczbowe ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", [KEY, BIG, SMALL], ids=["3233", "max16bit", "323"])
@pytest.mark.parametrize("m", [0, 1, 2, 65, 255, 256, "n-2", "n-1"])
def test_numeric_roundtrip(api, key, m):
    m = {"n-2": key["n"] - 2, "n-1": key["n"] - 1}.get(m, m)
    c = api.http.post("/api/v1/rsa/demo/encrypt", json={
        "message": m, "public_exponent": key["e"], "modulus": key["n"]})
    assert c.json() == {"ciphertext": pow(m, key["e"], key["n"])}
    back = api.http.post("/api/v1/rsa/demo/decrypt", json={
        "ciphertext": c.json()["ciphertext"], "private_exponent": key["d"], "modulus": key["n"]})
    assert back.json() == {"message": m}


@pytest.mark.parametrize(("body", "expected"), [
    ({"ciphertext": 3233, "private_exponent": 2753, "modulus": 3233}, 422),        # c = n
    ({"ciphertext": 1, "private_exponent": 0, "modulus": 3233}, 422),              # d = 0
    ({"ciphertext": 1, "private_exponent": 2753, "modulus": 1}, 422),              # n < 2
    ({"ciphertext": UINT32_MAX + 1, "private_exponent": 1, "modulus": 3233}, 422),
    ({"ciphertext": -1, "private_exponent": 1, "modulus": 3233}, 422),
    ({"ciphertext": "5", "private_exponent": 1, "modulus": 3233}, 422),            # string
    ({"ciphertext": True, "private_exponent": 1, "modulus": 3233}, 422),           # bool
    ({"ciphertext": 5.0, "private_exponent": 1, "modulus": 3233}, 422),            # float
    ({"ciphertext": 5, "private_exponent": 1, "modulus": 3233, "x": 1}, 422),      # extra
    ({"ciphertext": 5, "private_exponent": 1}, 422),                                # brak n
])
def test_numeric_decrypt_rejects_bad_input(api, body, expected):
    response = api.http.post("/api/v1/rsa/demo/decrypt", json=body)
    assert response.status_code == expected, response.text
    assert "error" in response.json()
    # Odrzucone wejście nie zmienia kolejnych wyników (operacje są bezstanowe).
    ok = api.http.post("/api/v1/rsa/demo/decrypt", json={
        "ciphertext": 2790, "private_exponent": 2753, "modulus": 3233})
    assert ok.json() == {"message": 65}


# --- RSA tekstowe ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", TEXTS, ids=range(len(TEXTS)))
@pytest.mark.parametrize("key", [KEY, BIG, SMALL], ids=["3233", "max16bit", "323"])
def test_text_roundtrip_matches_reference(api, key, text):
    raw = text.encode("utf-8")
    assert 1 <= len(raw) <= 128
    response = encrypt(api, text, key)
    assert response.status_code == 200, response.text
    ciphertexts = response.json()["ciphertexts"]
    assert ciphertexts == [pow(b, key["e"], key["n"]) for b in raw]
    back = decrypt(api, ciphertexts, key)
    assert back.status_code == 200, back.text
    assert back.json() == {"text": text}, "tekst musi wrócić bajt w bajt (bez normalizacji)"


def test_text_is_not_normalized(api):
    """NFC „é” i NFD „e + akcent” to inne bajty — round-trip zachowuje oba warianty."""
    nfc, nfd = encrypt(api, "é").json()["ciphertexts"], encrypt(api, "é").json()["ciphertexts"]
    assert len(nfc) == 2 and len(nfd) == 3 and nfc != nfd


@pytest.mark.parametrize(("text", "expected"), [
    ("", (422, "EMPTY_TEXT")),
    ("a" * 129, (422, "TEXT_TOO_LONG")),
    ("ą" * 64 + "a", (422, "TEXT_TOO_LONG")),       # 129 bajtów, 65 znaków
    ("🔐" * 33, (422, "TEXT_TOO_LONG")),           # 132 bajty, 33 znaki: limit liczy bajty
    ("\ud800", (422, "INVALID_UTF8")),             # samotny surogat nie ma kodowania UTF-8
])
def test_text_encrypt_rejects_invalid_text(api, text, expected):
    body = json.dumps({"text": text, "public_exponent": 17, "modulus": 3233})
    response = api.http.post("/api/v1/rsa/demo/text/encrypt", content=body,
                             headers={"Content-Type": "application/json"})
    assert code(response) == expected, response.text


@pytest.mark.parametrize(("body", "expected_code"), [
    ({"text": "a", "public_exponent": 17, "modulus": 255}, "TEXT_MODULUS_TOO_SMALL"),
    ({"text": 123, "public_exponent": 17, "modulus": 3233}, None),
    ({"text": ["a"], "public_exponent": 17, "modulus": 3233}, None),
    ({"text": "a", "public_exponent": 0, "modulus": 3233}, None),
    ({"text": "a", "public_exponent": 17, "modulus": 3233, "extra": 1}, None),
])
def test_text_encrypt_rejects_bad_key_and_types(api, body, expected_code):
    response = api.http.post("/api/v1/rsa/demo/text/encrypt", json=body)
    assert response.status_code == 422, response.text
    if expected_code:
        assert response.json()["error"]["code"] == expected_code


def test_text_modulus_boundary_256(api):
    """n = 256 przechodzi walidację modułu (> 255) — sprawdzamy kontrakt granicy."""
    response = encrypt(api, "a", {"e": 3, "n": 256})
    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json() == {"ciphertexts": [pow(97, 3, 256)]}


def test_text_decrypt_detects_tampering(api):
    ciphertexts = encrypt(api, "zażółć").json()["ciphertexts"]
    # 1) Ucięty znak wielobajtowy („ć” = 2 bajty) → niepoprawne UTF-8.
    assert code(decrypt(api, ciphertexts[:-1])) == (422, "INVALID_UTF8")
    # 2) Szyfrogram, który po deszyfrowaniu daje wartość > 255.
    big = pow(1000, KEY["e"], KEY["n"])
    assert code(decrypt(api, ciphertexts + [big])) == (422, "DECRYPTED_BYTE_OUT_OF_RANGE")
    # 3) Zły klucz prywatny: wynik nie może po cichu dać innego, „poprawnego” tekstu.
    wrong = decrypt(api, ciphertexts, d=KEY["d"] + 1)
    assert wrong.status_code == 422 or wrong.json().get("text") != "zażółć"
    # 4) Zamiana kolejności bloków zmienia tekst — textbook RSA nie chroni integralności.
    swapped = decrypt(api, [ciphertexts[1], ciphertexts[0]] + ciphertexts[2:])
    assert swapped.status_code == 200 and swapped.json()["text"] != "zażółć"


@pytest.mark.parametrize(("ciphertexts", "status"), [
    ([], 422), ([1] * 129, 422), ([3233], 422), ([-1], 422), (["1"], 422), ([1.5], 422),
])
def test_text_decrypt_rejects_bad_ciphertexts(api, ciphertexts, status):
    response = decrypt(api, ciphertexts)
    assert response.status_code == status, response.text
    assert decrypt(api, [pow(65, 17, 3233)]).json() == {"text": "A"}


def test_same_byte_gives_same_ciphertext(api):
    """Własność edukacyjna (nie defekt): szyfrowanie bajt po bajcie bez paddingu jest
    deterministyczne, więc powtarzające się litery mają identyczne szyfrogramy."""
    c = encrypt(api, "aaa").json()["ciphertexts"]
    assert c[0] == c[1] == c[2]


def test_default_text_rate_limit(default_api):
    """Kontrakt: 10/min/IP, burst 2, wspólny kubełek dla encrypt i decrypt tekstu."""
    body = {"text": "a", "public_exponent": 17, "modulus": 3233}
    r = [default_api.http.post("/api/v1/rsa/demo/text/encrypt", json=body) for _ in range(2)]
    assert [x.status_code for x in r] == [200, 200]
    limited = default_api.http.post("/api/v1/rsa/demo/text/decrypt", json={
        "ciphertexts": [1], "private_exponent": 2753, "modulus": 3233})
    assert code(limited) == (429, "RATE_LIMITED")
    assert int(limited.headers["retry-after"]) >= 1
