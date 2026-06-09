"""Pipeline completion hook tests for ``nomarr.components.library.scan_lifecycle_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.scan_lifecycle_comp import on_scan_complete_pipeline_hook
from nomarr.helpers.constants.pipeline_states import (
    ML_IN_PROGRESS,
    ML_STATE_FIELD,
    SCAN_COMPLETE,
    SCAN_STATE_FIELD,
)


class TestOnScanCompletePipelineHook:
    """Tests for the post-scan pipeline transition hook."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_scan_axis_to_complete_and_ml_to_in_progress(self) -> None:
        """Libraries with untagged files should move scan axis to complete and ML axis to in_progress."""
        mock_db = MagicMock()
        with (
            patch("nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis") as mock_transition,
            patch(
                "nomarr.components.library.library_file_state_comp.count_untagged_files",
                return_value=5,
            ),
        ):
            on_scan_complete_pipeline_hook(mock_db, "libraries/abc123")

        assert mock_transition.call_count == 2
        mock_transition.assert_any_call(mock_db, "libraries/abc123", SCAN_STATE_FIELD, SCAN_COMPLETE)
        mock_transition.assert_any_call(mock_db, "libraries/abc123", ML_STATE_FIELD, ML_IN_PROGRESS)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_scan_axis_to_complete_when_no_untagged_files(self) -> None:
        """Libraries with no untagged files should move scan axis to complete but ML axis stays."""
        mock_db = MagicMock()
        with (
            patch("nomarr.components.library.scan_lifecycle_comp.transition_pipeline_axis") as mock_transition,
            patch(
                "nomarr.components.library.library_file_state_comp.count_untagged_files",
                return_value=0,
            ),
        ):
            on_scan_complete_pipeline_hook(mock_db, "libraries/abc123")

        mock_transition.assert_called_once_with(mock_db, "libraries/abc123", SCAN_STATE_FIELD, SCAN_COMPLETE)
