"""QA UI: pełne scenariusze DH (zwykła wymiana) i MITM na rzeczywistych procesach ról.

Wartości z ekranu są sprawdzane matematycznie (logarytm dyskretny dla małego p),
a nie tylko porównywane między sobą — UI nie może pokazać K niezgodnego z A, B, X, Y.
"""

import pytest

from helpers.multi_session_stack import dlog

pytestmark = pytest.mark.e2e

P, G = 23, 5


def run_session(page, mode: str, diagnostics: bool = True):
    page.tab("dh")
    page.click(page.find(f"input[name=mode][value={mode}]"))
    checkbox = page.find(".dh-form input[type=checkbox]")
    if checkbox.is_selected() != diagnostics:
        page.click(checkbox)
    page.wait(lambda: page.button("Rozpocznij sesję").is_enabled(), message="węzły online")
    page.click(page.button("Rozpocznij sesję"))
    page.wait(lambda: "sesja zakończona" in page.session_badges(), timeout=30, message="sesja zakończona")
    if diagnostics:
        keys = ["Wspólny sekret"]
        page.wait(lambda: all(page.party(r)[k] is not None for r in ("alice", "bob") for k in keys),
                  timeout=30, message="K z diagnostyki")
        if mode == "mitm":
            page.wait(lambda: all(page.party("mallory")[k] is not None
                                  for k in ("Sekret z Alice", "Sekret z Bobem")),
                      timeout=30, message="K Mallory")


def reset(page):
    page.click(page.button("Reset"))
    page.wait(lambda: "Rozpocznij sesję" in page.text(".dh-placeholder"), message="reset")


def log_count(page) -> int:
    return int(page.text(".dh-log-count").strip("()"))


def test_dh_normal_full_scenario(page, width):
    run_session(page, "normal")
    alice, bob = page.party("alice"), page.party("bob")
    a = dlog(G, alice["Wartość publiczna"], P)
    b = dlog(G, bob["Wartość publiczna"], P)
    assert alice["Otrzymana wartość"] == bob["Wartość publiczna"]
    assert bob["Otrzymana wartość"] == alice["Wartość publiczna"]
    assert alice["Wspólny sekret"] == pow(bob["Wartość publiczna"], a, P)
    assert bob["Wspólny sekret"] == pow(alice["Wartość publiczna"], b, P) == alice["Wspólny sekret"]
    assert page.session_badges() == ["Zwykła wymiana", "sesja zakończona"]
    assert "Sekrety zgodne" in page.text(".dh-result")
    assert log_count(page) == 7
    assert page.text(".dh-channel-label") == "koordynator"
    # Sekrety prywatne nigdy nie trafiają do przeglądarki.
    assert alice["Klucz prywatny"] is None and bob["Klucz prywatny"] is None
    report = page.layout_report()
    assert report["scrollWidth"] <= report["vw"] and report["overflow"] == []
    page.record("dh_normal", {"alice": alice, "bob": bob, "layout": report})
    page.screenshot("dh-normal-done")

    reset(page)
    assert page.js("return Object.keys(sessionStorage).filter(k=>k.startsWith('radh.dh'))") == []


def test_dh_mitm_full_scenario(page, width):
    run_session(page, "mitm")
    alice, bob, mallory = page.party("alice"), page.party("bob"), page.party("mallory")
    a = dlog(G, alice["Wartość publiczna"], P)
    b = dlog(G, bob["Wartość publiczna"], P)
    x = dlog(G, mallory["Podstawiona Alice"], P)
    y = dlog(G, mallory["Podstawiona Bobowi"], P)
    assert mallory["Przechwycona od Alice"] == alice["Wartość publiczna"]
    assert mallory["Przechwycona od Boba"] == bob["Wartość publiczna"]
    assert alice["Otrzymana „od Boba”"] == mallory["Podstawiona Alice"]
    assert bob["Otrzymana „od Alice”"] == mallory["Podstawiona Bobowi"]
    assert alice["Wspólny sekret"] == pow(mallory["Podstawiona Alice"], a, P) == mallory["Sekret z Alice"]
    assert bob["Wspólny sekret"] == pow(mallory["Podstawiona Bobowi"], b, P) == mallory["Sekret z Bobem"]
    assert mallory["Sekret z Alice"] == pow(alice["Wartość publiczna"], x, P)
    assert mallory["Sekret z Bobem"] == pow(bob["Wartość publiczna"], y, P)
    assert page.session_badges() == ["Atak MITM", "sesja zakończona"]
    verdict = "Sekrety zgodne" if alice["Wspólny sekret"] == bob["Wspólny sekret"] else "Sekrety niezgodne"
    assert verdict in page.text(".dh-result")
    assert "Dlaczego atak się udaje" in page.text(".dh-explain")
    assert "podmieniła 2/2" in page.text(".dh-party--mallory .dh-party-header")
    assert log_count(page) == 9
    report = page.layout_report()
    assert report["scrollWidth"] <= report["vw"] and report["overflow"] == []
    page.record("dh_mitm", {"alice": alice, "bob": bob, "mallory": mallory, "layout": report})
    page.screenshot("dh-mitm-done")


@pytest.mark.widths(390, 1440)
def test_dh_without_diagnostics_hides_keys(page, width):
    run_session(page, "mitm", diagnostics=False)
    for role in ("alice", "bob"):
        assert page.party(role)["Wspólny sekret"] is None
        assert "obliczony, zna go tylko proces" in page.text(f".dh-party--{role}")
    assert all(page.party("mallory")[k] is None for k in ("Sekret z Alice", "Sekret z Bobem"))


@pytest.mark.widths(390, 1440)
def test_dh_comparison_and_event_log(page, width):
    run_session(page, "normal")
    reset(page)
    run_session(page, "mitm")
    page.js("document.querySelectorAll('details').forEach(d=>d.open=true)")
    compare = page.text(".dh-compare")
    assert "Zwykła wymiana" in compare and "Atak MITM" in compare
    assert "Sekrety Alice i Boba" in compare
    rows = page.js("return [...document.querySelectorAll('.dh-log tbody tr')].map(r=>r.innerText)")
    assert len(rows) == 9
    assert any("Mallory jako Alice" in row for row in rows)
    assert any("zamiast" in row for row in rows), "podmiana pokazuje oryginalną wartość"
    report = page.layout_report()
    assert report["scrollWidth"] <= report["vw"], "tabele przewijają się w swoim kontenerze, nie cała strona"
    page.screenshot("dh-compare-log")


@pytest.mark.widths(1440)
def test_dh_reload_restores_own_session(page, width):
    run_session(page, "normal")
    before = page.party("alice")
    page.reload()
    page.tab("dh")
    page.wait(lambda: "sesja zakończona" in page.session_badges(), message="odtworzenie po reload")
    assert page.party("alice")["Wartość publiczna"] == before["Wartość publiczna"]
