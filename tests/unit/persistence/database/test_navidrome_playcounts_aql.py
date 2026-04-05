"""Unit tests for NavidromePlaycountsOperations.increment_play (navidrome_playcounts_aql.py).

Mock-based — runs without ArangoDB.
Includes a regression guard for HOTFIX-aql-underscore-identifier (LET removed vs LET _ =).
"""

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.navidrome_playcounts_aql import (
    NavidromePlaycountsOperations,
)


@pytest.fixture
def mock_db():
    """Provide mock ArangoDB."""
    db = MagicMock()
    db.name = "test_db"
    return db


@pytest.fixture
def ops(mock_db):
    """Provide NavidromePlaycountsOperations instance."""
    return NavidromePlaycountsOperations(mock_db)


# ==================================================================
# increment_play
# ==================================================================


class TestIncrementPlay:
    """Tests for NavidromePlaycountsOperations.increment_play."""

    @pytest.mark.unit
    def test_calls_aql_execute(self, ops, mock_db):
        """Calls aql.execute exactly once."""
        ops.increment_play(user_id="alice", nd_id="track1", timestamp_ms=1000)
        assert mock_db.aql.execute.call_count == 1

    @pytest.mark.unit
    def test_bind_vars_contain_track_id(self, ops, mock_db):
        """bind_vars track_id is prefixed with the tracks collection."""
        ops.increment_play(user_id="alice", nd_id="track1", timestamp_ms=1000)
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["track_id"] == "navidrome_tracks/track1"

    @pytest.mark.unit
    def test_bind_vars_contain_user_id(self, ops, mock_db):
        """bind_vars user_id matches the passed argument."""
        ops.increment_play(user_id="bob", nd_id="track2", timestamp_ms=2000)
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["user_id"] == "bob"

    @pytest.mark.unit
    def test_bind_vars_contain_timestamp(self, ops, mock_db):
        """bind_vars timestamp_ms matches the passed argument."""
        ops.increment_play(user_id="alice", nd_id="track3", timestamp_ms=99999)
        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["timestamp_ms"] == 99999

    @pytest.mark.unit
    def test_query_contains_let_removed_not_underscore(self, ops, mock_db):
        """Regression guard: AQL uses LET removed, not the invalid LET _ = syntax."""
        ops.increment_play(user_id="alice", nd_id="track1", timestamp_ms=1000)
        query = mock_db.aql.execute.call_args[0][0]
        assert "LET removed" in query
        assert "LET _ =" not in query

    @pytest.mark.unit
    def test_cursor_close_called(self, ops, mock_db):
        """Cursor is closed after execution."""
        cursor = MagicMock()
        mock_db.aql.execute.return_value = cursor
        ops.increment_play(user_id="alice", nd_id="track1", timestamp_ms=1000)
        cursor.close.assert_called_once_with(ignore_missing=True)
