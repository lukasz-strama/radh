"""Infrastruktura testów E2E interfejsu (QA UI): Chrome/Chromium i Firefox przez Selenium.

Uruchamiane wyłącznie przy ``RADH_E2E=1`` (osobny job CI), bo wymagają
zbudowanego frontendu (``npm run build``) i przeglądarek z driverami.

Środowisko: backend v2 na 127.0.0.1:8000 (port zaszyty w proxy Vite), trzy
rzeczywiste procesy ról z ``--allow-diagnostics`` i ``vite preview`` na
http://localhost:5173 (Origin dopuszczony domyślnie przez backend).

Szerokości 360/390/768/1440 px:
* Chrome 360/390 — emulacja urządzenia mobilnego (viewport, dotyk, nakładkowe paski
  przewijania); 768/1440 — okno desktopowe o dokładnym ``innerWidth``.
* Firefox 768/1440 — okno; 360/390 — headless Firefox nie schodzi poniżej 500 px
  okna, więc aplikację osadzamy w ramce o dokładnej szerokości (media queries
  liczą się względem ramki), z nakładkowymi paskami i zdarzeniami dotyku.

Zmienne (opcjonalne — domyślnie Selenium Manager/PATH, jak w GitHub Actions):
RADH_E2E_CHROME_BINARY, RADH_E2E_CHROMEDRIVER, RADH_E2E_FIREFOX_BINARY,
RADH_E2E_GECKODRIVER, RADH_E2E_BROWSERS (np. "chrome,firefox"), RADH_E2E_ARTIFACTS.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

from helpers.multi_session_stack import Stack

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
BASE_URL = "http://localhost:5173"
BACKEND_PORT = 8000
WIDTHS = (360, 390, 768, 1440)
MOBILE = (360, 390)
HEIGHT = 900
ENABLED = os.environ.get("RADH_E2E") == "1"
BROWSERS = tuple(b.strip() for b in os.environ.get("RADH_E2E_BROWSERS", "chrome,firefox").split(",") if b.strip())
ARTIFACTS = Path(os.environ.get("RADH_E2E_ARTIFACTS", ROOT / "frontend" / "e2e-artifacts"))


def pytest_collection_modifyitems(config, items):
    if ENABLED:
        return
    skip = pytest.mark.skip(reason="Testy E2E UI: ustaw RADH_E2E=1 (patrz tests/test_ui_e2e/conftest.py)")
    for item in items:
        if "test_ui_e2e" in str(item.fspath):
            item.add_marker(skip)


def _port_free(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


@pytest.fixture(scope="session")
def ui_stack(core, tmp_path_factory):
    """Backend v2 + Alice/Bob/Mallory + ``vite preview`` dla całej sesji testów."""
    for port in (BACKEND_PORT, 5173):
        if not _port_free(port):
            pytest.fail(f"Port {port} jest zajęty — zatrzymaj lokalny backend/Vite przed E2E.")
    if not (FRONTEND / "dist" / "index.html").exists():
        subprocess.run(["npm", "run", "build"], cwd=FRONTEND, check=True)

    tmp = tmp_path_factory.mktemp("ui-stack")
    # Limity tworzenia z jednego IP podnosimy, bo wszystkie przeglądarki testu mają
    # 127.0.0.1; pozostałe ustawienia są domyślne (#73 §5).
    stack = Stack(tmp, core.path, {
        "CREATE_RATE_PER_MINUTE": 600, "CREATE_RATE_BURST": 64, "MAX_SESSIONS_PER_IP": 64,
        "READ_IP_RATE_PER_MINUTE": 6000, "CRYPTO_RATE_PER_MINUTE": 600, "CRYPTO_RATE_BURST": 64,
    }, port=BACKEND_PORT)
    stack.start_backend()
    stack.start_nodes()
    vite_bin = FRONTEND / "node_modules" / ".bin" / ("vite.cmd" if os.name == "nt" else "vite")
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    vite = subprocess.Popen(
        [str(vite_bin), "preview", "--port", "5173", "--strictPort", "--host", "localhost"],
        cwd=FRONTEND, stdout=(tmp / "vite.log").open("wb"), stderr=subprocess.STDOUT, **group)
    import httpx
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx.get(BASE_URL + "/", timeout=2).status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.2)
    else:
        _kill_group(vite)
        stack.close()
        pytest.fail("vite preview nie wystartował:\n" + (tmp / "vite.log").read_text(errors="replace"))
    yield stack
    _kill_group(vite)
    stack.close()


def _kill_group(process: subprocess.Popen) -> None:
    """vite uruchamia procesy potomne — zamykamy całą grupę procesów."""
    import signal
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)


def _chrome(width: int):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    if os.environ.get("RADH_E2E_CHROME_BINARY"):
        options.binary_location = os.environ["RADH_E2E_CHROME_BINARY"]
    if width in MOBILE:
        options.add_experimental_option("mobileEmulation", {
            "deviceMetrics": {"width": width, "height": 800, "pixelRatio": 3.0, "touch": True},
            "userAgent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/153.0 Mobile Safari/537.36",
        })
    service = Service(os.environ["RADH_E2E_CHROMEDRIVER"]) if os.environ.get("RADH_E2E_CHROMEDRIVER") else Service()
    return webdriver.Chrome(service=service, options=options)


def _firefox(width: int):
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service

    options = webdriver.FirefoxOptions()
    options.add_argument("-headless")
    if os.environ.get("RADH_E2E_FIREFOX_BINARY"):
        options.binary_location = os.environ["RADH_E2E_FIREFOX_BINARY"]
    if width in MOBILE:
        options.set_preference("ui.useOverlayScrollbars", 1)
        options.set_preference("dom.w3c_touch_events.enabled", 1)
    service = Service(os.environ["RADH_E2E_GECKODRIVER"]) if os.environ.get("RADH_E2E_GECKODRIVER") else Service()
    return webdriver.Firefox(service=service, options=options)


class Page:
    """Strona RADH w danej przeglądarce i szerokości; metody zwracają dane z DOM."""

    def __init__(self, driver, browser: str, width: int, name: str):
        self.driver, self.browser, self.width, self.name = driver, browser, width, name
        self.framed = browser == "firefox" and width in MOBILE
        if not (browser == "chrome" and width in MOBILE):
            driver.set_window_size(width, HEIGHT)
            driver.get("about:blank")
            inner = driver.execute_script("return window.innerWidth")
            if not self.framed:
                driver.set_window_size(width + (width - inner), HEIGHT)
            else:
                driver.set_window_size(1000, HEIGHT)

    # --- nawigacja ----------------------------------------------------------------------------
    def open(self):
        driver = self.driver
        driver.switch_to.default_content()
        driver.get(BASE_URL + "/")
        driver.execute_script("sessionStorage.clear()")
        if self.framed:
            driver.execute_script(
                "document.open();document.write('<!doctype html><html><body style=\"margin:0\">"
                "<iframe id=\"vp\" src=\"/\" style=\"border:0;width:%dpx;height:%dpx\"></iframe>"
                "</body></html>');document.close();" % (self.width, HEIGHT))
            self.wait(lambda: driver.execute_script(
                "const f=document.getElementById('vp');return !!(f&&f.contentDocument&&"
                "f.contentDocument.querySelector('#tab-rsa'))"))
            driver.switch_to.frame(driver.find_element("id", "vp"))
        self.wait(lambda: self.js("return !!document.querySelector('#tab-rsa')"))
        assert self.js("return document.documentElement.clientWidth") <= self.width
        return self

    def reload(self):
        if self.framed:
            self.js("location.reload()")
            time.sleep(0.3)
        else:
            self.driver.refresh()
        self.wait(lambda: self.js("return !!document.querySelector('#tab-rsa')"))

    def js(self, script: str, *args):
        return self.driver.execute_script(script, *args)

    def wait(self, predicate, timeout: float = 25, message: str = ""):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                last = predicate()
                if last:
                    return last
            except Exception as error:  # element w trakcie renderowania
                last = error
            time.sleep(0.15)
        raise AssertionError(f"[{self.name}] nie doczekano się: {message or predicate} (ostatnio: {last})")

    def find(self, css: str):
        from selenium.webdriver.common.by import By
        return self.driver.find_element(By.CSS_SELECTOR, css)

    def button(self, text: str, scope: str = "body"):
        from selenium.webdriver.common.by import By
        return self.find(scope).find_element(By.XPATH, f".//button[normalize-space()='{text}']")

    def click(self, element):
        self.js("arguments[0].scrollIntoView({block:'center'})", element)
        element.click()

    def tap(self, element):
        """Dotknięcie (pointer type touch) w środek elementu — W3C Actions."""
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        from selenium.webdriver.common.actions import interaction

        self.js("arguments[0].scrollIntoView({block:'center'})", element)
        finger = PointerInput(interaction.POINTER_TOUCH, "finger")
        actions = ActionBuilder(self.driver, mouse=finger)
        actions.pointer_action.move_to(element).pointer_down().pause(0.05).pointer_up()
        actions.perform()

    def fill(self, name: str, value: str):
        element = self.find(f"input[name='{name}']")
        self.js("arguments[0].scrollIntoView({block:'center'})", element)
        element.clear()
        element.send_keys(value)

    def tab(self, which: str):
        self.click(self.find(f"#tab-{which}"))
        self.wait(lambda: self.find(f"#view-{which}").is_displayed())

    # --- odczyty --------------------------------------------------------------------------------
    def text(self, css: str) -> str:
        return self.js("const e=document.querySelector(arguments[0]);return e?e.innerText:''", css)

    def field_error(self, name: str) -> str | None:
        return self.js("""
            const i=document.querySelector(`input[name='${arguments[0]}']`);
            if(i.getAttribute('aria-invalid')!=='true')return null;
            const d=document.getElementById(i.getAttribute('aria-describedby'));
            return d?d.innerText:'(brak opisu)';""", name)

    def notices(self, scope: str = "body") -> list[str]:
        return self.js("return [...document.querySelector(arguments[0]).querySelectorAll('.notice')]"
                       ".filter(e=>e.offsetParent!==null).map(e=>e.innerText)", scope)

    def party(self, role: str) -> dict:
        """Wartości z panelu węzła w widocznej zakładce: etykieta → liczba z <output> (None = '?').

        Zakładki DH i RSA + DH są naraz w DOM, więc panele z ukrytej zakładki pomijamy."""
        return self.js("""
            const out={};
            for(const v of document.querySelectorAll(`.dh-party--${arguments[0]} .dh-value`)){
              if(v.closest('[hidden]'))continue;
              const label=v.querySelector('.dh-value-header').innerText.replace(/\\s*(tajne|jawne)\\s*$/,'').trim();
              const o=v.querySelector('output'); const t=o?o.innerText.trim():null;
              out[label]=t===null||t==='?'?null:Number(t);
            }
            return out;""", role)

    def session_badges(self) -> list[str]:
        return self.js("return [...document.querySelectorAll('.dh-shared .badge')]"
                       ".filter(e=>!e.closest('[hidden]')).map(e=>e.innerText)")

    def layout_report(self) -> dict:
        """Przepełnienia poziome, małe cele dotykowe, nakładanie się elementów."""
        return self.js("""
            const vw=document.documentElement.clientWidth;
            const visible=e=>{const s=getComputedStyle(e);const r=e.getBoundingClientRect();
              return s.visibility!=='hidden'&&s.display!=='none'&&r.width>0&&r.height>0&&e.closest('[hidden]')===null};
            const all=[...document.querySelectorAll('body *')].filter(visible);
            const overflow=all.filter(e=>{const r=e.getBoundingClientRect();
                const clip=e.closest('.dh-log-scroll');
                return !clip&&(r.right>vw+0.5||r.left<-0.5)})
              .map(e=>e.tagName.toLowerCase()+'.'+[...e.classList].join('.'));
            const target=e=>{const l=e.closest('label');const r=(l&&['radio','checkbox'].includes(e.type)?l:e).getBoundingClientRect();return r};
            const small=[...document.querySelectorAll('button,input,a,summary,[role=tab]')].filter(visible)
              .map(e=>{const r=target(e);return {el:e.tagName.toLowerCase()+(e.name?'['+e.name+']':'')+' '+(e.innerText||e.value||'').trim().slice(0,25),w:Math.round(r.width),h:Math.round(r.height)}})
              .filter(x=>x.w<24||x.h<24);
            return {vw, scrollWidth:document.documentElement.scrollWidth, overflow:[...new Set(overflow)].slice(0,10), small};""")

    def screenshot(self, label: str):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        path = ARTIFACTS / f"{self.browser}-{self.width}-{label}.png"
        driver = self.driver
        height = self.js("return document.documentElement.scrollHeight")
        if self.framed:
            driver.switch_to.default_content()
            driver.execute_script("document.getElementById('vp').style.height=arguments[0]+'px'", height)
            driver.set_window_size(1000, min(height + 200, 8000))
            time.sleep(0.3)
            driver.find_element("id", "vp").screenshot(str(path))
            driver.execute_script("document.getElementById('vp').style.height=arguments[0]+'px'", HEIGHT)
            driver.set_window_size(1000, HEIGHT)
            driver.switch_to.frame(driver.find_element("id", "vp"))
        elif self.browser == "chrome" and self.width in MOBILE:
            metrics = {"width": self.width, "height": min(height, 8000), "deviceScaleFactor": 1, "mobile": True}
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", metrics)
            time.sleep(0.3)
            driver.save_screenshot(str(path))
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {**metrics, "height": 800, "deviceScaleFactor": 3})
        else:
            size = driver.get_window_size()
            driver.set_window_size(size["width"], min(height + 150, 8000))
            time.sleep(0.3)
            driver.save_screenshot(str(path))
            driver.set_window_size(size["width"], size["height"])
        return path

    def record(self, test: str, data: dict):
        """Dopisuje wynik do ARTIFACTS/results.jsonl — z tego powstaje raport QA."""
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        with (ARTIFACTS / "results.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"test": test, "browser": self.browser, "width": self.width, **data},
                                ensure_ascii=False) + "\n")


def _make(browser: str, width: int, name: str) -> Page:
    factory = {"chrome": _chrome, "firefox": _firefox}[browser]
    try:
        driver = factory(width)
    except Exception as error:  # brak przeglądarki/drivera w środowisku
        pytest.skip(f"{browser} niedostępny: {str(error).splitlines()[0][:200]}")
    driver.set_script_timeout(10)
    return Page(driver, browser, width, name)


@pytest.fixture
def page_factory(ui_stack, request):
    pages: list[Page] = []

    def factory(browser: str, width: int) -> Page:
        page = _make(browser, width, f"{request.node.name}")
        pages.append(page)
        return page.open()

    yield factory
    for page in pages:
        try:
            page.driver.quit()
        except Exception:
            pass


def pytest_generate_tests(metafunc):
    if "browser" in metafunc.fixturenames:
        metafunc.parametrize("browser", BROWSERS)
    if "width" in metafunc.fixturenames:
        marker = metafunc.definition.get_closest_marker("widths")
        metafunc.parametrize("width", marker.args if marker else WIDTHS)


@pytest.fixture
def page(page_factory, browser, width) -> Page:
    return page_factory(browser, width)