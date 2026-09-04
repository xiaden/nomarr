"""Unit tests for key and session management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.session_dataclass import AuthSession
from nomarr.services.infrastructure import keys_svc
from nomarr.services.infrastructure.keys_svc import KeyManagementService

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def clear_session_cache() -> Iterator[None]:
    """Isolate tests from the module-level session cache."""
    keys_svc._session_cache.clear()
    yield
    keys_svc._session_cache.clear()


@pytest.mark.unit
@pytest.mark.mocked
def test_reset_admin_password_revokes_sessions_from_cache_and_database(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Resetting the password invalidates sessions before and after restart."""
    app_db = MagicMock()
    persisted_sessions = [
        AuthSession(token="existing-token", expires_at=4_000_000_000.0, data={"user": "admin"}),
    ]
    app_db.find_active_sessions.side_effect = lambda _: list(persisted_sessions)
    deleted_sessions: list[AuthSession] = []

    def delete_sessions(sessions: list[AuthSession]) -> None:
        deleted_sessions.extend(sessions)
        persisted_sessions.clear()

    app_db.delete_sessions.side_effect = delete_sessions
    db = MagicMock()
    db.app = app_db
    service = KeyManagementService(db)
    keys_svc._session_cache["existing-token"] = 4_000_000_000.0
    # Cache-only token never returned by find_active_sessions — reset must clear the
    # whole cache, not just DB-matched entries.
    keys_svc._session_cache["orphan-cache-token"] = 4_000_000_000.0

    assert service.validate_session("existing-token") is True

    with (
        patch.object(KeyManagementService, "hash_password", return_value="new-hash"),
        caplog.at_level(logging.WARNING, logger="nomarr.services.infrastructure.keys_svc"),
    ):
        service.reset_admin_password("new-password")

    assert service.validate_session("existing-token") is False
    assert keys_svc._session_cache == {}
    # Simulate the live API process retaining its cache while the CLI reset deletes DB rows.
    keys_svc._session_cache["existing-token"] = 4_000_000_000.0
    assert service.validate_session("existing-token") is False
    assert "existing-token" not in keys_svc._session_cache
    # A selective-clear implementation removing only DB-matched tokens would leave this
    # orphan in the cache — reset must evict every entry.
    assert service.validate_session("orphan-cache-token") is False
    assert [session.token for session in deleted_sessions] == ["existing-token"]
    app_db.set_admin_password_hash.assert_called_once_with("new-hash")

    assert "revoked 1 active session(s)" in caplog.text
    assert "new-password" not in caplog.text

    restarted_service = KeyManagementService(db)
    assert restarted_service.load_sessions_from_db() == 0
    assert restarted_service.validate_session("existing-token") is False
    assert app_db.find_active_sessions.call_count == 4
