"""Unit tests for worker idle-path pipeline integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dto.health_dto import PIPELINE_FRAME_PREFIX
from nomarr.helpers.dto.processing_dto import ProcessorConfig
from nomarr.services.infrastructure.config_svc import INTERNAL_CALIBRATION_MIN_FILES

pytestmark = [pytest.mark.unit, pytest.mark.mocked]


@pytest.fixture
def processor_config() -> ProcessorConfig:
    """Provide a minimal processor config for WorkerSystemService construction."""
    return ProcessorConfig(
        models_dir="/mock/models",
        min_duration_s=30,
        allow_short=False,
        batch_size=11,
        namespace="nom",
        version_tag_key="nom_version",
        tagger_version="test",
    )


@pytest.fixture
def worker_db() -> MagicMock:
    """Provide a mocked database handle with worker connection metadata."""
    db = MagicMock()
    db.hosts = "http://localhost:8529"
    db.password = "test"
    db.meta = MagicMock()
    db.worker_restart_policy = MagicMock()
    db.worker_restart_policy.component_id.get.return_value = None
    return db


class TestIdlePipelineCompletion:
    """Tests for discovery worker idle-path pipeline completion checks."""

    def test_transitions_completed_libraries_and_signals_parent(
        self,
        worker_db: MagicMock,
    ) -> None:
        """Completed ML libraries should advance state and emit one pipeline trigger."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        completed = [
            {"library_id": "libraries/large", "tagged_count": INTERNAL_CALIBRATION_MIN_FILES},
            {"library_id": "libraries/small", "tagged_count": INTERNAL_CALIBRATION_MIN_FILES - 1},
        ]
        health_pipe = MagicMock()

        with (
            patch(
                "nomarr.components.library.library_records_comp.find_ml_complete_libraries",
                return_value=completed,
            ) as mock_find_ml_complete_libraries,
            patch("nomarr.components.library.library_scan_state_comp.transition_pipeline_axis") as mock_transition,
        ):
            transitions = _check_idle_pipeline_completion(worker_db, health_pipe)

        assert transitions == 2
        mock_find_ml_complete_libraries.assert_called_once_with(worker_db, INTERNAL_CALIBRATION_MIN_FILES)
        # Should transition ML axis to ML_processed and calibration axis to not_calibrated
        # Large library gets both ML and CAL transitions (3 calls total: 2 for large, 1 for small)
        assert mock_transition.call_count == 3
        health_pipe.send.assert_called_once_with(PIPELINE_FRAME_PREFIX + "calibration_trigger")

    def test_empty_completed_list_does_not_emit_pipeline_signal(
        self,
        worker_db: MagicMock,
    ) -> None:
        """Idle-path checks with no completed libraries should be a no-op."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        health_pipe = MagicMock()

        with (
            patch(
                "nomarr.components.library.library_records_comp.find_ml_complete_libraries",
                return_value=[],
            ),
            patch("nomarr.components.library.library_scan_state_comp.transition_pipeline_axis") as mock_transition,
        ):
            transitions = _check_idle_pipeline_completion(worker_db, health_pipe)

        assert transitions == 0
        mock_transition.assert_not_called()
        health_pipe.send.assert_not_called()

    def test_transitions_libraries_and_returns_count_when_health_pipe_is_none(
        self,
        worker_db: MagicMock,
    ) -> None:
        """Completed libraries should still transition when no health pipe is available."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        completed = [
            {"library_id": "libraries/large", "tagged_count": INTERNAL_CALIBRATION_MIN_FILES},
            {"library_id": "libraries/small", "tagged_count": INTERNAL_CALIBRATION_MIN_FILES - 1},
        ]

        with (
            patch(
                "nomarr.components.library.library_records_comp.find_ml_complete_libraries",
                return_value=completed,
            ) as mock_find_ml_complete_libraries,
            patch("nomarr.components.library.library_scan_state_comp.transition_pipeline_axis") as mock_transition,
        ):
            transitions = _check_idle_pipeline_completion(worker_db, None)

        assert transitions == 2
        mock_find_ml_complete_libraries.assert_called_once_with(worker_db, INTERNAL_CALIBRATION_MIN_FILES)
        # Should transition ML axis to ML_processed and calibration axis to not_calibrated
        # Large library gets both ML and CAL transitions (3 calls total: 2 for large, 1 for small)
        assert mock_transition.call_count == 3

    def test_broken_pipe_error_on_send_is_swallowed(
        self,
        worker_db: MagicMock,
    ) -> None:
        """Broken pipe errors during trigger emission should not interrupt transitions."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        completed = [{"library_id": "libraries/large", "tagged_count": INTERNAL_CALIBRATION_MIN_FILES}]
        health_pipe = MagicMock()
        health_pipe.send.side_effect = BrokenPipeError("pipe closed")

        with (
            patch(
                "nomarr.components.library.library_records_comp.find_ml_complete_libraries",
                return_value=completed,
            ) as mock_find_ml_complete_libraries,
            patch("nomarr.components.library.library_scan_state_comp.transition_pipeline_axis") as mock_transition,
        ):
            transitions = _check_idle_pipeline_completion(worker_db, health_pipe)

        assert transitions == 1
        mock_find_ml_complete_libraries.assert_called_once_with(worker_db, INTERNAL_CALIBRATION_MIN_FILES)
        # Should still transition despite broken pipe
        assert mock_transition.call_count == 2  # 1 library x 2 axes
