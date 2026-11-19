"""QA UI: wykryte defekty jako testy ``xfail(strict=True)``.

Każdy test opisuje oczekiwane zachowanie. Dopóki defekt istnieje, test „oczekiwanie
nie przechodzi” (XFAIL); po naprawie stanie się XPASS i — przez ``strict`` —
zatrzyma CI, żeby zdjąć oznaczenie i zamknąć bug issue. Kroki reprodukcji: docstring.
"""

import pytest

pytestmark = pytest.mark.e2e


def run_normal(page):
    page.tab("dh")
    page.wait(lambda: page.button("Rozpocznij sesję").is_enabled())
    page.click(page.button("Rozpocznij sesję"))
    page.wait(lambda: "sesja zakończona" in page.session_badges(), timeout=30, message="sesja zakończona")


@pytest.mark.xfail(strict=True, reason="BUG-UI-01: checkbox diagnostyki ma 44 px i stoi nad etykietą")
def test_bug_ui_01_diagnostics_checkbox_layout(page, width):
    """1. Otwórz zakładkę Diffie–Hellman. 2. Spójrz na „Pokaż edukacyjnie wspólne sekrety sesji”.
    Oczekiwane: zwykły checkbox (≈20 px) w jednym wierszu z etykietą, jak radio „Scenariusz”.
    Faktycznie: reguła `.panel input:not([type='radio'])` (App.css) nadaje mu min-height 44 px,
    a `.panel label` układa go w kolumnie — duży kwadrat wyśrodkowany nad tekstem."""
    page.tab("dh")
    box = page.js("""const c=document.querySelector('.dh-form input[type=checkbox]');
        const r=c.getBoundingClientRect(); const l=c.closest('label');
        const t=document.createRange(); t.selectNodeContents(l); const lr=[...t.getClientRects()].pop();
        return {h:r.height, w:r.width, cy:r.top+r.height/2, textBottom:lr.bottom, textTop:lr.top}""")
    page.record("bug_ui_01", box)
    assert box["h"] <= 24 and box["w"] <= 24, box
    assert box["textTop"] <= box["cy"] <= box["textBottom"], "checkbox w jednym wierszu z tekstem"


@pytest.mark.widths(390, 1440)
@pytest.mark.xfail(strict=True, reason="BUG-UI-02: odrzucona próba tworzenia blokuje kolejną do Reset")
def test_bug_ui_02_rejected_create_blocks_next_attempt(page, width):
    """1. DH, wpisz p = 24 (nie jest pierwsza — sprawdza ją backend), kliknij „Rozpocznij sesję”.
    2. Pojawia się „Niepoprawne parametry sesji DH.” — popraw p na 23 i kliknij ponownie.
    Oczekiwane: nowa sesja startuje. Faktycznie: „Poprzednia próba utworzenia wymaga porzucenia.
    Kliknij Reset…”. Przyczyna: `startDhSession` (api.ts) zapisuje `radh.dh.v2.creation` przed
    POST i nie usuwa go po ostatecznym odrzuceniu 4xx (422/409), więc inne parametry = konflikt."""
    page.tab("dh")
    page.fill("prime", "24")
    page.click(page.button("Rozpocznij sesję"))
    page.wait(lambda: page.notices(".dh-form"), message="odrzucenie p=24")
    page.fill("prime", "23")
    page.click(page.button("Rozpocznij sesję"))
    page.wait(lambda: page.session_badges() or page.notices(".dh-form"), timeout=20,
              message="wynik drugiej próby")
    page.record("bug_ui_02", {"notices": page.notices(".dh-form"), "badges": page.session_badges()})
    assert not any("wymaga porzucenia" in n for n in page.notices(".dh-form")), page.notices(".dh-form")
    page.wait(lambda: "sesja zakończona" in page.session_badges(), timeout=30, message="sesja po poprawce p")


@pytest.mark.widths(390, 1440)
@pytest.mark.xfail(strict=True, reason="BUG-UI-03: „Rozpocznij sesję” po zakończonej sesji czyści wynik")
def test_bug_ui_03_start_after_completed_hides_result(page, width):
    """1. DH, uruchom zwykłą wymianę i poczekaj na „sesja zakończona”.
    2. Bez Reset kliknij ponownie „Rozpocznij sesję” (przycisk jest aktywny).
    Oczekiwane: przycisk nieaktywny z podpowiedzią albo wynik zostaje na ekranie z komunikatem.
    Faktycznie: przebieg i wynik znikają (placeholder „Podaj parametry…”), pojawia się
    „Najpierw usuń własną poprzednią sesję przyciskiem Reset.”; po odświeżeniu strony sesja wraca."""
    run_normal(page)
    enabled = page.button("Rozpocznij sesję").is_enabled()
    page.click(page.button("Rozpocznij sesję"))
    page.wait(lambda: page.notices(".dh-form") or page.session_badges(), message="reakcja na drugi start")
    page.record("bug_ui_03", {"enabled": enabled, "badges": page.session_badges(),
                              "notices": page.notices(".dh-form")})
    assert not enabled or "sesja zakończona" in page.session_badges()
