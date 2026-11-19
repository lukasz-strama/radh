"""Pomocnicze klasy testów systemowych #71 (importowane przez test_multi_session_live): prawdziwy koordynator v2 i procesy ról.

Każdy test dostaje własny backend uvicorn (nowy epoch), osobne pliki tokenów ról
i opcjonalnie rzeczywiste procesy ``nodes.multi_session_cli``. Tam, gdzie test
musi precyzyjnie sterować protokołem (limity running, timeout uczestnika,
nieautoryzowane operacje z poprawną instancją), używa ``PseudoNode`` —
klienta HTTP z tokenem roli, który zachowuje się jak węzeł, ale nie jest
procesem z PR #82. Wektory pseudo-węzła liczy się niezależnie od C (``pow``).
"""

from __future__ import annotations

import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
ROLES = ("alice", "bob", "mallory")
WAIT_SECONDS = 20
POLL_SECONDS = 0.6


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"429, Retry-After {retry_after}")
        self.retry_after = retry_after


def _raise_if_limited(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise RateLimited(float(response.headers.get("retry-after", "1")))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def new_key() -> str:
    """Idempotency-Key: 32 losowe bajty base64url (43 znaki), jak Web Crypto w UI."""
    return secrets.token_urlsafe(32)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def dlog(generator: int, value: int, prime: int) -> int:
    """Logarytm dyskretny dla małych liczb pierwszych testu (niezależny od C)."""
    acc = 1
    for exponent in range(prime):
        if acc == value:
            return exponent
        acc = acc * generator % prime
    raise AssertionError(f"{value} nie jest potęgą {generator} mod {prime}")


def expected_keys(view: dict) -> dict:
    """Oczekiwane K wyliczone z publicznych wartości sesji (niezależnie od C).

    Normal: K_A = B^a = K_B. MITM: Alice liczy z X Mallory, Bob z Y Mallory.
    """
    p, g = view["prime"], view["generator"]
    sent = {m["sender"]: m for m in view["messages"]}
    if view["mode"] == "normal":
        a = dlog(g, sent["alice"]["public_value"], p)
        key = pow(sent["bob"]["public_value"], a, p)
        return {"alice": key, "bob": key}
    original = {i["original_sender"]: i["original_value"] for i in view["interceptions"]}
    delivered = {i["recipient"]: i["delivered_value"] for i in view["interceptions"]}
    a = dlog(g, original["alice"], p)
    b = dlog(g, original["bob"], p)
    return {"alice": pow(delivered["alice"], a, p), "bob": pow(delivered["bob"], b, p)}


@dataclass
class Owned:
    """Sesja z perspektywy jednego użytkownika: ID + capability token."""

    session_id: str
    token: str
    create_key: str
    created: dict

    @property
    def path(self) -> str:
        return "/api/v2/dh/sessions/" + self.session_id

    @property
    def auth(self) -> dict[str, str]:
        return bearer(self.token)


class Stack:
    """Backend v2 + opcjonalne procesy Alice/Bob/Mallory na losowym porcie."""

    def __init__(self, tmp_path: Path, core_path: Path, env: dict[str, str] | None = None,
                 allow_diagnostics: bool = True, port: int | None = None):
        self.tmp = tmp_path
        self.core_path = core_path
        self.env_overrides = {k: str(v) for k, v in (env or {}).items()}
        self.allow_diagnostics = allow_diagnostics
        self.tokens = {role: secrets.token_urlsafe(32) for role in ROLES}
        self.token_files = {}
        for role, token in self.tokens.items():
            path = tmp_path / f"{role}.token"
            path.write_text(token + "\n", encoding="ascii")
            path.chmod(0o600)
            self.token_files[role] = path
        self.port = port or free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.backend: subprocess.Popen | None = None
        self.backend_starts = 0
        self.nodes: dict[str, subprocess.Popen] = {}
        self.node_starts: dict[str, int] = {}
        self.http = httpx.Client(base_url=self.url, timeout=5)

    # --- procesy -------------------------------------------------------------------------
    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        for key in ("RADH_NODE_TEST_SECRET", "RADH_MALLORY_TEST_X", "RADH_MALLORY_TEST_Y"):
            env.pop(key, None)
        env["RADH_CRYPTO_CORE_LIBRARY"] = str(self.core_path)
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(BACKEND_DIR)])
        for role, path in self.token_files.items():
            env[f"RADH_{role.upper()}_TOKEN_FILE"] = str(path)
        env.update(self.env_overrides)
        return env

    def start_backend(self) -> None:
        self.backend_starts += 1
        log = (self.tmp / f"backend-{self.backend_starts}.log").open("wb")
        self.backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(BACKEND_DIR),
             "--host", "127.0.0.1", "--port", str(self.port), "--workers", "1"],
            cwd=ROOT, env=self._env(), stdout=log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            if self.backend.poll() is not None:
                pytest.fail("Backend zakończył pracę:\n" + self.backend_log())
            try:
                if self.http.get("/internal/health/live").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        pytest.fail("Backend nie wystartował:\n" + self.backend_log())

    def stop_backend(self) -> None:
        if self.backend is not None:
            _stop(self.backend)
            self.backend = None

    def restart_backend(self) -> None:
        self.stop_backend()
        self.start_backend()

    def start_node(self, role: str) -> subprocess.Popen:
        self.node_starts[role] = self.node_starts.get(role, 0) + 1
        log = (self.tmp / f"{role}-{self.node_starts[role]}.log").open("wb")
        command = [sys.executable, "-m", "nodes.multi_session_cli", "--role", role, "--url", self.url]
        if self.allow_diagnostics:
            command.append("--allow-diagnostics")
        process = subprocess.Popen(command, cwd=ROOT, env=self._env(), stdout=log,
                                   stderr=subprocess.STDOUT)
        self.nodes[role] = process
        return process

    def start_nodes(self, roles=ROLES) -> None:
        for role in roles:
            self.start_node(role)
        self.wait_online(roles)

    def stop_node(self, role: str, kill: bool = False) -> None:
        process = self.nodes.pop(role)
        _stop(process, kill=kill)

    def pause(self, role: str) -> None:
        """Zamraża proces roli (SIGSTOP na Linuksie, psutil.suspend na Windows)."""
        suspend(self.nodes[role])

    def resume(self, role: str) -> None:
        resume(self.nodes[role])

    def close(self) -> None:
        for role in list(self.nodes):
            process = self.nodes[role]
            if process.poll() is None:
                resume(process)
            self.stop_node(role)
        self.stop_backend()
        self.http.close()

    # --- dzienniki -----------------------------------------------------------------------
    def backend_log(self) -> str:
        return "\n".join(p.read_text(errors="replace") for p in sorted(self.tmp.glob("backend-*.log")))

    def node_log(self, role: str) -> str:
        return "\n".join(p.read_text(errors="replace") for p in sorted(self.tmp.glob(f"{role}-*.log")))

    def all_logs(self) -> str:
        return "\n".join(p.read_text(errors="replace") for p in sorted(self.tmp.glob("*.log")))

    def _check_nodes_alive(self) -> None:
        for role, process in self.nodes.items():
            if process.poll() is not None:
                pytest.fail(f"Proces {role} zakończył pracę:\n" + self.node_log(role))

    # --- API publiczne -------------------------------------------------------------------
    def epoch(self) -> str:
        return self.http.get("/api/v2/dh/nodes").headers["x-backend-epoch"]

    def presence(self) -> dict:
        return self.http.get("/api/v2/dh/nodes").json()

    def wait_online(self, roles=ROLES, online: bool = True, timeout: float = WAIT_SECONDS) -> None:
        self.wait_for(self.presence,
                      lambda p: all(p[r]["online"] is online for r in roles), timeout=timeout)

    def create_raw(self, body: dict, key: str | None = None, epoch: str | None = None,
                   client: httpx.Client | None = None, headers: dict | None = None) -> httpx.Response:
        sent = {"Idempotency-Key": key or new_key(), "X-Backend-Epoch": epoch or self.epoch()}
        sent.update(headers or {})
        return (client or self.http).post("/api/v2/dh/sessions", json=body, headers=sent)

    def create(self, mode: str = "normal", prime: int = 23, generator: int = 5,
               diagnostics: bool = True, client: httpx.Client | None = None,
               key: str | None = None) -> Owned:
        key = key or new_key()
        response = self.create_raw({"prime": prime, "generator": generator, "mode": mode,
                                    "diagnostics_enabled": diagnostics}, key=key, client=client)
        assert response.status_code == 201, response.text
        body = response.json()
        return Owned(body["session"]["session_id"], body["session_token"], key, body)

    def get(self, owned: Owned, client: httpx.Client | None = None) -> dict:
        response = (client or self.http).get(owned.path, headers=owned.auth)
        _raise_if_limited(response)
        assert response.status_code == 200, response.text
        return response.json()

    def start(self, owned: Owned, client: httpx.Client | None = None) -> dict:
        response = (client or self.http).post(owned.path + "/start", headers=owned.auth)
        assert response.status_code == 200, response.text
        return response.json()

    def events(self, owned: Owned) -> list[dict]:
        response = self.http.get(owned.path + "/events", headers=owned.auth)
        _raise_if_limited(response)
        assert response.status_code == 200, response.text
        return response.json()["events"]

    def diagnostics(self, owned: Owned, mallory: bool = False) -> dict:
        suffix = "/diagnostics/mallory" if mallory else "/diagnostics"
        response = self.http.get(owned.path + suffix, headers=owned.auth)
        _raise_if_limited(response)
        assert response.status_code == 200, response.text
        return response.json()

    def wait_for(self, read, predicate, timeout: float = WAIT_SECONDS):
        """Odpytuje co POLL_SECONDS — poniżej limitu 120 odczytów/min/token (#73 §5).

        Gdy mimo to backend odpowie 429, czekamy Retry-After zamiast przerywać test:
        limit odczytów jest tu zabezpieczeniem, a nie badanym zachowaniem.
        """
        deadline = time.monotonic() + timeout
        result = None
        while time.monotonic() < deadline:
            try:
                result = read()
            except RateLimited as limited:
                time.sleep(min(limited.retry_after, max(0.0, deadline - time.monotonic())))
                continue
            if predicate(result):
                return result
            self._check_nodes_alive()
            time.sleep(POLL_SECONDS)
        pytest.fail(f"Nie osiągnięto oczekiwanego stanu w {timeout} s; ostatnio: {result}")

    def wait_status(self, owned: Owned, status: str, timeout: float = WAIT_SECONDS) -> dict:
        return self.wait_for(lambda: self.get(owned), lambda v: v["status"] == status, timeout)

    def wait_diagnostics(self, owned: Owned, mallory: bool = False) -> dict:
        keys = ("shared_with_alice", "shared_with_bob") if mallory else ("alice", "bob")
        return self.wait_for(lambda: self.diagnostics(owned, mallory),
                             lambda d: all(d[k] is not None for k in keys))

    def node(self, role: str, token: str | None = None) -> "PseudoNode":
        return PseudoNode(self, role, self.tokens[role] if token is None else token)


