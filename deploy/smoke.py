"""Ręczny smoke lokalnego Compose v1; nie zastępuje testów QA #71."""

import argparse
import json
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke RSA i normal/MITM na lokalnym Compose.")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--diagnostics", action="store_true")
    args = parser.parse_args()
    if urlsplit(args.url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Smoke jest przeznaczony wyłącznie dla lokalnego loopback.")
    base = args.url.rstrip("/")

    def request(method: str, path: str, body: dict | None = None) -> object:
        data = None if body is None else json.dumps(body).encode()
        req = Request(base + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=5) as response:
            return json.load(response)

    key = request("POST", "/api/v1/rsa/demo/keygen", {"p": 61, "q": 53, "e": 17})
    assert key == {"n": 3233, "e": 17, "d": 2753, "phi": 3120}
    cipher = request("POST", "/api/v1/rsa/demo/encrypt", {
        "message": 65, "public_exponent": key["e"], "modulus": key["n"],
    })
    assert cipher == {"ciphertext": 2790}
    print("RSA/keygen: OK")
    deadline = time.monotonic() + 30
    while True:
        nodes = request("GET", "/api/v1/dh/nodes")
        if all(nodes[role]["online"] for role in ("alice", "bob", "mallory")):
            break
        assert time.monotonic() < deadline, "Węzły nie są dostępne."
        time.sleep(1)

    for mode in ("normal", "mitm"):
        session_id = "smoke-" + uuid4().hex
        path = "/api/v1/dh/sessions/" + session_id
        request("POST", "/api/v1/dh/sessions", {
            "session_id": session_id, "prime": 23, "generator": 5, "mode": mode,
        })
        try:
            request("POST", path + "/start")
            deadline = time.monotonic() + 30
            while True:
                session = request("GET", path)
                if session["status"] == "completed":
                    break
                assert time.monotonic() < deadline, "Wymiana nie zakończyła się w terminie."
                time.sleep(0.5)
            assert session["participants"] == {"alice": "received", "bob": "received"}
            assert len(session["messages"]) == 2
            assert all(m["status"] == "processed" and 1 <= m["public_value"] < 23
                       for m in session["messages"])
            assert len(session["interceptions"]) == (2 if mode == "mitm" else 0)
            if args.diagnostics:
                deadline = time.monotonic() + 10
                while True:
                    diag = request("GET", path + "/diagnostics")
                    mallory = request("GET", path + "/diagnostics/mallory") if mode == "mitm" else {}
                    if all(v is not None for v in [*diag.values(), *mallory.values()]):
                        break
                    assert time.monotonic() < deadline, "Brak jawnej diagnostyki."
                    time.sleep(0.5)
                assert all(1 <= v < 23 for v in [*diag.values(), *mallory.values()])
                if mode == "normal":
                    assert diag["alice"] == diag["bob"]
                else:
                    assert diag["alice"] == mallory["shared_with_alice"]
                    assert diag["bob"] == mallory["shared_with_bob"]
                # Losowe wykładniki nie gwarantują różnych K w MITM przy małym p.
            print(f"DH {mode}: OK")
        except Exception:
            try:
                request("POST", path + "/cancel")
            except Exception:
                pass  # Sprzątanie nie zastępuje zgłoszenia pierwotnego błędu.
            raise


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Smoke nie powiódł się; sprawdź stan i logi lokalnych usług.")
