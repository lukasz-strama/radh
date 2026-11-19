"""QA UI: prezentacja błędów DH — walidacja pól, odrzucenie przez backend, niedostępny
węzeł, restart backendu w trakcie sesji."""

import pytest

from helpers.multi_session_stack import resume

pytestmark = pytest.mark.e2e


def restore_nodes(stack):
    """Wstrzymany > 10 s proces traci lease i kończy się (#68); jak nadzorca w Compose,
    uruchamiamy go ponownie, żeby kolejne testy miały komplet ról."""
    for role in ("alice", "bob", "mallory"):
        process = stack.nodes.get(role)
        if process is not None:
            resume(process)
    for role in ("alice", "bob", "mallory"):
        process = stack.nodes.get(role)
        if process is not None:
            try:
                process.wait(timeout=3)
            except Exception:
                continue
        stack.nodes.pop(role, None)
        stack.start_node(role)
    stack.wait_online(timeout=40)


def start(page):
    page.click(page.button("Rozpocznij sesję"))


@pytest.mark.widths(390, 1440)
def test_dh_field_validation(page, width):
    page.tab("dh")
    cases = [
        ("", "5", "prime", "To pole jest wymagane."),
        ("2", "5", "prime", "co najmniej równa 3"),
        ("abc", "5", "prime", "nieujemną liczbę całkowitą"),
        ("4294967296", "5", "prime", "Maksymalna wartość"),
        ("23", "23", "generator", None),
        ("23", "", "generator", "To pole jest wymagane."),
    ]
    for prime, generator, field, fragment in cases:
        page.fill("prime", prime)
        page.fill("generator", generator)
        start(page)
        error = page.wait(lambda: page.field_error(field), message=f"błąd pola {field} dla p={prime!r}")
        if fragment:
            assert fragment in error, (prime, generator, error)
        assert page.session_badges() == [], "błędne dane nie tworzą sesji"
    assert page.js("return sessionStorage.getItem('radh.dh.v2.creation')") is None, \
        "walidacja lokalna nie zapisuje próby tworzenia"
    page.screenshot("dh-field-errors")


@pytest.mark.widths(390, 1440)
def test_dh_backend_rejection_is_shown(page, width):
    page.tab("dh")
    page.fill("prime", "24")
    start(page)
    page.wait(lambda: page.notices(".dh-form"), message="komunikat backendu")
    assert page.notices(".dh-form") == ["Parametr p musi być liczbą pierwszą."]
    assert page.js("return document.querySelector('.dh-form .notice--error').getAttribute('role')") == "alert"
    assert page.session_badges() == []
    page.screenshot("dh-backend-error")


@pytest.mark.widths(1440)
def test_dh_offline_node_blocks_start_with_hint(page, ui_stack, width):
    page.tab("dh")
    page.click(page.find("input[name=mode][value=mitm]"))
    ui_stack.pause("mallory")
    try:
        page.wait(lambda: "niedostępny" in page.text(".dh-party--mallory .dh-party-header"),
                  timeout=25, message="Mallory niedostępna (lease 10 s)")
        assert not page.button("Rozpocznij sesję").is_enabled()
        hint = page.text("#dh-nodes-hint")
        assert hint == "Uruchom proces Mallory, żeby rozpocząć sesję."
        assert page.button("Rozpocznij sesję").get_attribute("aria-describedby") == "dh-nodes-hint"
        # Zwykła wymiana nie potrzebuje Mallory — start znów możliwy.
        page.click(page.find("input[name=mode][value=normal]"))
        page.wait(lambda: page.button("Rozpocznij sesję").is_enabled(), message="normal bez Mallory")
        page.screenshot("dh-node-offline")
    finally:
        restore_nodes(ui_stack)
    page.click(page.find("input[name=mode][value=mitm]"))
    page.wait(lambda: page.button("Rozpocznij sesję").is_enabled(), timeout=25, message="Mallory wróciła")


@pytest.mark.widths(1440)
def test_dh_backend_restart_during_session(page, ui_stack, width):
    page.tab("dh")
    ui_stack.pause("bob")
    try:
        page.wait(lambda: page.button("Rozpocznij sesję").is_enabled())
        start(page)
        page.wait(lambda: "sesja w toku" in page.session_badges(), message="sesja w toku")
        page.wait(lambda: "Czekamy na wartość publiczną od Boba" in page.text(".dh-scene"),
                  message="podpowiedź, na kogo czekamy")
        ui_stack.restart_backend()
    finally:
        restore_nodes(ui_stack)
    page.wait(lambda: page.notices(".dh-form"), timeout=30, message="błąd po restarcie backendu")
    message = " ".join(page.notices(".dh-form"))
    assert "Serwer uruchomił się ponownie" in message or "Utracono stan sesji" in message, message
    page.screenshot("dh-backend-restart")
    # Poświadczenie starej sesji zostało usunięte — można od razu zacząć nową.
    assert page.js("return sessionStorage.getItem('radh.dh.v2.session')") is None
    page.wait(lambda: page.button("Rozpocznij sesję").is_enabled(), timeout=20)
    start(page)
    page.wait(lambda: "sesja zakończona" in page.session_badges(), timeout=30, message="nowa sesja po restarcie")
