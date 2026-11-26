"""QA UI #107 / #114: „Losuj parametry” w RSA i DH — Chrome i Firefox, 360/390/768/1440 px.

Wylosowane wartości z pól formularza sprawdzamy niezależnie (Miller–Rabin, rząd
generatora liczony wprost), a potem przechodzimy pełny scenariusz na tych liczbach.
"""

import math

import pytest

from helpers.multi_session_stack import dlog

pytestmark = pytest.mark.e2e

KEYGEN = "form[aria-labelledby=rsa-keygen-title]"
ENCRYPT = "form[aria-labelledby=rsa-encrypt-title]"


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d, r = d // 2, r + 1
    for a in (2, 3, 5, 7, 11, 13, 17):
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def full_order(g: int, p: int) -> bool:
    value, k = g % p, 1
    while value != 1:
        value, k = value * g % p, k + 1
    return k == p - 1


def field(page, name) -> int:
    return int(page.find(f"input[name='{name}']").get_attribute("value"))


def outputs(page, css):
    return page.js("return [...document.querySelector(arguments[0]).querySelectorAll('output')]"
                   ".map(o=>o.innerText)", css)


def test_rsa_draw_and_full_cycle(page, width):
    defaults = (field(page, "p"), field(page, "q"), field(page, "e"))
    page.click(page.button("Losuj parametry", KEYGEN))
    page.wait(lambda: (field(page, "p"), field(page, "q"), field(page, "e")) != defaults,
              message="wylosowane p, q, e w polach")
    p, q, e = field(page, "p"), field(page, "q"), field(page, "e")
    phi = (p - 1) * (q - 1)
    assert is_prime(p) and is_prime(q) and p != q, (p, q)
    assert 257 <= p <= 65_521 and 257 <= q <= 65_521
    assert 1 < e < phi and math.gcd(e, phi) == 1
    assert page.notices(KEYGEN) == [], "losowanie bez błędu"
    # Losowanie tylko wypełnia pola — klucze generuje dopiero „Generuj klucze”.
    assert outputs(page, KEYGEN)[0] == "?"

    page.click(page.button("Generuj klucze", KEYGEN))
    n, d = p * q, pow(e, -1, phi)
    page.wait(lambda: outputs(page, KEYGEN)[0] == str(n), message="n = p·q")
    assert outputs(page, KEYGEN)[:3] == [str(n), str(phi), str(d)]
    page.click(page.button("Użyj klucza publicznego", KEYGEN))
    page.fill("message", "65")
    page.click(page.button("Szyfruj", ENCRYPT))
    page.wait(lambda: page.text(f"{ENCRYPT} .result--ok"), message="szyfrogram")
    assert outputs(page, ENCRYPT) == [str(pow(65, e, n))]
    report = page.layout_report()
    assert report["scrollWidth"] <= report["vw"] and report["overflow"] == [] and report["small"] == []
    page.record("rsa_draw", {"p": p, "q": q, "e": e})
    page.screenshot("rsa-draw")


def test_dh_draw_and_session(page, width):
    page.tab("dh")
    page.click(page.find("input[name=mode][value=normal]"))
    checkbox = page.find(".dh-form input[type=checkbox]")
    if not checkbox.is_selected():
        page.click(checkbox)
    defaults = (field(page, "prime"), field(page, "generator"))
    page.click(page.button("Losuj parametry", ".dh-form"))
    page.wait(lambda: (field(page, "prime"), field(page, "generator")) != defaults,
              message="wylosowane p i g w polach")
    p, g = field(page, "prime"), field(page, "generator")
    assert is_prime(p) and 257 <= p <= 65_521, p
    assert full_order(g, p), f"g={g} nie ma pełnego rzędu modulo {p}"

    page.wait(lambda: page.button("Rozpocznij sesję").is_enabled())
    page.click(page.button("Rozpocznij sesję"))
    page.wait(lambda: "sesja zakończona" in page.session_badges(), timeout=30, message="sesja")
    page.wait(lambda: page.party("alice")["Wspólny sekret"] is not None, timeout=30, message="K")
    alice, bob = page.party("alice"), page.party("bob")
    a = dlog(g, alice["Wartość publiczna"], p)
    assert alice["Wspólny sekret"] == bob["Wspólny sekret"] == pow(bob["Wartość publiczna"], a, p)
    assert alice["Wartość publiczna"] != 1 and bob["Wartość publiczna"] != 1
    report = page.layout_report()
    assert report["scrollWidth"] <= report["vw"] and report["overflow"] == [] and report["small"] == []
    page.record("dh_draw", {"prime": p, "generator": g})
    page.screenshot("dh-draw")


@pytest.mark.widths(390, 1440)
def test_draw_is_keyboard_accessible(page, width):
    from selenium.webdriver.common.keys import Keys

    button = page.button("Losuj parametry", KEYGEN)
    page.js("arguments[0].focus()", button)
    before = field(page, "p")
    page.driver.switch_to.active_element.send_keys(Keys.ENTER)
    page.wait(lambda: field(page, "p") != before, message="Enter uruchamia losowanie")
    # Edycja pola po losowaniu jest możliwa i nie przywraca wylosowanej wartości.
    page.fill("p", "61")
    assert field(page, "p") == 61
