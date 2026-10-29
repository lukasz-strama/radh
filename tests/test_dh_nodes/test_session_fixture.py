"""Regresja przywracania dynamicznego State po zakończeniu fixture sesji."""

from contextlib import contextmanager, nullcontext

from app.main import app
from app.session_models import CreateSession
from tests.test_dh_nodes.test_sessions import api


def test_api_fixture_isolates_stores_and_restores_application_state(monkeypatch):
    # Sprawdzamy cykl życia fixture; żądania HTTP mają osobne testy.
    monkeypatch.setattr("test_sessions.TestClient", lambda application: nullcontext())
    original_state = app.state
    original_sessions = app.state.dh_sessions
    original_presence = app.state.dh_presence
    previous_stores = []

    for _ in range(2):
        with contextmanager(api.__wrapped__)(monkeypatch):
            sessions = app.state.dh_sessions
            presence = app.state.dh_presence
            assert sessions is not original_sessions
            assert presence is not original_presence
            assert all(sessions is not old[0] and presence is not old[1]
                       for old in previous_stores)
            assert sessions.session is None and sessions.used_ids == set()
            assert all(node.last_seen is None for node in presence.snapshot().values())
            sessions.create(CreateSession(session_id="ref", prime=23, generator=5))
            presence.heartbeat("alice")
            previous_stores.append((sessions, presence))

        assert app.state is original_state
        assert app.state.dh_sessions is original_sessions
        assert app.state.dh_presence is original_presence
