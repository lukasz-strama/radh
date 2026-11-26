"""Uruchamia rzeczywisty węzeł z deterministycznym DH i błędami transportu na potrzeby testów live."""

import json
import os
from pathlib import Path

from nodes import authenticated, multi_session_cli
from nodes.internal_http import InternalClient, InternalError
from nodes.multi_session import MultiSessionTransport
from nodes.testing import DeterministicDhNode, DeterministicMalloryNode


class FaultInjectingClient(InternalClient):
    def __init__(self, url, role, token, instance_id):
        super().__init__(url, role, token, instance_id)
        self.drop = ({"trusted-keys", "signatures", "verifications", "ack"}
                     if role == os.getenv("RADH_TEST_LOST_RESPONSE_ROLE") else set())

    def request(self, method, path, epoch, body=None):
        stage = path.rsplit("/", 1)[-1]
        if method == "POST" and stage == "signatures" and self.role == "alice":
            source = os.getenv("RADH_TEST_SIGNATURE_FIXTURE")
            if source and Path(source).exists():
                fixture = json.loads(Path(source).read_text(encoding="ascii"))
                if path.split("/")[-2] == fixture["session_id"]:
                    if fixture["kind"] == "peer":
                        snapshot, _ = super().request("GET", path.rsplit("/", 1)[0] + "/authentication", epoch)
                        originals = [s for s in snapshot["signatures"] if s["signer"] == "bob"]
                        if not originals:
                            raise InternalError(409, "PUBLIC_VALUES_REQUIRED")
                        original = originals[0]
                    else:
                        original = fixture["signature"]
                    body = {field: original[field] for field in ("signature", "transcript_hash")}
        result = super().request(method, path, epoch, body)
        if method == "POST" and stage in self.drop:
            self.drop.remove(stage)
            print(f"lost response: {stage}", flush=True)
            raise InternalError()
        return result


def real_transport(client, **kwargs):
    role = client.role
    if os.getenv("RADH_TEST_SIGNATURE_FIXTURE"):
        # Stałe klucze zapewniają, że rekord testowy mieści się w module odbiorcy.
        parameters = {"alice": (65519, 65521, 19), "bob": (257, 263, 3)}
        authenticated.generate_rsa_keypair = lambda core, _: core.generate_rsa_keys(*parameters[role])
    if role == "mallory":
        factory = lambda: DeterministicMalloryNode(7, 11)
    else:
        factory = lambda: DeterministicDhNode(role, 6 if role == "alice" else 15)
    return MultiSessionTransport(client, factory=factory, **kwargs)


if __name__ == "__main__":
    multi_session_cli.InternalClient = FaultInjectingClient
    multi_session_cli.MultiSessionTransport = real_transport
    raise SystemExit(multi_session_cli.main())
