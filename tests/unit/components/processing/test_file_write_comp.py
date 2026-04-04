"""Tests for nomarr.components.processing.file_write_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.processing.file_write_comp import mark_file_written


class TestMarkFileWritten:
    """Tests for mark_file_written delegation."""

    @pytest.mark.unit
    def test_delegates_to_library_files_set_file_written(self) -> None:
        mock_db = MagicMock()
        mark_file_written(mock_db, "abc123")
        mock_db.library_files.set_file_written.assert_called_once_with("abc123")
