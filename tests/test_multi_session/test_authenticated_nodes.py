"""Węzły uwierzytelnione i koordynator z rzeczywistą biblioteką C."""

from hashlib import sha256
from secrets import token_urlsafe

import pytest
from pydantic import ValidationError

from backend.app.coordinator import Coordinator
from backend.app.coordinator_limits import CoordinatorError
from backend.app.crypto_core import CryptoCore, CryptoCoreCallError, CryptoCoreInputError
from backend.app.multi_models import (
    Create, Failure, MalloryReport, Publish, Report, SignatureRequest, TrustedKeyRequest,
    VerificationRequest,
)
from backend.app.parameter_generation import ParameterGenerationExhausted, generate_rsa_keypair
from nodes.authenticated import AuthenticatedExchange
from nodes.internal_http import EpochChanged, InternalError
from nodes.internal_models import AuthenticationState, PublicKey, Signature, TrustedKey
from nodes.multi_session import MultiSessionTransport
from nodes.node import NodeError
from nodes.testing import DeterministicDhNode, DeterministicMalloryNode
from nodes.transcript import Transcript

CONTEXT = {"session_id": "0" * 32, "backend_epoch": "1" * 32}
TEXT = (
    b"RADH-SIGNED-DH-V1\n"
    b"session_id=00000000000000000000000000000000\n"
    b"backend_epoch=11111111111111111111111111111111\n"
    b"signer=alice\nprime=23\ngenerator=5\nalice_public=8\nbob_public=19\n"
    b"alice_rsa_n=3233\nalice_rsa_e=17\nbob_rsa_n=3127\nbob_rsa_e=17"
)


def transcript(**changes):
    data = dict(**CONTEXT, signer="alice", prime=23, generator=5, alice_public=8, bob_public=19,
                alice_key=PublicKey(modulus=3233, public_exponent=17),
                bob_key=PublicKey(modulus=3127, public_exponent=17))
    return Transcript(**(data | changes))


def test_transcript_matches_known_bytes_and_hash():
    original = transcript()
    assert original.encode() == TEXT
    expected = sha256(TEXT).hexdigest()
    assert expected == "952de03098d7296e9602d03cbed00a3908dd9683e9bd59a4ed9eceefc6eaf33e"
    assert original.hash_and_representative() == (expected, int(expected, 16) % 3233)
    assert transcript(signer="bob").hash_and_representative()[1] == (
        int(sha256(TEXT.replace(b"signer=alice", b"signer=bob")).hexdigest(), 16) % 3127
    )


@pytest.mark.parametrize("change", [
    {"session_id": "2" * 32}, {"backend_epoch": "2" * 32}, {"signer": "bob"},
    {"bob_public": 17}, {"alice_public": 22},
    {"alice_key": PublicKey(modulus=3233, public_exponent=7)},
    {"bob_key": PublicKey(modulus=3233, public_exponent=17)},
])
def test_transcript_binds_session_epoch_role_and_both_pairs(change):
    assert transcript(**change).hash_and_representative()[0] != transcript().hash_and_representative()[0]


@pytest.mark.parametrize("change", [
    {"session_id": "A" * 32}, {"backend_epoch": "1" * 31}, {"signer": "mallory"},
    {"prime": True}, {"generator": "05"}, {"alice_public": 0}, {"bob_public": 23},
    {"bob_key": {"modulus": 3233, "public_exponent": 3233}},
])
def test_transcript_rejects_noncanonical_inputs(change):
    with pytest.raises(ValidationError):
        transcript(**change)


def test_ctypes_signature_calls_and_errors(core):
    adapter = CryptoCore(core.path)
    assert adapter.sign(65, 2753, 3233) == 588 == pow(65, 2753, 3233)
    assert adapter.verify(65, 588, 17, 3233) is True
    assert adapter.verify(66, 588, 17, 3233) is False
    with pytest.raises(CryptoCoreCallError) as error:
        adapter.verify(65, 3233, 17, 3233)
    assert error.value.code == "MESSAGE_OUT_OF_RANGE"
    for call in (lambda: adapter.sign(True, 2753, 3233),
                 lambda: adapter.verify(65, 2**32, 17, 3233)):
        with pytest.raises(CryptoCoreInputError):
            call()


