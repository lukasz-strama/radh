"""#71 / G05, G07–G09: idempotencja tworzenia i ograniczenia zasobów.

Testy z domyślnymi limitami sprawdzają wartości kontraktu (#73 §5). Testy
pojemności obniżają limity przez zmienne Settings — to konfiguracja testowa,
nie zmiana domyślnych zabezpieczeń.
"""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from helpers.multi_session_stack import new_key, rss_kib

pytestmark = pytest.mark.live

BODY = {"prime": 23, "generator": 5, "mode": "normal", "diagnostics_enabled": False}


def code(response):
    return response.status_code, response.json()["error"]["code"]


def test_default_create_rate_limits_retries_too(make_stack):
    """6/min/IP, burst 2 — obejmuje także retry tym samym kluczem (trafienie w cache)."""
    stack = make_stack(nodes=False)
    key = new_key()
    first = stack.create_raw(BODY, key=key)
    retry = stack.create_raw(BODY, key=key)
    assert first.status_code == retry.status_code == 201
    assert first.json() == retry.json()
    limited = stack.create_raw(BODY, key=key)
    assert code(limited) == (429, "RATE_LIMITED")
    wait = int(limited.headers["retry-after"])
    assert 1 <= wait <= 10
    assert code(stack.create_raw(BODY)) == (429, "RATE_LIMITED")
    time.sleep(wait)
    again = stack.create_raw(BODY, key=key)
    assert again.status_code == 201 and again.json() == first.json()


def test_hundred_parallel_retries_return_one_session(make_stack):
    """G05: 100 ponowień w <60 s przy jawnie podniesionych limitach testowych."""
    stack = make_stack(nodes=False, env={"CREATE_RATE_PER_MINUTE": 6000, "CREATE_RATE_BURST": 128})
    key, epoch = new_key(), stack.epoch()
    with ThreadPoolExecutor(16) as pool:
        responses = list(pool.map(lambda _: stack.create_raw(BODY, key=key, epoch=epoch), range(100)))
    assert {r.status_code for r in responses} == {201}
    assert len({(r.json()["session"]["session_id"], r.json()["session_token"]) for r in responses}) == 1
    created = responses[0].json()
    sid, token = created["session"]["session_id"], created["session_token"]
    events = stack.http.get(f"/api/v2/dh/sessions/{sid}/events",
                            headers={"Authorization": "Bearer " + token}).json()["events"]
    assert [e["type"] for e in events] == ["session_created"]
    assert code(stack.create_raw({**BODY, "prime": 29}, key=key)) == (409, "IDEMPOTENCY_CONFLICT")
    assert stack.http.delete(f"/api/v2/dh/sessions/{sid}",
                             headers={"Authorization": "Bearer " + token}).status_code == 204
    assert code(stack.create_raw(BODY, key=key)) == (410, "CREATION_GONE")


def test_create_retry_cache_expires(make_stack):
    stack = make_stack(nodes=False, env={"CREATE_RETRY_TTL_SECONDS": 2, "CREATE_RATE_BURST": 4})
    key = new_key()
    assert stack.create_raw(BODY, key=key).status_code == 201
    time.sleep(2.5)
    assert code(stack.create_raw(BODY, key=key)) == (409, "CREATE_RETRY_EXPIRED")


@pytest.mark.parametrize("headers,body,expected", [
    ({"Idempotency-Key": None}, BODY, (400, "BAD_REQUEST")),
    ({"X-Backend-Epoch": None}, BODY, (400, "BAD_REQUEST")),
    ({"Idempotency-Key": "short"}, BODY, (400, "BAD_REQUEST")),
    ({"X-Backend-Epoch": "0" * 32}, BODY, (409, "BACKEND_EPOCH_MISMATCH")),
    ({}, {"prime": 24, "generator": 5}, (422, "INVALID_PRIME")),
    ({}, {"prime": 23, "generator": 23}, (422, "INVALID_GENERATOR")),
    ({}, {"prime": "23", "generator": 5}, (422, "INVALID_REQUEST")),
    ({}, {"prime": 23, "generator": 5, "mode": "evil"}, (422, "INVALID_REQUEST")),
    ({}, {"prime": 23, "generator": 5, "session_id": "a" * 32}, (422, "INVALID_REQUEST")),
    ({}, {"prime": 23, "generator": 5, "diagnostics_enabled": 1}, (422, "INVALID_REQUEST")),
])
def test_invalid_create_requests_create_nothing(make_stack, headers, body, expected):
    stack = make_stack(nodes=False, env={"CREATE_RATE_BURST": 8})
    sent = {"Idempotency-Key": new_key(), "X-Backend-Epoch": stack.epoch(), **headers}
    sent = {k: v for k, v in sent.items() if v is not None}
    response = stack.http.post("/api/v2/dh/sessions", json=body, headers=sent)
    assert code(response) == expected
    # Ta sama próba nie zostawia obiektu: poprawne tworzenie z nowym kluczem działa.
    assert stack.create_raw(BODY).status_code == 201


def test_body_size_and_media_type_limits(make_stack):
    stack = make_stack(nodes=False)
    headers = {"Idempotency-Key": new_key(), "X-Backend-Epoch": stack.epoch(),
               "Content-Type": "application/json"}
    big = b'{"prime":23,"generator":5,"pad":"' + b"x" * 5000 + b'"}'
    assert code(stack.http.post("/api/v2/dh/sessions", content=big, headers=headers)) == (
        413, "REQUEST_TOO_LARGE")
    headers["Content-Type"] = "text/plain"
    assert code(stack.http.post("/api/v2/dh/sessions", content=b'{"prime":23,"generator":5}',
                                headers=headers)) == (415, "UNSUPPORTED_MEDIA_TYPE")


