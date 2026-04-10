"""Tests for nomarr.components.library.validate_scan_state_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.validate_scan_state_comp import (
    ValidationStats,
    _heal_short_files,
    validate_unchanged_files,
)


class TestHealShortFiles:
    """Tests for _heal_short_files."""

    @pytest.mark.unit
    def test_no_short_files_returns_zero(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.find_short_files_missing_too_short.return_value = []
        result = _heal_short_files(mock_db, "libraries/1", 30)
        assert result == 0
        mock_db.file_states.set_too_short.assert_not_called()

    @pytest.mark.unit
    def test_short_files_calls_set_too_short_for_each(self) -> None:
        mock_db = MagicMock()
        file_ids = ["library_files/a", "library_files/b"]
        mock_db.file_states.find_short_files_missing_too_short.return_value = file_ids
        result = _heal_short_files(mock_db, "libraries/1", 30)
        assert result == 2
        assert mock_db.file_states.set_too_short.call_count == 2
        for fid in file_ids:
            mock_db.file_states.set_too_short.assert_any_call(fid)

    @pytest.mark.unit
    def test_query_uses_outbound_library_edge_traversal(self) -> None:
        """Delegate to persistence layer with correct library_id and min_duration_s."""
        mock_db = MagicMock()
        mock_db.file_states.find_short_files_missing_too_short.return_value = []

        _heal_short_files(mock_db, "libraries/1", 30)

        mock_db.file_states.find_short_files_missing_too_short.assert_called_once_with("libraries/1", 30)


class TestValidateUnchangedFiles:
    """Tests for validate_unchanged_files."""

    @pytest.mark.unit
    def test_returns_validation_stats(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.find_short_files_missing_too_short.return_value = []
        result = validate_unchanged_files(mock_db, "libraries/1", 30)
        assert isinstance(result, ValidationStats)
        assert result.short_files_healed == 0
        assert result.files_checked == 0

    @pytest.mark.unit
    def test_logs_when_healed_greater_than_zero(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_db = MagicMock()
        mock_db.file_states.find_short_files_missing_too_short.return_value = ["library_files/x"]
        import logging

        with caplog.at_level(logging.INFO):
            result = validate_unchanged_files(mock_db, "libraries/1", 30)
        assert result.short_files_healed == 1
        assert "Healed 1 short files" in caplog.text