def _tree(process: subprocess.Popen) -> list:
    """Proces i wszystkie jego dzieci (psutil).

    Na Windows ``.venv\\Scripts\\python.exe`` to launcher, który uruchamia właściwy
    interpreter jako proces potomny — wstrzymanie lub zamknięcie samego launchera
    nie dotyczy węzła ani backendu. Dlatego operujemy na całym drzewie.
    """
    try:
        import psutil
    except ImportError:
        pytest.skip("Testy live na Windows wymagają psutil (pip install -r tests/requirements.txt)")
    try:
        parent = psutil.Process(process.pid)
        return parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return []


def suspend(process: subprocess.Popen) -> None:
    if hasattr(signal, "SIGSTOP"):
        process.send_signal(signal.SIGSTOP)
        return
    for proc in _tree(process):
        try:
            proc.suspend()
        except Exception:
            pass


def resume(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if hasattr(signal, "SIGCONT"):
        process.send_signal(signal.SIGCONT)
        return
    for proc in _tree(process):
        try:
            proc.resume()
        except Exception:
            pass


def rss_kib(pid: int) -> int:
    """Pamięć rezydentna procesu w KiB (Linux /proc albo psutil, z dziećmi launchera)."""
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        with status.open(encoding="ascii") as fh:
            return next(int(line.split()[1]) for line in fh if line.startswith("VmRSS:"))
    try:
        import psutil
    except ImportError:
        pytest.skip("Pomiar RSS poza Linuksem wymaga psutil (pip install psutil)")
    parent = psutil.Process(pid)
    return sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)]) // 1024


