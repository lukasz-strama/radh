"""#71 / G01: równoległe sesje normal i MITM na rzeczywistych procesach ról.

Kryteria: automatyczny test dwóch równoległych sesji przechodzi; testy potwierdzają
izolację wiadomości, diagnostyki i zdarzeń między sesjami.
"""

from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from helpers.multi_session_stack import ROLES, Owned, assert_no_secrets_in, bearer, expected_keys

pytestmark = pytest.mark.live

NORMAL_EVENTS = ["session_created", "session_started", "public_value", "public_value",
                 "message_processed", "message_processed", "session_completed"]
MITM_EVENTS = ["session_created", "session_started", "message_intercepted", "message_intercepted",
               "message_forwarded", "message_forwarded", "message_processed",
               "message_processed", "session_completed"]


def _assert_completed_session(stack, owned: Owned, mode: str, prime: int, generator: int):
    view = stack.wait_status(owned, "completed")
    assert (view["session_id"], view["mode"], view["prime"], view["generator"]) == (
        owned.session_id, mode, prime, generator)
    assert view["participants"] == {"alice": "received", "bob": "received"}
    assert view["failure_code"] is None and view["terminal_at"] is not None
    assert {m["message_id"] for m in view["messages"]} == {"alice-public", "bob-public"}
    for message in view["messages"]:
        assert 1 <= message["public_value"] < prime
        assert message["status"] == "processed"

    events = stack.events(owned)
    types = [e["type"] for e in events]
    # Kolejność między wiadomościami może się przeplatać (np. forward alice-public
    # przed przechwyceniem bob-public); stałe są: zbiór zdarzeń, początek/koniec
    # i przyczynowość w obrębie jednego message_id.
    assert sorted(types) == sorted(MITM_EVENTS if mode == "mitm" else NORMAL_EVENTS)
    assert types[:2] == ["session_created", "session_started"]
    assert types[-1] == "session_completed"
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    for mid in ("alice-public", "bob-public"):
        chain = [e["type"] for e in events if e.get("message_id") == mid]
        assert chain == (["message_intercepted", "message_forwarded", "message_processed"]
                         if mode == "mitm" else ["public_value", "message_processed"])

    keys = expected_keys(view)
    diagnostics = stack.wait_diagnostics(owned)
    assert diagnostics == keys, "K z C różni się od wartości wyliczonej z publicznych liczb"
    mallory = stack.diagnostics(owned, mallory=True)
    if mode == "mitm":
        assert {i["original_sender"] for i in view["interceptions"]} == {"alice", "bob"}
        for interception in view["interceptions"]:
            assert interception["actual_sender"] == "mallory"
            assert interception["status"] == "processed"
        mallory = stack.wait_diagnostics(owned, mallory=True)
        assert mallory == {"shared_with_alice": keys["alice"], "shared_with_bob": keys["bob"]}
    else:
        assert view["interceptions"] == []
        assert mallory == {"shared_with_alice": None, "shared_with_bob": None}
    text = str(view) + str(events)
    assert "shared" not in str(view) and "session_token" not in text
    assert_no_secrets_in(text, owned.token, owned.create_key)
    return view, events


def test_two_parallel_sessions_normal_and_mitm_are_isolated(stack):
    """Dwóch użytkowników (osobne klienty HTTP) tworzy i startuje sesje równolegle."""
    pids = {role: stack.nodes[role].pid for role in ROLES}
    assert len(set(pids.values()) | {stack.backend.pid}) == 4
    specs = [("normal", 467, 2), ("mitm", 503, 5)]
    users = [httpx.Client(base_url=stack.url, timeout=5) for _ in specs]
    try:
        def create_and_start(index):
            mode, prime, generator = specs[index]
            owned = stack.create(mode, prime, generator, client=users[index])
            stack.start(owned, client=users[index])
            return owned

        with ThreadPoolExecutor(2) as pool:
            sessions = list(pool.map(create_and_start, range(2)))
        assert sessions[0].session_id != sessions[1].session_id
        assert sessions[0].token != sessions[1].token

        views = {}
        for owned, (mode, prime, generator) in zip(sessions, specs):
            views[mode], _ = _assert_completed_session(stack, owned, mode, prime, generator)

        # Sesja normal nie ma przechwyceń; każda wiadomość należy do własnego p/g.
        assert views["normal"]["interceptions"] == []
        assert len(views["mitm"]["interceptions"]) == 2
        assert views["normal"]["backend_epoch"] == views["mitm"]["backend_epoch"]

        # Właściciel A nie widzi B i odwrotnie (pełna macierz w test_ms_authorization).
        for owner, other in ((sessions[0], sessions[1]), (sessions[1], sessions[0])):
            for suffix in ("", "/events", "/diagnostics", "/diagnostics/mallory"):
                response = users[0].get(other.path + suffix, headers=bearer(owner.token))
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"
    finally:
        for user in users:
            user.close()

    # Jeden proces na rolę przez cały test — brak procesu per sesja.
    assert {role: stack.nodes[role].pid for role in ROLES} == pids
    assert all(stack.nodes[role].poll() is None for role in ROLES)
    log = stack.all_logs()
    for owned in sessions:
        assert_no_secrets_in(log, owned.token, owned.create_key)
    assert_no_secrets_in(log, *stack.tokens.values())


def test_twenty_concurrent_sessions_ten_normal_ten_mitm(make_stack):
    """G01 (lokalnie): 10 normal + 10 MITM równocześnie, trzy procesy, różne p.

    Konfiguracja testowa podnosi wyłącznie limity tworzenia z jednego IP
    (wszyscy klienci testu mają 127.0.0.1); pozostałe limity są domyślne.
    """
    stack = make_stack(env={"CREATE_RATE_PER_MINUTE": 600, "CREATE_RATE_BURST": 32,
                            "MAX_SESSIONS_PER_IP": 32})
    primes = [467, 479, 487, 491, 499, 503, 509, 521, 523, 541,
              547, 557, 563, 569, 571, 577, 587, 593, 599, 601]
    specs = [("normal" if i % 2 == 0 else "mitm", p, 2 if p % 8 in (1, 7) else 5)
             for i, p in enumerate(primes)]

    def create_and_start(spec):
        with httpx.Client(base_url=stack.url, timeout=10) as user:
            owned = stack.create(spec[0], spec[1], spec[2], client=user)
            stack.start(owned, client=user)
            return owned

    with ThreadPoolExecutor(20) as pool:
        sessions = list(pool.map(create_and_start, specs))
    assert len({s.session_id for s in sessions}) == 20
    assert len({s.token for s in sessions}) == 20

    for owned, (mode, prime, generator) in zip(sessions, specs):
        view, events = _assert_completed_session(stack, owned, mode, prime, generator)
        assert all(e.get("public_value") is None or e["public_value"] < prime for e in events)
    assert all(stack.nodes[role].poll() is None for role in ROLES)


def test_messages_ids_are_scoped_per_session(make_stack):
    """Te same deterministyczne message_id w dwóch sesjach nie kolidują (#73 §4)."""
    stack = make_stack()
    first = stack.create("normal", 23, 5)
    second = stack.create("normal", 23, 5)
    stack.start(first)
    stack.start(second)
    a = stack.wait_status(first, "completed")
    b = stack.wait_status(second, "completed")
    assert [m["message_id"] for m in a["messages"]] == [m["message_id"] for m in b["messages"]]
    assert stack.wait_diagnostics(first) == expected_keys(a)
    assert stack.wait_diagnostics(second) == expected_keys(b)
    assert len(stack.events(first)) == len(stack.events(second)) == len(NORMAL_EVENTS)
