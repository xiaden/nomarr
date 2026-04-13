"""Pipeline completion hook tests for ``nomarr.components.library.scan_lifecycle_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.scan_lifecycle_comp import on_scan_complete_pipeline_hook
from nomarr.helpers.constants.pipeline_states import (
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
        with patch(
            "nomarr.components.library.scan_lifecycle_comp.count_library_files",
            return_value=3,
        ) as mock_count_library_files:
            on_scan_complete_pipeline_hook(mock_db, "libraries/abc123")

        mock_count_library_files.assert_called_once_with(mock_db, "libraries/abc123")
        mock_db.library_pipeline_states.library_key.upsert.assert_called_once_with(
            [{"library_key": "abc123", "pipeline_state": PIPELINE_ML_RUNNING}],
            match_field="library_key",
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_to_idle_when_library_has_no_files(self) -> None:
        """Empty libraries should return to idle after scan completion."""
        mock_db = MagicMock()
        with patch(
            "nomarr.components.library.scan_lifecycle_comp.count_library_files",
            return_value=0,
        ) as mock_count_library_files:
            on_scan_complete_pipeline_hook(mock_db, "libraries/abc123")

        mock_count_library_files.assert_called_once_with(mock_db, "libraries/abc123")
        mock_db.library_pipeline_states.library_key.upsert.assert_called_once_with(
            [{"library_key": "abc123", "pipeline_state": PIPELINE_IDLE}],
            match_field="library_key",
        )