def test_keygen_budget_and_key_material(core, monkeypatch):
    adapter = CryptoCore(core.path)
    draws = []

    def same_prime(upper):
        draws.append(upper)
        return 0  # p=257, kandydat q zawsze równy p.

    monkeypatch.setattr("backend.app.parameter_generation.secrets.randbelow", same_prime)
    with pytest.raises(ParameterGenerationExhausted):
        generate_rsa_keypair(adapter, 7)
    assert len(draws) == 7

    # Dwa niezależne komplety z budżetu, z różną liczbą pierwszą w drugiej parze.
    draws = iter([0, 3, 1, 3, 6, 1])  # (257,263,3), (263,269,3)

    def next_candidate(upper):
        value = next(draws)
        assert 0 <= value < upper
        return value

    monkeypatch.setattr("backend.app.parameter_generation.secrets.randbelow", next_candidate)
    first, second = AuthenticatedExchange(adapter), AuthenticatedExchange(adapter)
    assert first.public_key.modulus == 257 * 263
    assert second.public_key.modulus == 263 * 269
    assert first.public_key.model_dump() == {"modulus": 257 * 263, "public_exponent": 3}
    assert "private_exponent" not in repr(first)


def test_full_hash_mismatch_rejects_even_with_same_representative(core):
    adapter = CryptoCore(core.path)
    signed = transcript(prime=65521, bob_public=35)
    received = transcript(prime=65521, bob_public=47)
    published_hash, representative = signed.hash_and_representative()
    local_hash, local_representative = received.hash_and_representative()
    assert representative == local_representative == 1482 and published_hash != local_hash
    signature = adapter.sign(representative, 2753, 3233)
    assert adapter.verify(local_representative, signature, 17, 3233) is True
    exchange = AuthenticatedExchange(adapter)
    exchange.peer_key = TrustedKey(**CONTEXT, owner="alice", modulus=3233, public_exponent=17)
    record = Signature(**CONTEXT, signer="alice", signature=signature, transcript_hash=published_hash)
    assert exchange.verify(received, record, "bob").verified is False


@pytest.mark.parametrize("change", [{"session_id": "2" * 32}, {"signer": "bob"}])
def test_signature_context_of_another_session_or_role_is_rejected(core, change):
    adapter = CryptoCore(core.path)
    old = transcript(**change)
    params = (53, 59, 17) if old.signer == "bob" else (61, 53, 17)
    old_key = adapter.generate_rsa_keys(*params)
    old_hash, representative = old.hash_and_representative()
    s = adapter.sign(representative, old_key.d, old_key.n)
    assert adapter.verify(representative, s, old_key.e, old_key.n)
    expected = transcript()
    exchange = AuthenticatedExchange(adapter)
    exchange.peer_key = TrustedKey(**CONTEXT, owner="alice", modulus=3233, public_exponent=17)
    copied = Signature(**CONTEXT, signer="alice", signature=s, transcript_hash=old_hash)
    result = exchange.verify(expected, copied, "bob")
    assert result.verified is False and result.transcript_hash != result.published_transcript_hash


class CoordinatorClient:
    """Wysyła te same modele do prawdziwego rejestru bez używania gniazd."""

    def __init__(self, coordinator, role, instance):
        self.coordinator, self.role, self.instance_id = coordinator, role, instance
        self.drop = set()
        self.writes = []

    def request(self, method, path, epoch, body=None):
        c, role, iid = self.coordinator, self.role, self.instance_id
        try:
            if path.endswith("/heartbeat"):
                response = c.heartbeat(role, body["instance_id"])
            elif epoch != c.epoch:
                raise EpochChanged()
            elif path == "/internal/v1/dh/sessions":
                response = c.discover(role, epoch, iid)
            else:
                sid, route, *tail = path.split("/")[5:]
                with c.access(sid, role=role, epoch=epoch, instance=iid) as record:
                    response = self.session(record, method, route, tail, body)
                if method == "POST":
                    self.writes.append((sid, route, tuple(tail), body))
                    stage = tail[-1] if tail else route
                    if stage in self.drop:
                        self.drop.remove(stage)
                        raise InternalError()
        except CoordinatorError as error:
            raise InternalError(error.status, error.code) from None
        return None if response is None else response.model_dump(mode="json"), c.epoch

    def session(self, record, method, route, tail, body):
        c, role = self.coordinator, self.role
        if route == "messages":
            if tail:
                return c.acknowledge(record, role, tail[0])
            return c.inbox(record, role) if method == "GET" else c.publish(record, role, Publish(**body))
        if route == "authentication":
            return c.authentication(record, role)
        if route == "trusted-keys":
            return c.publish_trusted_key(record, role, TrustedKeyRequest(**body))
        if route == "signatures":
            return c.publish_signature(record, role, SignatureRequest(**body))
        if route == "verifications":
            return c.verify_signature(record, role, VerificationRequest(**body))
        if route == "interceptions":
            return (c.interceptions(record, role) if method == "GET"
                    else c.forward(record, role, tail[0], body["public_value"]))
        if route == "diagnostics":
            c.report(record, role, (MalloryReport if tail else Report)(**body))
            return None
        if route == "fail":
            return c.fail(record, Failure(**body).code)
        pytest.fail(f"Nieoczekiwana operacja {route}")


