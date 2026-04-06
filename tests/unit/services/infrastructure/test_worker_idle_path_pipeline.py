"""Unit tests for worker idle-path pipeline integration."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from nomarr.helpers.dto.health_dto import PIPELINE_FRAME_PREFIX, ComponentPolicy
from nomarr.helpers.dto.processing_dto import ProcessorConfig
from nomarr.persistence.database.library_pipeline_states_aql import (
    PIPELINE_AWAITING_CALIBRATION,
    PIPELINE_TOO_SMALL,
)
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
    db.worker_restart_policy.get_restart_state.return_value = (0, None)
    return db


class TestIdlePipelineCompletion:
    """Tests for discovery worker idle-path pipeline completion checks."""

    def test_transitions_completed_libraries_and_signals_parent(
        self,
        worker_db: MagicMock,
    ) -> None:
        """Completed ML libraries should advance state and emit one pipeline trigger."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        mock_pipeline_states = worker_db.library_pipeline_states
        mock_pipeline_states.find_ml_complete_libraries.return_value = [
            {
                "library_id": "libraries/large",
                "tagged_count": INTERNAL_CALIBRATION_MIN_FILES,
            },
            {
                "library_id": "libraries/small",
                "tagged_count": INTERNAL_CALIBRATION_MIN_FILES - 1,
            },
        ]
        health_pipe = MagicMock()

        transitions = _check_idle_pipeline_completion(worker_db, health_pipe)

        assert transitions == 2
        mock_pipeline_states.find_ml_complete_libraries.assert_called_once_with(INTERNAL_CALIBRATION_MIN_FILES)
        assert mock_pipeline_states.transition_state.call_args_list == [
            call("libraries/large", PIPELINE_AWAITING_CALIBRATION),
            call("libraries/small", PIPELINE_TOO_SMALL),
        ]
        health_pipe.send.assert_called_once_with(PIPELINE_FRAME_PREFIX + "calibration_trigger")

    def test_empty_completed_list_does_not_emit_pipeline_signal(
        self,
        worker_db: MagicMock,
    ) -> None:
        """Idle-path checks with no completed libraries should be a no-op."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        mock_pipeline_states = worker_db.library_pipeline_states
        mock_pipeline_states.find_ml_complete_libraries.return_value = []
        health_pipe = MagicMock()

        transitions = _check_idle_pipeline_completion(worker_db, health_pipe)

        assert transitions == 0
        mock_pipeline_states.transition_state.assert_not_called()
        health_pipe.send.assert_not_called()

    def test_transitions_libraries_and_returns_count_when_health_pipe_is_none(
        self,
        worker_db: MagicMock,
    ) -> None:
        """Completed libraries should still transition when no health pipe is available."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        mock_pipeline_states = worker_db.library_pipeline_states
        mock_pipeline_states.find_ml_complete_libraries.return_value = [
            {
                "library_id": "libraries/large",
                "tagged_count": INTERNAL_CALIBRATION_MIN_FILES,
            },
            {
                "library_id": "libraries/small",
                "tagged_count": INTERNAL_CALIBRATION_MIN_FILES - 1,
            },
        ]

        transitions = _check_idle_pipeline_completion(worker_db, None)

        assert transitions == 2
        mock_pipeline_states.find_ml_complete_libraries.assert_called_once_with(INTERNAL_CALIBRATION_MIN_FILES)
        assert mock_pipeline_states.transition_state.call_args_list == [
            call("libraries/large", PIPELINE_AWAITING_CALIBRATION),
            call("libraries/small", PIPELINE_TOO_SMALL),
        ]

    def test_broken_pipe_error_on_send_is_swallowed(
        self,
        worker_db: MagicMock,
    ) -> None:
        """Broken pipe errors during trigger emission should not interrupt transitions."""
        from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

        mock_pipeline_states = worker_db.library_pipeline_states
        mock_pipeline_states.find_ml_complete_libraries.return_value = [
            {
                "library_id": "libraries/large",
                "tagged_count": INTERNAL_CALIBRATION_MIN_FILES,
            },
        ]
        health_pipe = MagicMock()
        health_pipe.send.side_effect = BrokenPipeError("pipe closed")

        transitions = _check_idle_pipeline_completion(worker_db, health_pipe)

        assert transitions == 1
        mock_pipeline_states.find_ml_complete_libraries.assert_called_once_with(INTERNAL_CALIBRATION_MIN_FILES)
        mock_pipeline_states.transition_state.assert_called_once_with(
            "libraries/large",
            PIPELINE_AWAITING_CALIBRATION,
        )
        health_pipe.send.assert_called_once_with(PIPELINE_FRAME_PREFIX + "calibration_trigger")


class TestWorkerSystemPipelineCallback:
    """Tests for main-process pipeline callback wiring."""

    def test_pipeline_frame_invokes_trigger_calibration(
        self,
        worker_db: MagicMock,
        processor_config: ProcessorConfig,
    ) -> None:
        """PIPELINE calibration frames should call LibraryPipelineService.trigger_calibration."""
        from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorConfig, HealthMonitorService
        from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

        health_monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        health_monitor.register_component(
            component_id="worker:tag:0",
            handler=MagicMock(),
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
        )
        pipeline_svc = MagicMock()

        WorkerSystemService(
            db=worker_db,
            processor_config=processor_config,
            pipeline_svc=pipeline_svc,
            health_monitor=health_monitor,
            worker_count=1,
        )

        health_monitor._handle_frame("worker:tag:0", PIPELINE_FRAME_PREFIX + "calibration_trigger")

        pipeline_svc.trigger_calibration.assert_called_once_with()

    def test_duplicate_pipeline_frames_invoke_callback_each_time(
        self,
        worker_db: MagicMock,
        processor_config: ProcessorConfig,
    ) -> None:
        """Callback wiring is intentionally stateless; trigger idempotency lives in the pipeline service."""
        from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorConfig, HealthMonitorService
        from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

        health_monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        health_monitor.register_component(
            component_id="worker:tag:0",
            handler=MagicMock(),
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
        )
        pipeline_svc = MagicMock()

        WorkerSystemService(
            db=worker_db,
            processor_config=processor_config,
            pipeline_svc=pipeline_svc,
            health_monitor=health_monitor,
            worker_count=1,
        )

        health_monitor._handle_frame("worker:tag:0", PIPELINE_FRAME_PREFIX + "calibration_trigger")
        health_monitor._handle_frame("worker:tag:0", PIPELINE_FRAME_PREFIX + "calibration_trigger")

        assert pipeline_svc.trigger_calibration.call_count == 2
