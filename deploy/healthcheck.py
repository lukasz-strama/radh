"""Sondy dla wielosesyjnego Compose v2; nie dodają endpointów ani heartbeatów."""

import json
import os
import sys
import stat
from pathlib import Path
from urllib.request import urlopen


def check_secret(role: str) -> None:
    path = Path(os.environ[f"RADH_{role.upper()}_TOKEN_FILE"])
    info = path.stat()
    assert stat.S_ISREG(info.st_mode)
    assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (10001, 10001, 0o400)
    assert os.statvfs(path).f_flag & os.ST_RDONLY
    with path.open("rb") as stream:
        assert stream.read(1)


def main() -> None:
    if sys.argv[1] == "backend":
        for role in ("alice", "bob", "mallory"):
            check_secret(role)
        with urlopen("http://127.0.0.1:8000/internal/health/ready", timeout=2) as response:
            assert json.load(response) == {"status": "ready"}
    else:
        assert sys.argv[1] == "node"
        os.kill(1, 0)
        role = os.environ["RADH_NODE_ROLE"]
        check_secret(role)
        command = Path('/proc/1/cmdline').read_bytes().split(b'\0')
        assert b'nodes.multi_session_cli' in command
        position = command.index(b'--role')
        assert command[position + 1] == role.encode()
        url = os.environ["RADH_COORDINATOR_URL"].rstrip("/") + "/api/v2/dh/nodes"
        with urlopen(url, timeout=2) as response:
            assert json.load(response)[role]["online"] is True


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Healthcheck nie ujawnia konfiguracji, ścieżek, tokenów i argumentów C.
        print("Healthcheck failed", file=sys.stderr)
        sys.exit(1)
