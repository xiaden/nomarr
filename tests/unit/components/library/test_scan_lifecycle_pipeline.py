"""Pipeline completion hook tests for ``nomarr.components.library.scan_lifecycle_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.scan_lifecycle_comp import on_scan_complete_pipeline_hook
from nomarr.helpers.constants.pipeline_states import (
    ML_IN_PROGRESS,
    ML_NOT_PROCESSED,
    ML_STATE_FIELD,
)


class TestOnScanCompletePipelineHook:
    """Tests for the post-scan pipeline transition hook."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_ml_axis_when_files_exist(self) -> None:
        """Libraries with files should move ML axis to in_progress."""
        mock_db = MagicMock()
        mock_db.library.list_library_file_ids.return_value = ["f1", "f2"]
        with patch("nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis") as mock_transition:
            on_scan_complete_pipeline_hook(mock_db, "libraries/abc123")

        mock_transition.assert_called_once_with(mock_db, "libraries/abc123", ML_STATE_FIELD, ML_IN_PROGRESS)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_ml_axis_when_no_files(self) -> None:
        """Libraries with no files should move ML axis to not_processed."""
        mock_db = MagicMock()
        mock_db.library.list_library_file_ids.return_value = []
        with patch("nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis") as mock_transition:
            on_scan_complete_pipeline_hook(mock_db, "libraries/abc123")

        mock_transition.assert_called_once_with(mock_db, "libraries/abc123", ML_STATE_FIELD, ML_NOT_PROCESSED)
