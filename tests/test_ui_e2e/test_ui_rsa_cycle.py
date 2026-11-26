"""QA UI #107 / #100: pełny cykl RSA (liczba i tekst UTF-8) — Chrome i Firefox, 4 szerokości.

Szyfrogramy z ekranu sprawdzamy niezależnie: ``pow(bajt, e, n)`` dla każdego bajtu
UTF-8. Tekst ustawiamy przez natywny setter + zdarzenie ``input`` (ChromeDriver nie
wpisuje znaków spoza BMP, np. emoji, przez ``send_keys``).
"""

import pytest

pytestmark = pytest.mark.e2e

KEYGEN = "form[aria-labelledby=rsa-keygen-title]"
ENCRYPT = "form[aria-labelledby=rsa-encrypt-title]"
DECRYPT = "form[aria-labelledby=rsa-decrypt-title]"
N, E, D = 3233, 17, 2753          # domyślny klucz panelu (p=61, q=53, e=17)


def set_value(page, css, value):
    page.js("""
        const el = document.querySelector(arguments[0]);
        el.scrollIntoView({block: 'center'});
        const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, arguments[1]);
        el.dispatchEvent(new Event('input', {bubbles: true}));""", css, value)


def value(page, css):
    return page.js("return document.querySelector(arguments[0]).value", css)


def error_of(page, css):
    return page.js("""
        const el = document.querySelector(arguments[0]);
        if (el.getAttribute('aria-invalid') !== 'true') return null;
        return el.getAttribute('aria-describedby').split(' ')
          .map(id => document.getElementById(id)).filter(Boolean)
          .map(e => e.innerText).join(' | ');""", css)


def use_default_keys(page):
    page.click(page.button("Generuj klucze", KEYGEN))
    page.wait(lambda: "3233" in page.text(f"{KEYGEN} .rsa-keys"), message="klucze")
    page.click(page.button("Użyj klucza publicznego", KEYGEN))
    page.click(page.button("Użyj klucza prywatnego", KEYGEN))
    assert value(page, f"{DECRYPT} input[name=private_exponent]") == str(D)
    assert value(page, f"{DECRYPT} input[name=private_modulus]") == str(N)


def text_mode(page):
    page.click(page.find("input[name=rsa-mode][value=text]"))
    page.wait(lambda: page.js("return !!document.querySelector('textarea[name=text]')"))


def byte_table(page, form):
    """Wiersze tabeli bajtów: [[znak, bajty, szyfrogramy], …] jako tekst."""
    return page.js("""
        const rows = [...document.querySelector(arguments[0]).querySelectorAll('.rsa-bytes tr')];
        return rows.map(r => [...r.children].map(c => c.innerText.trim()));""", form)


TEXT = "Zażółć gęślą jaźń 🔐"


def test_text_cycle_utf8(page, width):
    use_default_keys(page)
    text_mode(page)
    set_value(page, "textarea[name=text]", TEXT)
    raw = TEXT.encode("utf-8")
    assert f"{len(raw)} / 128" in page.text(ENCRYPT), "licznik bajtów UTF-8"
    page.click(page.button("Szyfruj", ENCRYPT))
    page.wait(lambda: page.text(f"{ENCRYPT} .result--ok"), message="szyfrogramy")
    expected = [pow(b, E, N) for b in raw]
    # Szyfrogramy trafiają od razu do pola deszyfrowania — i zgadzają się z referencją.
    numbers = [int(x) for x in value(page, "textarea[name=ciphertexts]").replace(",", " ").split()]
    assert numbers == expected
    table = " ".join(" ".join(row) for row in byte_table(page, ENCRYPT))
    assert "197" in table and "188" in table, "„ż” = 197 188 widoczne w tabeli bajtów"
    assert f"{len(raw)} bajt" in page.text(f"{ENCRYPT} .result--ok")

    page.click(page.button("Odszyfruj", DECRYPT))
    page.wait(lambda: page.text(f"{DECRYPT} .result--ok"), message="odzyskany tekst")
    assert page.js(f"return document.querySelector('{DECRYPT} .result--ok output').innerText") == TEXT
    report = page.layout_report()
    assert report["scrollWidth"] <= report["vw"], "tabela bajtów przewija się w swoim kontenerze"
    assert report["small"] == []
    page.record("rsa_text_cycle", {"bytes": len(raw)})
    page.screenshot("rsa-text-cycle")


