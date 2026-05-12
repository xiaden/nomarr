"""Tests for nomarr.components.library.file_sync_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.file_sync_comp import mark_file_tagged
from nomarr.helpers.constants.file_states import STATE_NOT_TAGGED, STATE_TAGGED


class TestMarkFileTagged:
    """Tests for mark_file_tagged delegation."""

    @pytest.mark.unit
    @patch("nomarr.components.library.file_sync_comp.persist_last_tagged_at")
    @patch("nomarr.components.library.file_sync_comp.transition_file_state")
    def test_delegates_to_state_transition_and_timestamp_update(
        self,
        mock_transition_file_state: MagicMock,
        mock_persist_last_tagged_at: MagicMock,
    ) -> None:
        mock_db = MagicMock()

        mark_file_tagged(mock_db, "library_files/xyz")

        mock_transition_file_state.assert_called_once_with(
            mock_db,
            ["library_files/xyz"],
            STATE_NOT_TAGGED,
            STATE_TAGGED,
        )
        mock_persist_last_tagged_at.assert_called_once_with(mock_db, "library_files/xyz")
