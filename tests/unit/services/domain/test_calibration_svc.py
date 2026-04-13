"""Tests for BTS-backed calibration behavior in ``nomarr.services.domain.calibration_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers import ManagedTask
from nomarr.services.domain.calibration_svc import (
    CALIBRATION_GENERATE_TASK_ID,
    CalibrationConfig,
    CalibrationService,
)


def _make_service(*, db: MagicMock | None = None, bts: MagicMock | None = None) -> CalibrationService:
    """Build a minimal CalibrationService for BTS-backed tests."""
    return CalibrationService(
        db=db or MagicMock(),
        cfg=CalibrationConfig(models_dir="models", namespace="nom"),
        bts=bts or MagicMock(),
    )


class TestIsGenerationRunning:
    """Tests for BTS-backed generation status polling."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_generation_running_true_when_bts_status_running(self) -> None:
        """Running BTS status should surface as generation running."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {"status": "running"}
        service = _make_service(bts=mock_bts)

        result = service.is_generation_running()

        assert result is True
        mock_bts.get_task_status.assert_called_once_with(CALIBRATION_GENERATE_TASK_ID)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_generation_running_false_when_bts_status_none(self) -> None:
        """Missing BTS task state should surface as generation not running."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(bts=mock_bts)

        result = service.is_generation_running()

        assert result is False
        mock_bts.get_task_status.assert_called_once_with(CALIBRATION_GENERATE_TASK_ID)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_generation_running_false_when_bts_status_complete(self) -> None:
        """Completed BTS status should not surface as generation running."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {"status": "complete"}
        service = _make_service(bts=mock_bts)

        result = service.is_generation_running()

        assert result is False
        mock_bts.get_task_status.assert_called_once_with(CALIBRATION_GENERATE_TASK_ID)


class TestStartHistogramCalibrationBackground:
    """Tests for BTS-backed generation dispatch."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_registers_managed_task_with_bts(self) -> None:
        """Service should register a ManagedTask with the expected task id."""
        mock_bts = MagicMock()
        service = _make_service(bts=mock_bts)

        service.start_histogram_calibration_background()

        mock_bts.start_task.assert_called_once()
        managed_task = mock_bts.start_task.call_args.args[0]
        assert isinstance(managed_task, ManagedTask)
        assert managed_task.task_id == CALIBRATION_GENERATE_TASK_ID

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_skips_if_already_running(self) -> None:
        """Dispatch should be skipped when generation is already running."""
        mock_bts = MagicMock()
        service = _make_service(bts=mock_bts)

        with patch.object(service, "is_generation_running", return_value=True):
            service.start_histogram_calibration_background()

        mock_bts.start_task.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_handles_bts_value_error_gracefully(self) -> None:
        """Duplicate BTS start attempts should be swallowed without raising."""
        mock_bts = MagicMock()
        mock_bts.start_task.side_effect = ValueError("already running")
        service = _make_service(bts=mock_bts)

        with patch.object(service, "is_generation_running", return_value=False):
            service.start_histogram_calibration_background()

        mock_bts.start_task.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_resets_result_and_error_before_start(self) -> None:
        """Starting a new run should clear previous result and error state."""
        mock_bts = MagicMock()
        service = _make_service(bts=mock_bts)
        service._generation_result = {"foo": 1}
        service._generation_error = RuntimeError("old")

        with patch.object(service, "is_generation_running", return_value=False):
            service.start_histogram_calibration_background()

        assert service._generation_result is None
        assert service._generation_error is None


