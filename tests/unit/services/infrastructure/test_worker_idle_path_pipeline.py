"""Unit tests for worker idle-path pipeline integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
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
            {
                "library": Library(name="large", root_path="/music/large"),
                "tagged_count": INTERNAL_CALIBRATION_MIN_FILES,
            },
            {
                "library": Library(name="small", root_path="/music/small"),
                "tagged_count": INTERNAL_CALIBRATION_MIN_FILES - 1,
            },
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
            {
                "library": Library(name="large", root_path="/music/large"),
                "tagged_count": INTERNAL_CALIBRATION_MIN_FILES,
            },
            {
                "library": Library(name="small", root_path="/music/small"),
                "tagged_count": INTERNAL_CALIBRATION_MIN_FILES - 1,
            },
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

    def test_real_transition_path_updates_state_and_emits_trigger(
        self,
        worker_db: MagicMock,
    ) -> None:
        """The idle path passes a domain Library through the real transition logic."""
        from nomarr.helpers.constants.pipeline_states import (
            CAL_NOT_CALIBRATED,
            CAL_STATE_FIELD,
            ML_COMPLETE,
            ML_STATE_FIELD,
        )
        from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryPipelineState
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        library = Library(name="large", root_path="/music/large")
        state = LibraryPipelineState(
            scan_state="scanned",
            ml_state="ML_processing",
            calibration_state="calibrating",
            tag_write_state="not_written",
        )
        worker_db.library.get_pipeline_state.return_value = state
        worker_db.library.set_pipeline_axis.side_effect = lambda received, axis, next_state: self._set_pipeline_axis(
            received, axis, next_state, worker_db
        )
        health_pipe = MagicMock()

        with patch(
            "nomarr.components.library.library_records_comp.find_ml_complete_libraries",
            return_value=[{"library": library, "tagged_count": INTERNAL_CALIBRATION_MIN_FILES}],
        ):
            transitions = _check_idle_pipeline_completion(worker_db, health_pipe)

        assert transitions == 1
        assert worker_db.library.get_pipeline_state.call_count == 2
        assert worker_db.library.get_pipeline_state.call_args_list[0].args == (library,)
        assert worker_db.library.set_pipeline_axis.call_args_list == [
            ((library, ML_STATE_FIELD, ML_COMPLETE), {}),
            ((library, CAL_STATE_FIELD, CAL_NOT_CALIBRATED), {}),
        ]
        health_pipe.send.assert_called_once_with(PIPELINE_FRAME_PREFIX + "calibration_trigger")

    @staticmethod
    def _set_pipeline_axis(
        library: Library,
        axis: str,
        next_state: str,
        db: MagicMock,
    ) -> None:
        """Apply the facade write in the in-memory integration fixture."""
        from nomarr.helpers.constants.pipeline_states import ML_STATE_FIELD

        assert isinstance(library, Library)
        current = db.library.get_pipeline_state.return_value
        if axis == ML_STATE_FIELD:
            db.library.get_pipeline_state.return_value = current.__class__(
                scan_state=current.scan_state,
                ml_state=next_state,
                calibration_state=current.calibration_state,
                tag_write_state=current.tag_write_state,
            )
        else:
            db.library.get_pipeline_state.return_value = current.__class__(
                scan_state=current.scan_state,
                ml_state=current.ml_state,
                calibration_state=next_state,
                tag_write_state=current.tag_write_state,
            )

    def test_broken_pipe_error_on_send_is_swallowed(
        self,
        worker_db: MagicMock,
    ) -> None:
        """Broken pipe errors during trigger emission should not interrupt transitions."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        library = Library(name="large", root_path="/music/large")
        health_pipe = MagicMock()
        health_pipe.send.side_effect = BrokenPipeError("pipe closed")

        with (
            patch(
                "nomarr.components.library.library_records_comp.find_ml_complete_libraries",
                return_value=[{"library": library, "tagged_count": INTERNAL_CALIBRATION_MIN_FILES}],
            ),
            patch("nomarr.components.library.library_scan_state_comp.transition_pipeline_axis") as mock_transition,
        ):
            transitions = _check_idle_pipeline_completion(worker_db, health_pipe)

        assert transitions == 1
        assert mock_transition.call_count == 2

    def test_failed_library_does_not_abort_other_completions(
        self,
        worker_db: MagicMock,
    ) -> None:
        """A stale library should not prevent later libraries from completing."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        stale = Library(name="stale", root_path="/music/stale")
        live = Library(name="live", root_path="/music/live")
        completed = [
            {"library": stale, "tagged_count": 0},
            {"library": live, "tagged_count": INTERNAL_CALIBRATION_MIN_FILES},
        ]
        health_pipe = MagicMock()
        transition = MagicMock(side_effect=[LookupError("library deleted"), None, None])

        with (
            patch(
                "nomarr.components.library.library_records_comp.find_ml_complete_libraries",
                return_value=completed,
            ),
            patch(
                "nomarr.components.library.library_scan_state_comp.transition_pipeline_axis",
                transition,
            ),
        ):
            transitions = _check_idle_pipeline_completion(worker_db, health_pipe)

        assert transitions == 1
        assert transition.call_count == 3
        health_pipe.send.assert_called_once_with(PIPELINE_FRAME_PREFIX + "calibration_trigger")