def components(core):
    coordinator = Coordinator()
    transports = {}
    adapter = CryptoCore(core.path)
    for index, (role, factory) in enumerate((
        ("alice", lambda: DeterministicDhNode("alice", 6, adapter)),
        ("bob", lambda: DeterministicDhNode("bob", 15, adapter)),
        ("mallory", lambda: DeterministicMalloryNode(7, 11, adapter)),
    )):
        client = CoordinatorClient(coordinator, role, f"{index:032x}")
        worker = MultiSessionTransport(client, factory=factory, allow_diagnostics=True)
        worker.heartbeat()
        transports[role] = worker
    return coordinator, transports


def start(coordinator, scenario="authenticated", mode="normal"):
    owned = coordinator.create(Create(prime=23, generator=5, mode=mode, scenario=scenario,
                                      diagnostics_enabled=True), token_urlsafe(32), coordinator.epoch, "ip")
    coordinator.transition(owned.session.session_id, owned.session_token, "start")
    return owned.session.session_id, owned.session_token


def step(transport):
    transport.discover()
    for entry in list(transport.entries.values()):
        if not entry.disabled:
            transport.work(entry)


@pytest.mark.parametrize(("scenarios", "mode"), [
    (("classic",), "normal"), (("classic",), "mitm"),
    (("authenticated",), "normal"), (("authenticated",), "mitm"),
    (("classic", "authenticated"), "normal"), (("authenticated", "authenticated"), "normal"),
])
def test_component_exchange_and_isolation(core, scenarios, mode):
    coordinator, transports = components(core)
    owned = [start(coordinator, scenario, mode) for scenario in scenarios]
    for _ in range(10):
        for transport in transports.values():
            step(transport)
    for (sid, token), scenario in zip(owned, scenarios):
        view = coordinator.get(sid, token)
        keys = coordinator.diagnostics(sid, token)
        mallory = coordinator.diagnostics(sid, token, mallory=True)
        if scenario == "authenticated" and mode == "mitm":
            assert view.failure_code == "SIGNATURE_VERIFICATION_FAILED"
            assert view.status == "failed" and any(i.delivered_value != i.original_value for i in view.interceptions)
            assert keys.alice is keys.bob is mallory.shared_with_alice is mallory.shared_with_bob is None
            assert all(m.status != "processed" for m in view.messages)
            assert not any(route == "diagnostics" for t in transports.values() for _, route, _, _ in t.client.writes)
            continue
        assert view.status == "completed"
        assert (keys.alice, keys.bob) == ((2, 2) if mode == "normal" else (12, 22))
        if scenario == "authenticated":
            assert len(view.authentication.verifications) == 2
            assert all(report.verified for report in view.authentication.verifications)
            assert all(m.status == "processed" for m in view.messages)
        else:
            assert not view.authentication.trusted_keys