def _stop(process: subprocess.Popen, kill: bool = False) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        tree = _tree(process)
        for proc in tree:
            try:
                proc.resume()
                proc.kill() if kill else proc.terminate()
            except Exception:
                pass
        try:
            import psutil
            psutil.wait_procs(tree, timeout=8)
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return
    resume(process)
    if kill:
        process.kill()
        process.wait(timeout=5)
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class PseudoNode:
    """Sterowany z testu klient internal; każda metoda zwraca surową odpowiedź."""

    def __init__(self, stack: Stack, role: str, token: str):
        self.stack, self.role, self.token = stack, role, token
        self.instance = uuid4().hex
        self.epoch: str | None = None
        self.secrets: dict[str, int] = {}
        self._beat_stop: threading.Event | None = None

    def headers(self, epoch: str | None = None, instance: str | None = None) -> dict:
        return {**bearer(self.token), "X-Backend-Epoch": epoch or self.epoch or "0" * 32,
                "X-Node-Instance": instance or self.instance}

    def heartbeat(self, role: str | None = None, instance: str | None = None) -> httpx.Response:
        response = self.stack.http.post(
            f"/internal/v1/dh/nodes/{role or self.role}/heartbeat",
            json={"instance_id": instance or self.instance}, headers=bearer(self.token))
        if response.status_code == 200:
            self.epoch = response.json()["backend_epoch"]
        return response

    def register(self) -> "PseudoNode":
        response = self.heartbeat()
        assert response.status_code == 200, response.text
        return self

    def keep_alive(self, period: float = 2.0) -> None:
        """Osobny wątek heartbeat jak w procesie #68 (lease 10 s)."""
        self._beat_stop = threading.Event()

        def loop():
            while not self._beat_stop.wait(period):
                try:
                    self.heartbeat()
                except httpx.TransportError:
                    pass

        threading.Thread(target=loop, daemon=True).start()

    def stop_keep_alive(self) -> None:
        if self._beat_stop is not None:
            self._beat_stop.set()

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", None) or self.headers()
        return self.stack.http.request(method, "/internal/v1/dh" + path, headers=headers, **kwargs)

    def discover(self, **kwargs) -> httpx.Response:
        return self.request("GET", "/sessions", **kwargs)

    def publish(self, sid: str, view: dict, value: int | None = None, **kwargs) -> httpx.Response:
        if value is None:
            secret = self.secrets.setdefault(sid, secrets.randbelow(view["prime"] - 3) + 2)
            value = pow(view["generator"], secret, view["prime"])
        return self.request("POST", f"/sessions/{sid}/messages", json={
            "message_id": self.role + "-public", "type": "public_value", "public_value": value,
        }, **kwargs)

    def inbox(self, sid: str, **kwargs) -> httpx.Response:
        return self.request("GET", f"/sessions/{sid}/messages", **kwargs)

    def ack(self, sid: str, mid: str, **kwargs) -> httpx.Response:
        return self.request("POST", f"/sessions/{sid}/messages/{mid}/ack", **kwargs)

    def interceptions(self, sid: str, **kwargs) -> httpx.Response:
        return self.request("GET", f"/sessions/{sid}/interceptions", **kwargs)

    def forward(self, sid: str, mid: str, value: int, **kwargs) -> httpx.Response:
        return self.request("POST", f"/sessions/{sid}/interceptions/{mid}/forward",
                            json={"public_value": value}, **kwargs)

    def report(self, sid: str, value: int, **kwargs) -> httpx.Response:
        return self.request("POST", f"/sessions/{sid}/diagnostics",
                            json={"shared_secret": value}, **kwargs)

    def report_mallory(self, sid: str, a: int, b: int, **kwargs) -> httpx.Response:
        return self.request("POST", f"/sessions/{sid}/diagnostics/mallory",
                            json={"shared_with_alice": a, "shared_with_bob": b}, **kwargs)

    def fail(self, sid: str, code: str = "LOCAL_STATE_LOST", **kwargs) -> httpx.Response:
        return self.request("POST", f"/sessions/{sid}/fail", json={"code": code}, **kwargs)


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def assert_no_secrets_in(text: str, *secrets_: str) -> None:
    for value in secrets_:
        assert value not in text, "sekret/poświadczenie trafiło do odpowiedzi lub logu"


