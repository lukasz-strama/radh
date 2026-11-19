"""QA UI: pełny scenariusz RSA (generowanie → użycie klucza → szyfrowanie) oraz błędy formularzy."""

import pytest

pytestmark = pytest.mark.e2e

KEYGEN = "form[aria-labelledby=rsa-keygen-title]"
ENCRYPT = "form[aria-labelledby=rsa-encrypt-title]"


def outputs(page, css):
    return page.js("return [...document.querySelector(arguments[0]).querySelectorAll('output')].map(o=>o.innerText)", css)


def test_rsa_full_scenario(page):
    use_key = page.button("Użyj klucza publicznego", KEYGEN)
    assert not use_key.is_enabled(), "przed wygenerowaniem kluczy przycisk jest nieaktywny"
    assert outputs(page, KEYGEN)[:3] == ["?", "?", "?"]

    page.click(page.button("Generuj klucze", KEYGEN))
    page.wait(lambda: outputs(page, KEYGEN)[0] != "?", message="wynik generowania")
    assert outputs(page, KEYGEN) == ["3233", "3120", "2753", "(3233, 17)", "(3233, 2753)"]
    assert any("32-bitowe" in text for text in page.notices(KEYGEN)), "ostrzeżenie o kluczach edukacyjnych"

    page.click(page.button("Użyj klucza publicznego", KEYGEN))
    assert page.find("input[name=public_exponent]").get_attribute("value") == "17"
    assert page.find("input[name=modulus]").get_attribute("value") == "3233"

    page.fill("message", "65")
    page.click(page.button("Szyfruj", ENCRYPT))
    page.wait(lambda: page.text(f"{ENCRYPT} .result--ok"), message="szyfrogram")
    assert outputs(page, ENCRYPT) == ["2790"]
    assert "c = 6517 mod 3233 = 2790" in page.text(f"{ENCRYPT} .result--ok").replace("\n", " ")
    page.record("rsa_full", {"n": 3233, "phi": 3120, "d": 2753, "c": 2790})
    page.screenshot("rsa-done")

    # Nowa para kluczy usuwa nieaktualny szyfrogram dopiero po „Użyj klucza publicznego”.
    page.fill("p", "11")
    page.fill("q", "13")
    page.fill("e", "7")
    page.click(page.button("Generuj klucze", KEYGEN))
    page.wait(lambda: outputs(page, KEYGEN)[0] == "143", message="druga para kluczy")
    assert outputs(page, KEYGEN)[:3] == ["143", "120", "103"]
    page.click(page.button("Użyj klucza publicznego", KEYGEN))
    assert page.text(f"{ENCRYPT} .result--ok") == ""


def test_rsa_form_errors(page):
    page.click(page.button("Szyfruj", ENCRYPT))
    for name in ("message", "public_exponent", "modulus"):
        assert page.field_error(name) == "To pole jest wymagane."
    # Fokus/klawiatura: błędne pola są oznaczone dla czytników ekranu.
    page.fill("message", "4000")
    page.fill("public_exponent", "17")
    page.fill("modulus", "3233")
    page.click(page.button("Szyfruj", ENCRYPT))
    assert page.field_error("message") == "Wiadomość m musi być mniejsza od modułu n."
    assert page.field_error("modulus") is None
    page.fill("message", "4294967296")
    page.click(page.button("Szyfruj", ENCRYPT))
    assert "Maksymalna wartość" in page.field_error("message")
    page.fill("message", "-5")
    page.click(page.button("Szyfruj", ENCRYPT))
    assert page.field_error("message")

    # Błędy z backendu (CryptoCore) jako komunikat w panelu, role=alert.
    page.fill("p", "60")
    page.click(page.button("Generuj klucze", KEYGEN))
    page.wait(lambda: page.notices(KEYGEN), message="komunikat backendu")
    assert page.notices(KEYGEN) == ["Parametr p musi być liczbą pierwszą."]
    assert page.js(f"return document.querySelector('{KEYGEN} .notice--error').getAttribute('role')") == "alert"
    page.fill("p", "61")
    page.fill("e", "60")
    page.click(page.button("Generuj klucze", KEYGEN))
    page.wait(lambda: "względnie pierwsze" in " ".join(page.notices(KEYGEN)), message="e i phi")
    assert not page.button("Użyj klucza publicznego", KEYGEN).is_enabled()
    page.record("rsa_errors", {"ok": True})
    page.screenshot("rsa-errors")
