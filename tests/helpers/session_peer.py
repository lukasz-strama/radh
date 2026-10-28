"""Proces testowy transportu; stała wartość publiczna, bez implementacji agenta DH."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.dh_transport import HttpTransport, TransportError


class PublicPeer:
    def __init__(self, role):
        self.role = role
        self.state = SimpleNamespace(session_id=None)
        self.received = None

    def start_session(self, session_id, p, g):
        assert (p, g) == (23, 5)
        self.state = SimpleNamespace(session_id=session_id, public_value=8 if self.role == "alice" else 19)

    def receive_public(self, session_id, value):
        assert session_id == self.state.session_id
        self.received = value


role, url, ready = sys.argv[1:]
peer = PublicPeer(role)
transport = HttpTransport(url, role, peer)
Path(ready).write_text("ready")
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    try:
        transport.poll()
        if peer.received is not None:
            print(json.dumps({"role": role, "received": peer.received}))
            break
    except TransportError as error:
        if error.status not in (404, 409):
            raise
    time.sleep(0.05)
else:
    raise SystemExit("Timeout")
