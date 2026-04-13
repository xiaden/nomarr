"""Tests for constructor-backed access to the sessions collection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.filter_types import Op
from nomarr.persistence.constructor import SchemaConstructor
from nomarr.persistence.schema import SCHEMA


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide a mock Arango database handle for constructor tests."""
    return MagicMock()


@pytest.fixture
def sessions_namespace(mock_db: MagicMock):
    """Provide the constructor-backed sessions namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace("sessions", SCHEMA["sessions"])


class TestSessionsCollection:
    """Migration-coverage tests for the sessions constructor namespace."""

    @pytest.mark.unit
    def test_session_lookup_uses_unique_session_id_accessor(self, sessions_namespace, mock_db) -> None:
        """`db.sessions.session_id.get(token)` returns the matching session doc."""
        mock_db.aql.execute.return_value = iter(
            [{"session_id": "token-1", "user_id": "admin", "expiry_timestamp": 12345}],
        )

        assert sessions_namespace.session_id.get("token-1") == {
            "session_id": "token-1",
            "user_id": "admin",
            "expiry_timestamp": 12345,
        }

    @pytest.mark.unit
    def test_expiry_filter_supports_active_session_queries(self, sessions_namespace, mock_db) -> None:
        """`expiry_timestamp.get.in_()` replaces the old active-session scan."""
        mock_db.aql.execute.return_value = iter(
            [{"session_id": "token-1", "user_id": "admin", "expiry_timestamp": 2000}],
        )

        result = sessions_namespace.expiry_timestamp.get.in_({Op.GT: 1000}, limit=5)

        assert result == [{"session_id": "token-1", "user_id": "admin", "expiry_timestamp": 2000}]

    @pytest.mark.unit
    def test_user_delete_returns_deleted_count(self, sessions_namespace, mock_db) -> None:
        """`user_id.delete()` replaces the old delete_user_sessions helper."""
        mock_db.aql.execute.return_value = iter([1, 1])

        assert sessions_namespace.user_id.delete("admin") == 2
