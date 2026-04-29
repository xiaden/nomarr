"""Tests for nomarr.components.library.file_sync_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.file_sync_comp import mark_file_tagged
from nomarr.helpers.constants.file_states import STATE_NOT_TAGGED, STATE_TAGGED


class TestMarkFileTagged:
    """Tests for mark_file_tagged delegation."""

    @pytest.mark.unit
    def test_delegates_to_file_states_transition(self) -> None:
        mock_db = MagicMock()
        mark_file_tagged(mock_db, "library_files/xyz")
        mock_db.file_states.transition.assert_called_once_with(["library_files/xyz"], STATE_NOT_TAGGED, STATE_TAGGED)

    @pytest.mark.unit
    def test_also_updates_last_tagged_at(self) -> None:
        mock_db = MagicMock()
        mark_file_tagged(mock_db, "library_files/xyz")
        mock_db.library_files._id.update.assert_called_once_with("library_files/xyz", mock_db.library_files._id.update.call_args[0][1])
        _, fields = mock_db.library_files._id.update.call_args[0]
        assert "last_tagged_at" in fields
        assert isinstance(fields["last_tagged_at"], int)
