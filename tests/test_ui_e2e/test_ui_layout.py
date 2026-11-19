"""QA UI: responsywność 360/390/768/1440 px w Chrome i Firefox (bez przewijania poziomego,
cele dotykowe ≥ 24 px wg WCAG 2.5.8, układ paneli zależny od szerokości)."""

import pytest

pytestmark = pytest.mark.e2e


def boxes(page, css):
    return page.js("return [...document.querySelectorAll(arguments[0])].filter(e=>e.offsetParent!==null)"
                   ".map(e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right}})", css)


def assert_layout_ok(page, label):
    report = page.layout_report()
    page.record("layout", {"view": label, **report})
    assert report["scrollWidth"] <= report["vw"], f"przewijanie poziome: {report}"
    assert report["overflow"] == [], f"elementy poza ekranem: {report['overflow']}"
    assert report["small"] == [], f"cele dotykowe < 24 px: {report['small']}"


def test_rsa_layout(page, width):
    assert_layout_ok(page, "rsa")
    panels = boxes(page, "#view-rsa .rsa-layout > .panel")
    assert len(panels) == 2
    if width < 768:
        assert panels[1]["top"] >= panels[0]["bottom"] - 1, "na telefonie panele RSA jeden pod drugim"
    if width >= 1440:
        assert abs(panels[0]["top"] - panels[1]["top"]) < 2, "na desktopie panele RSA obok siebie"
    tabs = boxes(page, "[role=tab]")
    assert abs(tabs[0]["top"] - tabs[1]["top"]) < 2, "zakładki w jednym wierszu"
    page.screenshot("rsa")


@pytest.mark.parametrize("mode", ["normal", "mitm"])
def test_dh_idle_layout(page, width, mode):
    page.tab("dh")
    page.click(page.find(f"input[name=mode][value={mode}]"))
    page.wait(lambda: (page.find(".dh-party--mallory") is not None) if mode == "mitm" else True)
    assert_layout_ok(page, f"dh-{mode}-idle")
    parties = boxes(page, ".dh-parties > *")
    assert len(parties) == 3
    form = boxes(page, "#view-dh aside.panel")[0]
    scene = boxes(page, "#view-dh .dh-scene")[0]
    if width < 768:
        assert all(b["top"] >= a["bottom"] - 1 for a, b in zip(parties, parties[1:])), \
            "na telefonie Alice/środek/Bob jeden pod drugim"
        assert form["bottom"] <= scene["top"] + 1, "na telefonie formularz nad przebiegiem sesji"
    if width >= 1440:
        assert len({round(p["top"]) for p in parties}) == 1, "na desktopie Alice/środek/Bob w jednym rzędzie"
        assert form["left"] >= scene["right"] - 1, "na desktopie formularz obok przebiegu"
    page.screenshot(f"dh-{mode}-idle")
