"""Tests for nomarr.components.library.file_sync_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.file_sync_comp import mark_file_tagged


class TestMarkFileTagged:
    """Tests for mark_file_tagged delegation."""

    @pytest.mark.unit
    def test_delegates_to_file_states_set_tagged(self) -> None:
        mock_db = MagicMock()
        mark_file_tagged(mock_db, "library_files/xyz")
        mock_db.file_states.set_tagged.assert_called_once_with("library_files/xyz")