class TestGetGenerationCombinedStatus:
    """Tests for combined generation status snapshots."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_generation_combined_status_idle(self) -> None:
        """Fresh service should report idle combined status."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(bts=mock_bts)

        with (
            patch("nomarr.services.domain.calibration_svc.discover_heads_no_db", return_value=[]),
            patch("nomarr.services.domain.calibration_svc.now_ms") as mock_now_ms,
            patch("nomarr.services.domain.calibration_svc.count_recent_calibration_states", return_value=0),
            patch("nomarr.services.domain.calibration_svc.get_latest_calibration_state_updated_at", return_value=None),
        ):
            mock_now_ms.return_value.value = 2_000

            status = service.get_generation_combined_status()

        assert status == {
            "running": False,
            "completed": False,
            "error": None,
            "result": None,
            "current_head": None,
            "current_head_index": None,
            "total_heads": 0,
            "completed_heads": 0,
            "remaining_heads": 0,
            "last_updated": None,
            "is_running": False,
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_generation_combined_status_running(self) -> None:
        """Running BTS status should report combined live progress without completion."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {"status": "running"}
        service = _make_service(bts=mock_bts)
        service._progress = {
            "current_head": "mood_happy",
            "current_head_index": 2,
            "total_heads": 12,
        }

        status = service.get_generation_combined_status()

        assert status["running"] is True
        assert status["completed"] is False
        assert status["current_head"] == "mood_happy"
        assert status["current_head_index"] == 2
        assert status["total_heads"] == 12
        assert status["is_running"] is True

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_generation_combined_status_completed(self) -> None:
        """Stored generation result should surface in the combined status output."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(bts=mock_bts)
        service._generation_result = {"heads_success": 3}

        with (
            patch("nomarr.services.domain.calibration_svc.discover_heads_no_db", return_value=["a", "b", "c"]),
            patch("nomarr.services.domain.calibration_svc.now_ms") as mock_now_ms,
            patch("nomarr.services.domain.calibration_svc.count_recent_calibration_states", return_value=2),
            patch("nomarr.services.domain.calibration_svc.get_latest_calibration_state_updated_at", return_value=1_500),
        ):
            mock_now_ms.return_value.value = 2_000

            status = service.get_generation_combined_status()

        assert status["completed"] is True
        assert status["result"] == {"heads_success": 3}
        assert status["total_heads"] == 3
        assert status["completed_heads"] == 2
        assert status["remaining_heads"] == 1
        assert status["last_updated"] == 1_500

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_generation_combined_status_failed(self) -> None:
        """Stored generation error should surface in combined status output."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(bts=mock_bts)
        service._generation_error = RuntimeError("boom")

        with (
            patch("nomarr.services.domain.calibration_svc.discover_heads_no_db", return_value=[]),
            patch("nomarr.services.domain.calibration_svc.now_ms") as mock_now_ms,
            patch("nomarr.services.domain.calibration_svc.count_recent_calibration_states", return_value=0),
            patch("nomarr.services.domain.calibration_svc.get_latest_calibration_state_updated_at", return_value=None),
        ):
            mock_now_ms.return_value.value = 2_000

            status = service.get_generation_combined_status()

        assert status["error"] == "boom"
        assert status["running"] is False


class TestSetPostGenerationHook:
    """Tests for guarded post-generation hook behavior."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_hook_skips_when_no_result(self) -> None:
        """Hook should not run when no generation result is available."""
        service = _make_service()
        hook = MagicMock()
        service.set_post_generation_hook(hook)

        assert service._post_generation_hook is not None
        service._post_generation_hook()

        hook.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_hook_skips_when_heads_failed_nonzero(self) -> None:
        """Hook should not run when generation completed with failed heads."""
        service = _make_service()
        hook = MagicMock()
        service.set_post_generation_hook(hook)
        service._generation_result = {"heads_failed": 2}

        assert service._post_generation_hook is not None
        service._post_generation_hook()

        hook.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_hook_calls_when_heads_failed_zero(self) -> None:
        """Hook should run when generation completed with zero failed heads."""
        service = _make_service()
        hook = MagicMock()
        service.set_post_generation_hook(hook)
        service._generation_result = {"heads_failed": 0}

        assert service._post_generation_hook is not None
        service._post_generation_hook()

        hook.assert_called_once_with()


class TestClearCalibration:
    """Tests for clearing calibration data."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_clear_calibration_raises_if_generation_running(self) -> None:
        """Clearing calibration should be blocked while generation is active."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {"status": "running"}
        service = _make_service(bts=mock_bts)

        with pytest.raises(RuntimeError, match="Cannot clear calibration while generation is running"):
            service.clear_calibration()


class TestRunHistogramGeneration:
    """Tests for managed histogram generation execution."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_run_histogram_generation_stores_result(self) -> None:
        """Successful generation should be stored on the service."""
        service = _make_service()
        expected = {"heads_success": 2, "heads_failed": 0}

        with patch.object(service, "generate_histogram_calibration", return_value=expected):
            result = service._run_histogram_generation()

        assert result == expected
        assert service._generation_result == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_run_histogram_generation_stores_error_and_reraises(self) -> None:
        """Failed generation should store the error and re-raise it."""
        service = _make_service()
        error = RuntimeError("fail")

        with (
            patch.object(service, "generate_histogram_calibration", side_effect=error),
            pytest.raises(
                RuntimeError,
                match="fail",
            ),
        ):
            service._run_histogram_generation()

        assert service._generation_error is error
