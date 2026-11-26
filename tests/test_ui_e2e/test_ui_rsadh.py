"""QA UI #107 / #117: zakładka „RSA + DH” — podpisana wymiana DH (normalna i MITM).

Liczby z ekranu sprawdzamy niezależnie od aplikacji:
* transkrypt składamy sami (AUTHENTICATED_DH.md) i liczymy ``hashlib.sha256``,
* podpis weryfikujemy ``pow(s, e, n) == int(skrót) % n``,
* wspólny sekret K liczymy z logarytmu dyskretnego (małe p).
"""

import hashlib
import json

import pytest

from helpers.multi_session_stack import dlog

pytestmark = pytest.mark.e2e

VIEW = "#view-rsadh"
P, G = 23, 5


def start(page, mode: str, diagnostics: bool = True):
    page.tab("rsadh")
    page.click(page.find(f"{VIEW} input[name=mode][value={mode}]"))
    box = page.find(f"{VIEW} .dh-form input[type=checkbox]")
    if box.is_selected() != diagnostics:
        page.click(box)
    page.wait(lambda: page.button("Rozpocznij sesję", VIEW).is_enabled(), message="węzły online")
    page.click(page.button("Rozpocznij sesję", VIEW))


def auth_panel(page) -> dict:
    """Panel „Podpisy RSA”: rola → {n, e, s, hash, badge}."""
    return page.js("""
        const out={};
        const parties=document.querySelectorAll(arguments[0]+' .dh-auth-party');
        ['alice','bob'].forEach((role,i)=>{
          const dd=[...parties[i].querySelectorAll('dd')].map(d=>d.innerText.trim());
          const m=dd[0].match(/\\((\\d+),\\s*(\\d+)\\)/);
          out[role]={n:m?+m[1]:null,e:m?+m[2]:null,s:dd[1]==='?'?null:+dd[1],hash:dd[2],badge:dd[3]};
        });
        return out;""", VIEW)


def credential(page) -> dict:
    return json.loads(page.js("return sessionStorage.getItem('radh.dh.v2.authenticated.session')"))


def transcript_hash(cred, signer, alice_public, bob_public, keys) -> str:
    values = [("session_id", cred["id"]), ("backend_epoch", cred["epoch"]), ("signer", signer),
              ("prime", P), ("generator", G), ("alice_public", alice_public), ("bob_public", bob_public),
              ("alice_rsa_n", keys["alice"]["n"]), ("alice_rsa_e", keys["alice"]["e"]),
              ("bob_rsa_n", keys["bob"]["n"]), ("bob_rsa_e", keys["bob"]["e"])]
    lines = ["RADH-SIGNED-DH-V1"] + [f"{k}={v}" for k, v in values]
    return hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()


def test_rsadh_normal_signatures_verified(page, width):
    start(page, "normal")
    page.wait(lambda: "sesja zakończona" in page.session_badges(), timeout=40, message="sesja zakończona")
    page.wait(lambda: page.text(f"{VIEW} .dh-auth .result--ok"), timeout=30, message="obie weryfikacje")
    auth = auth_panel(page)
    alice, bob = page.party("alice"), page.party("bob")
    A, B = alice["Wartość publiczna"], bob["Wartość publiczna"]
    cred = credential(page)
    for role in ("alice", "bob"):
        k = auth[role]
        expected = transcript_hash(cred, role, A, B, auth)
        assert k["hash"] == expected, f"skrót transkryptu {role} zgodny z niezależnym SHA-256"
        assert pow(k["s"], k["e"], k["n"]) == int(expected, 16) % k["n"], f"podpis {role} poprawny"
        assert k["badge"] == "podpis poprawny"
    assert auth["alice"]["n"] != auth["bob"]["n"], "każda strona ma własny klucz RSA"
    a, b = dlog(G, A, P), dlog(G, B, P)
    page.wait(lambda: page.party("alice")["Wspólny sekret"] is not None, timeout=30, message="K")
    assert page.party("alice")["Wspólny sekret"] == pow(B, a, P) == page.party("bob")["Wspólny sekret"] == pow(A, b, P)
    assert "Jak podpisy chronią wymianę" in page.text(VIEW)
    assert page.session_badges()[0] == "Podpisana wymiana"
    report = page.layout_report()
    assert report["scrollWidth"] <= report["vw"] and report["overflow"] == []
    page.record("rsadh_normal", {"auth": auth, "A": A, "B": B})
    page.screenshot("rsadh-normal")


def test_rsadh_mitm_rejected_and_key_hidden(page, width):
    start(page, "mitm")
    page.wait(lambda: page.text(f"{VIEW} .dh-auth .result--error"), timeout=40, message="odrzucenie podpisu")
    auth = auth_panel(page)
    assert "podpis odrzucony" in (auth["alice"]["badge"], auth["bob"]["badge"])
    reason = page.text(f"{VIEW} .dh-auth .result--error")
    assert "różni się" in reason and "nie został zaakceptowany" in reason
    assert any("Podpis odrzucony" in n for n in page.notices(VIEW))
    # Mimo włączonej diagnostyki K nie jest pokazywany po odrzuceniu.
    assert page.party("alice")["Wspólny sekret"] is None and page.party("bob")["Wspólny sekret"] is None
    assert "Obie strony zweryfikowały" not in page.text(VIEW)
    assert page.session_badges()[0] == "Podpisana wymiana + MITM"
    report = page.layout_report()
    assert report["scrollWidth"] <= report["vw"] and report["overflow"] == []
    page.screenshot("rsadh-mitm-rejected")

    page.click(page.button("Reset", VIEW))
    page.wait(lambda: not page.js("return sessionStorage.getItem('radh.dh.v2.authenticated.session')"),
              message="reset czyści sesję")
    page.wait(lambda: page.button("Rozpocznij sesję", VIEW).is_enabled(), message="można zacząć od nowa")


@pytest.mark.widths(1440)
def test_rsadh_tab_isolated_from_classic_dh(page, width):
    """Sesja w zakładce DH i w RSA + DH to dwie niezależne sesje z osobnymi danymi."""
    page.tab("dh")
    page.click(page.find("#view-dh input[name=mode][value=normal]"))
    page.wait(lambda: page.button("Rozpocznij sesję", "#view-dh").is_enabled(), message="węzły online")
    page.click(page.button("Rozpocznij sesję", "#view-dh"))
    page.wait(lambda: "sesja zakończona" in page.session_badges(), timeout=40, message="zwykły DH")
    classic = json.loads(page.js("return sessionStorage.getItem('radh.dh.v2.session')"))
    start(page, "normal")
    page.wait(lambda: "sesja zakończona" in page.session_badges(), timeout=40, message="podpisany DH")
    assert credential(page)["id"] != classic["id"]
    page.tab("dh")
    assert page.session_badges()[0] == "Zwykła wymiana", "zakładka DH zachowuje własną sesję"