def test_global_session_capacity(make_stack):
    """129. rekord → 503 SESSION_CAPACITY (tu MAX_SESSIONS=3); istniejące nietknięte."""
    stack = make_stack(nodes=False, env={"MAX_SESSIONS": 3, "MAX_RUNNING_SESSIONS": 2,
                                         "CREATE_RATE_BURST": 8})
    sessions = [stack.create() for _ in range(3)]
    full = stack.create_raw(BODY)
    assert code(full) == (503, "SESSION_CAPACITY")
    assert full.headers["retry-after"] == "5"
    assert all(stack.get(s)["status"] == "created" for s in sessions)
    assert stack.http.delete(sessions[0].path, headers=sessions[0].auth).status_code == 204
    assert stack.create_raw(BODY).status_code == 201


def test_sessions_per_ip_limit(make_stack):
    stack = make_stack(nodes=False, env={"MAX_SESSIONS_PER_IP": 2, "CREATE_RATE_BURST": 8})
    first, second = stack.create(), stack.create()
    assert code(stack.create_raw(BODY)) == (429, "RATE_LIMITED")
    # Anulowana sesja nie liczy się do aktywnych created/running tego IP.
    assert stack.http.post(first.path + "/cancel", headers=first.auth).status_code == 200
    assert stack.create_raw(BODY).status_code == 201
    assert stack.get(second)["status"] == "created"


def test_running_capacity_and_fair_continuation(make_stack):
    """33. start → 503 RUNNING_CAPACITY (tu limit 2); pozostałe running działają dalej."""
    stack = make_stack(nodes=False, env={"MAX_RUNNING_SESSIONS": 2, "CREATE_RATE_BURST": 8})
    alice, bob = stack.node("alice").register(), stack.node("bob").register()
    a, b, c = stack.create("normal", 467, 2), stack.create("normal", 479, 13), stack.create()
    stack.start(a)
    stack.start(b)
    busy = stack.http.post(c.path + "/start", headers=c.auth)
    assert code(busy) == (503, "RUNNING_CAPACITY")
    assert busy.headers["retry-after"] == "5"
    assert stack.get(c)["status"] == "created"
    sid, view = a.session_id, stack.get(a)
    assert alice.publish(sid, view).status_code == 200
    assert bob.publish(sid, view).status_code == 200
    assert alice.ack(sid, "bob-public").status_code == 200
    assert bob.ack(sid, "alice-public").status_code == 200
    assert stack.get(a)["status"] == "completed"
    assert stack.start(c)["status"] == "running"
    assert stack.get(b)["status"] == "running"


def test_public_read_rate_limit_per_token(make_stack):
    """120 odczytów/min/token: 121. odczyt → 429 z Retry-After, inny token działa."""
    stack = make_stack(nodes=False)
    hot, other = stack.create(), stack.create()
    statuses = [stack.http.get(hot.path, headers=hot.auth).status_code for _ in range(121)]
    assert statuses[:120] == [200] * 120 and statuses[120] == 429
    limited = stack.http.get(hot.path, headers=hot.auth)
    assert code(limited) == (429, "RATE_LIMITED") and int(limited.headers["retry-after"]) >= 1
    assert stack.http.get(other.path, headers=other.auth).status_code == 200


def test_events_pagination_bounds(make_stack):
    stack = make_stack(nodes=False)
    owned = stack.create()
    for query in ("limit=0", "limit=33", "after=-1", "limit=x"):
        assert code(stack.http.get(owned.path + "/events?" + query, headers=owned.auth)) == (
            422, "INVALID_REQUEST")
    page = stack.http.get(owned.path + "/events?after=1&limit=1", headers=owned.auth).json()
    assert page["events"] == [] and page["next_after"] == 1


def test_tombstones_are_bounded(make_stack):
    """MAX_TOMBSTONES (tu 2): najstarszy tombstone wypada → 404 zamiast 410."""
    stack = make_stack(nodes=False, env={"MAX_TOMBSTONES": 2, "CREATE_RATE_BURST": 8})
    sessions = [stack.create() for _ in range(3)]
    for owned in sessions:
        assert stack.http.delete(owned.path, headers=owned.auth).status_code == 204
    assert code(stack.http.get(sessions[0].path, headers=sessions[0].auth)) == (404, "SESSION_NOT_FOUND")
    for owned in sessions[1:]:
        assert code(stack.http.get(owned.path, headers=owned.auth)) == (410, "SESSION_EXPIRED")


def test_thousand_create_delete_cycles_keep_memory_bounded(make_stack):
    """G07/G22 (lokalnie): 1000 create/delete; RSS backendu nie rośnie liniowo."""
    stack = make_stack(nodes=False, env={"CREATE_RATE_PER_MINUTE": 100000, "CREATE_RATE_BURST": 128,
                                         "READ_IP_RATE_PER_MINUTE": 100000})

    def cycles(count):
        for _ in range(count):
            owned = stack.create(diagnostics=False)
            assert stack.http.delete(owned.path, headers=owned.auth).status_code == 204

    cycles(200)  # rozgrzewka: ustalenie pul alokatora i map do pełnych limitów
    baseline = rss_kib(stack.backend.pid)
    started = time.monotonic()
    cycles(1000)
    elapsed = time.monotonic() - started
    growth = rss_kib(stack.backend.pid) - baseline
    print(f"1000 create/delete: {elapsed:.1f} s, wzrost RSS {growth} KiB")
    assert growth < 8 * 1024, f"RSS wzrósł o {growth} KiB po 1000 cyklach"
    # Po cyklach backend nadal przyjmuje nowe sesje (brak wycieku pojemności).
    assert stack.create().session_id
