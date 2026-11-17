"""Sondy dla aktualnego v1; nie dodają endpointów ani heartbeatów."""

import json
import os
import sys
from urllib.request import urlopen


def main() -> None:
    if sys.argv[1] == "backend":
        # Sprawdź trasę aplikacji i załadowanie biblioteki z wymaganym ABI.
        with urlopen("http://127.0.0.1:8000/openapi.json", timeout=2) as response:
            schema = json.load(response)
        assert "/api/v1/rsa/demo/keygen" in schema["paths"]
        from backend.app.crypto_core import CryptoCore
        core = CryptoCore()
        assert core._keygen is not None
    else:
        assert sys.argv[1] == "node"
        os.kill(1, 0)
        role = os.environ["RADH_NODE_ROLE"]
        url = os.environ["RADH_COORDINATOR_URL"].rstrip("/") + "/api/v1/dh/nodes"
        with urlopen(url, timeout=2) as response:
            assert json.load(response)[role]["online"] is True


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Healthcheck nie ujawnia konfiguracji, ścieżek, tokenów i argumentów C.
        print("Healthcheck failed", file=sys.stderr)
        sys.exit(1)