def test_authentication_retries_same_payload_and_repeats_ack_after_completion(core):
    coordinator, transports = components(core)
    sid, token = start(coordinator)
    alice, bob = transports["alice"], transports["bob"]
    bob.client.drop = {"trusted-keys", "signatures", "verifications", "ack"}
    for _ in range(15):
        step(alice)
        step(bob)
    assert coordinator.get(sid, token).status == "completed"
    assert coordinator.diagnostics(sid, token).bob == 2
    for stage in ("trusted-keys", "signatures", "verifications", "ack"):
        retries = [item for item in bob.client.writes if item[1] == stage or item[2][-1:] == (stage,)]
        assert len(retries) == 2 and retries[0] == retries[1]
    events = [event.type for event in coordinator.events(sid, token).events]
    assert events.count("signature_published") == events.count("signature_verified") == 2
    assert events.count("message_processed") == 2
    assert events.count("session_completed") == 1


def test_negative_verification_discards_pending_secret_without_calling_receive(core):
    coordinator, transports = components(core)
    sid, token = start(coordinator, mode="mitm")
    alice = transports["alice"]
    step(alice)
    entry = alice.entries[coordinator.epoch, sid]
    pending = entry.node
    with pytest.raises(NodeError):
        pending.diagnostics()
    for _ in range(10):
        for transport in transports.values():
            step(transport)
    assert coordinator.get(sid, token).failure_code == "SIGNATURE_VERIFICATION_FAILED"
    assert pending.state.phase == "public_ready"
    with pytest.raises(NodeError):
        pending.diagnostics()
    assert entry.disabled and entry.node is entry.authentication is None


def test_discovery_rejects_changed_scenario(core, monkeypatch):
    coordinator, transports = components(core)
    sid, _ = start(coordinator)
    alice = transports["alice"]
    step(alice)
    original = alice.client.request

    def change(*args):
        data, epoch = original(*args)
        if args[1] == "/internal/v1/dh/sessions":
            data["sessions"][0]["scenario"] = "classic"
        return data, epoch

    monkeypatch.setattr(alice.client, "request", change)
    with pytest.raises(InternalError):
        alice.discover()
    assert alice.entries[coordinator.epoch, sid].descriptor.scenario == "authenticated"


@pytest.mark.parametrize("stop", ["cancel", "expiry", "assignment", "epoch"])
def test_authentication_releases_state_and_never_publishes_after_fencing(core, stop):
    coordinator, transports = components(core)
    sid, token = start(coordinator)
    alice = transports["alice"]
    step(alice)
    entry = alice.entries[coordinator.epoch, sid]
    assert entry.authentication is not None and entry.node is not None
    writes = list(alice.client.writes)
    if stop == "cancel":
        coordinator.transition(sid, token, "cancel")
    elif stop in ("expiry", "assignment"):
        with coordinator.access(sid, token=token) as record:
            if stop == "expiry":
                record.deadline = coordinator.clock()
            else:
                record.assignments.pop("alice")
    else:
        alice.client.coordinator = Coordinator()
        alice.heartbeat()
    step(alice)
    alice.work(entry)
    assert entry.disabled and entry.node is entry.authentication is None
    assert alice.client.writes == writes


@pytest.mark.parametrize("bad", ["duplicate", "session", "epoch", "role", "signer", "hash", "field"])
def test_strict_authentication_response(bad):
    keys = [dict(**CONTEXT, owner=role, modulus=3233, public_exponent=17)
            for role in ("alice", "bob")]
    signed = dict(**CONTEXT, signer="alice", transcript_hash="a" * 64, signature=588)
    reports = [dict(**CONTEXT, signer="alice", verifier="bob", transcript_hash="a" * 64,
                    published_transcript_hash="a" * 64, verified=True)]
    data = dict(**CONTEXT, trusted_keys=keys, signatures=[signed, dict(signed, signer="bob")],
                verifications=reports)
    AuthenticationState.model_validate(data)
    if bad == "duplicate":
        keys[1] = keys[0]
    elif bad == "session":
        signed["session_id"] = "a" * 32
    elif bad == "epoch":
        keys[0]["backend_epoch"] = "a" * 32
    elif bad == "role":
        keys[0]["owner"] = "mallory"
    elif bad == "signer":
        reports[0]["signer"] = "bob"
    elif bad == "hash":
        reports[0]["transcript_hash"] = "b" * 64
    else:
        signed["signature"] = "588"
    with pytest.raises(ValidationError):
        AuthenticationState.model_validate(data)