@pytest.mark.widths(390, 1440)
def test_number_cycle_and_padding_warning(page, width):
    use_default_keys(page)
    page.fill("message", "65")
    page.click(page.button("Szyfruj", ENCRYPT))
    page.wait(lambda: page.text(f"{ENCRYPT} .result--ok"), message="szyfrogram")
    assert value(page, f"{DECRYPT} input[name=ciphertext]") == "2790"
    page.click(page.button("Odszyfruj", DECRYPT))
    page.wait(lambda: page.text(f"{DECRYPT} .result--ok"), message="wiadomość")
    assert page.js(f"return document.querySelector('{DECRYPT} .result--ok output').innerText") == "65"
    warning = page.text(".rsa-cycle .notice--warning")
    assert "bez paddingu" in warning and "HELLO" in warning


@pytest.mark.widths(390, 1440)
def test_private_key_not_persisted(page, width):
    use_default_keys(page)
    stored = page.js("return JSON.stringify({...sessionStorage}) + JSON.stringify({...localStorage}) + location.href")
    assert str(D) not in stored, "klucz prywatny nie może trafić do storage ani adresu"


@pytest.mark.widths(390, 1440)
def test_text_form_errors(page, width):
    use_default_keys(page)
    text_mode(page)
    cases = [("", "textarea[name=text]"), ("a" * 129, "textarea[name=text]"), ("ą" * 65, "textarea[name=text]")]
    for text, css in cases:
        set_value(page, css, text)
        page.click(page.button("Szyfruj", ENCRYPT))
        assert page.wait(lambda: error_of(page, css), message=f"błąd dla {len(text.encode())} B")
        assert not page.text(f"{ENCRYPT} .result--ok")
    set_value(page, "textarea[name=text]", "abc")
    set_value(page, f"{ENCRYPT} input[name=modulus]", "255")
    page.click(page.button("Szyfruj", ENCRYPT))
    assert page.wait(lambda: error_of(page, f"{ENCRYPT} input[name=modulus]"), message="n ≤ 255")
    # Deszyfrowanie: c ≥ n z numerem błędnego szyfrogramu.
    set_value(page, "textarea[name=ciphertexts]", "1, 2, 3233")
    page.click(page.button("Odszyfruj", DECRYPT))
    message = page.wait(lambda: error_of(page, "textarea[name=ciphertexts]"), message="c ≥ n")
    assert "3" in message, f"komunikat wskazuje numer szyfrogramu: {message}"
    page.screenshot("rsa-text-errors")


@pytest.mark.widths(390, 1440)
def test_tampered_ciphertexts_show_backend_error(page, width):
    use_default_keys(page)
    text_mode(page)
    set_value(page, "textarea[name=text]", "żółw")
    page.click(page.button("Szyfruj", ENCRYPT))
    page.wait(lambda: page.text(f"{ENCRYPT} .result--ok"))
    numbers = value(page, "textarea[name=ciphertexts]").replace(",", " ").split()
    set_value(page, "textarea[name=ciphertexts]", " ".join(numbers[:-2]) + " " + numbers[-1])  # ucięte „ł”
    page.click(page.button("Odszyfruj", DECRYPT))
    page.wait(lambda: page.notices(DECRYPT), message="komunikat o niepoprawnym UTF-8")
    assert "UTF-8" in " ".join(page.notices(DECRYPT))
    assert not page.text(f"{DECRYPT} .result--ok"), "brak „odzyskanego” tekstu po błędzie"