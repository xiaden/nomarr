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
        """Uses separate read, write, and insert AQL calls."""
        mock_db.aql.execute.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        ops.increment_play(user_id="alice", nd_id="track1", timestamp_ms=1000)
        assert mock_db.aql.execute.call_count == 3

    @pytest.mark.unit
    def test_bind_vars_contain_track_id(self, ops, mock_db):
        """bind_vars track_id is prefixed with the tracks collection."""
        mock_db.aql.execute.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        ops.increment_play(user_id="alice", nd_id="track1", timestamp_ms=1000)
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        insert_bind_vars = mock_db.aql.execute.call_args_list[2][1]["bind_vars"]
        assert read_bind_vars["track_id"] == "navidrome_tracks/track1"
        assert insert_bind_vars["track_id"] == "navidrome_tracks/track1"

    @pytest.mark.unit
    def test_bind_vars_contain_user_id(self, ops, mock_db):
        """bind_vars user_id matches the passed argument."""
        mock_db.aql.execute.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        ops.increment_play(user_id="bob", nd_id="track2", timestamp_ms=2000)
        read_bind_vars = mock_db.aql.execute.call_args_list[0][1]["bind_vars"]
        write_bind_vars = mock_db.aql.execute.call_args_list[1][1]["bind_vars"]
        assert read_bind_vars["user_id"] == "bob"
        assert write_bind_vars["user_id"] == "bob"

    @pytest.mark.unit
    def test_bind_vars_contain_timestamp(self, ops, mock_db):
        """bind_vars timestamp_ms matches the passed argument."""
        mock_db.aql.execute.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        ops.increment_play(user_id="alice", nd_id="track3", timestamp_ms=99999)
        bind_vars = mock_db.aql.execute.call_args_list[2][1]["bind_vars"]
        assert bind_vars["timestamp_ms"] == 99999

    @pytest.mark.unit
    def test_query_contains_let_removed_not_underscore(self, ops, mock_db):
        """Regression guard: split queries do not reintroduce the invalid LET _ = syntax."""
        mock_db.aql.execute.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        ops.increment_play(user_id="alice", nd_id="track1", timestamp_ms=1000)
        queries = [call[0][0] for call in mock_db.aql.execute.call_args_list]
        assert all("LET _ =" not in query for query in queries)

    @pytest.mark.unit
    def test_cursor_close_called(self, ops, mock_db):
        """Each query cursor is closed after execution."""
        read_cursor = MagicMock()
        write_cursor = MagicMock()
        insert_cursor = MagicMock()
        mock_db.aql.execute.side_effect = [read_cursor, write_cursor, insert_cursor]
        ops.increment_play(user_id="alice", nd_id="track1", timestamp_ms=1000)
        read_cursor.close.assert_called_once_with(ignore_missing=True)
        write_cursor.close.assert_called_once_with(ignore_missing=True)
        insert_cursor.close.assert_called_once_with(ignore_missing=True)
