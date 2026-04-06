"""Pipeline completion hook tests for ``nomarr.components.library.scan_lifecycle_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.scan_lifecycle_comp import on_scan_complete_pipeline_hook
from nomarr.persistence.database.library_pipeline_states_aql import (
    PIPELINE_IDLE,
    PIPELINE_ML_RUNNING,
)


class TestOnScanCompletePipelineHook:
    """Tests for the post-scan pipeline transition hook."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_to_ml_running_when_library_has_files(self) -> None:
        """Libraries with scanned files should move into ML processing."""
        mock_db = MagicMock()
        mock_db.library_files.count_library_files.return_value = 3

        on_scan_complete_pipeline_hook(mock_db, "libraries/abc123")

        mock_db.library_files.count_library_files.assert_called_once_with("libraries/abc123")
        mock_db.library_pipeline_states.transition_state.assert_called_once_with(
            "libraries/abc123",
            PIPELINE_ML_RUNNING,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_to_idle_when_library_has_no_files(self) -> None:
        """Empty libraries should return to idle after scan completion."""
        mock_db = MagicMock()
        mock_db.library_files.count_library_files.return_value = 0

        on_scan_complete_pipeline_hook(mock_db, "libraries/abc123")

        mock_db.library_files.count_library_files.assert_called_once_with("libraries/abc123")
        mock_db.library_pipeline_states.transition_state.assert_called_once_with(
            "libraries/abc123",
            PIPELINE_IDLE,
        )
