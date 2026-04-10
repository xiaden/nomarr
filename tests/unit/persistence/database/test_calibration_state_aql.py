"""Tests for CalibrationStateOperations (calibration_state_aql.py)."""

from __future__ import annotations

import pytest

from nomarr.persistence.database.calibration_state_aql import CalibrationStateOperations


@pytest.fixture
def ops(mock_db):
    """Provide CalibrationStateOperations instance."""
    return CalibrationStateOperations(mock_db)


class TestCountRecent:
    """Tests for count_recent()."""

    @pytest.mark.unit
    def test_returns_count_from_aql(self, ops, mock_db) -> None:
        """Returns the scalar count produced by AQL."""
        mock_db.aql.execute.return_value = iter([5])

        result = ops.count_recent(1000)

        assert result == 5

    @pytest.mark.unit
    def test_returns_zero_when_cursor_empty(self, ops, mock_db) -> None:
        """Returns zero when the cursor is empty."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.count_recent(1000)

        assert result == 0

    @pytest.mark.unit
    def test_passes_threshold_as_bind_var(self, ops, mock_db) -> None:
        """Passes the threshold through bind_vars."""
        mock_db.aql.execute.return_value = iter([0])

        ops.count_recent(1000)

        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]
        assert bind_vars == {"threshold": 1000}


class TestGetLatestUpdatedAt:
    """Tests for get_latest_updated_at()."""

    @pytest.mark.unit
    def test_returns_timestamp_when_found(self, ops, mock_db) -> None:
        """Returns the latest updated_at value from the cursor."""
        mock_db.aql.execute.return_value = iter([1_234_567_890])

        result = ops.get_latest_updated_at()

        assert result == 1_234_567_890

    @pytest.mark.unit
    def test_returns_none_when_collection_empty(self, ops, mock_db) -> None:
        """Returns None when no calibration_state documents exist."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.get_latest_updated_at()

        assert result is None
