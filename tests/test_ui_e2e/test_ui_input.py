"""QA UI: obsługa klawiaturą (zakładki ARIA, kolejność Tab, widoczny fokus, scenariusze bez myszy)
i dotykiem (W3C pointer type touch na szerokościach telefonu)."""

import pytest

Keys = pytest.importorskip("selenium.webdriver.common.keys").Keys

pytestmark = pytest.mark.e2e


def active(page) -> str:
    return page.js("const e=document.activeElement;return e.id||e.name||e.innerText.trim().slice(0,30)")


def press(page, *keys):
    page.driver.switch_to.active_element.send_keys(*keys)


def focus_visible(page) -> bool:
    return page.js("const s=getComputedStyle(document.activeElement);"
                   "return (s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>=2)||s.boxShadow!=='none'")


@pytest.mark.widths(768, 1440)
def test_keyboard_tabs_order_and_focus(page, width):
    page.find("#tab-rsa").click()
    assert active(page) == "tab-rsa"
    press(page, Keys.ARROW_RIGHT)
    assert active(page) == "tab-dh" and page.find("#tab-dh").get_attribute("aria-selected") == "true"
    assert page.find("#view-dh").is_displayed() and not page.find("#view-rsa").is_displayed()
    press(page, Keys.HOME)
    assert active(page) == "tab-rsa" and page.find("#view-rsa").is_displayed()
    press(page, Keys.END)
    assert active(page) == "tab-dh"
    press(page, Keys.ARROW_LEFT)
    assert active(page) == "tab-rsa"

    # Tab: tylko aktywna zakładka, potem kontrolki widocznego panelu; każdy fokus widoczny.
    order = []
    for _ in range(10):
        press(page, Keys.TAB)
        assert focus_visible(page), f"niewidoczny fokus na {active(page)}"
        order.append(active(page))
    assert order == ["p", "q", "e", "Losuj parametry", "Generuj klucze", "message", "public_exponent",
                     "modulus", "Szyfruj", "Repozytorium na GitHubie"]
    assert "tab-dh" not in order and "prime" not in order, "ukryty panel i nieaktywna zakładka poza kolejnością"
    page.record("keyboard_order", {"order": order})


@pytest.mark.widths(768, 1440)
def test_keyboard_only_rsa_and_mitm(page, width):
    page.find("input[name=p]").click()
    press(page, Keys.ENTER)
    page.wait(lambda: "3233" in page.text("form[aria-labelledby=rsa-keygen-title] .rsa-keys"),
              message="Enter w polu generuje klucze")
    page.find("input[name=e]").click()
    press(page, Keys.TAB, Keys.TAB, Keys.TAB)  # Losuj parametry → Generuj klucze → Użyj klucza publicznego
    assert active(page) == "Użyj klucza publicznego"
    press(page, Keys.ENTER)
    press(page, Keys.TAB)
    press(page, "65", Keys.ENTER)
    page.wait(lambda: "2790" in page.text("form[aria-labelledby=rsa-encrypt-title]"), message="szyfrogram")

    page.find("#tab-rsa").click()
    press(page, Keys.ARROW_RIGHT)
    radio = page.find("input[name=mode][value=normal]")
    page.js("arguments[0].focus()", radio)
    press(page, Keys.ARROW_DOWN)
    assert page.find("input[name=mode][value=mitm]").is_selected(), "strzałki zmieniają scenariusz"
    page.js("arguments[0].focus()", page.find(".dh-form input[type=checkbox]"))
    press(page, Keys.SPACE)
    assert page.find(".dh-form input[type=checkbox]").is_selected()
    page.wait(lambda: page.button("Rozpocznij sesję").is_enabled())
    page.js("arguments[0].focus()", page.find("input[name=generator]"))
    press(page, Keys.ENTER)
    page.wait(lambda: "sesja zakończona" in page.js(
        "return [...document.querySelectorAll('.dh-shared .badge')].map(e=>e.innerText)"),
        timeout=30, message="MITM z klawiatury")
    page.js("arguments[0].focus()", page.find(".dh-log summary"))
    press(page, Keys.ENTER)
    assert page.js("return document.querySelector('.dh-log details').open")


@pytest.mark.widths(360, 390)
def test_touch_rsa_and_dh(page, width):
    if page.browser == "chrome":
        assert page.js("return navigator.maxTouchPoints") > 0
    assert page.js("return document.documentElement.clientWidth") == width
    page.tap(page.button("Generuj klucze"))
    page.wait(lambda: "3233" in page.text(".rsa-keys"), message="tap: generowanie")
    page.tap(page.button("Użyj klucza publicznego"))
    page.tap(page.find("#tab-dh"))
    page.wait(lambda: page.find("#view-dh").is_displayed(), message="tap: zakładka DH")
    page.tap(page.find("input[name=mode][value=mitm]").find_element("xpath", ".."))
    assert page.find("input[name=mode][value=mitm]").is_selected(), "tap w etykietę wybiera scenariusz"
    page.wait(lambda: page.button("Rozpocznij sesję").is_enabled())
    page.tap(page.button("Rozpocznij sesję"))
    page.wait(lambda: "sesja zakończona" in page.js(
        "return [...document.querySelectorAll('.dh-shared .badge')].map(e=>e.innerText)"),
        timeout=30, message="tap: sesja MITM")
    # Po starcie na telefonie przebieg sesji jest widoczny (formularz stoi nad nim).
    top = page.js("return document.querySelector('.dh-scene').getBoundingClientRect().top")
    assert top < page.js("return innerHeight"), "przebieg sesji przewinięty do widoku"
    page.tap(page.find(".dh-log summary"))
    assert page.js("return document.querySelector('.dh-log details').open")
    page.tap(page.button("Reset"))
    page.wait(lambda: page.js("return document.querySelectorAll('.dh-shared').length") == 0, message="tap: reset")
    page.record("touch", {"ok": True})