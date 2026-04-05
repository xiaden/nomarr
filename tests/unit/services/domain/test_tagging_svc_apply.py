"""Tests for BTS-backed apply behavior in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers import ManagedTask
from nomarr.services.domain.tagging_svc import (
    CALIBRATION_APPLY_TASK_ID,
    TaggingService,
    TaggingServiceConfig,
)


def _make_service(*, db: MagicMock | None = None, bts: MagicMock | None = None) -> TaggingService:
    """Build a minimal TaggingService for apply tests."""
    return TaggingService(
        database=db or MagicMock(),
        cfg=TaggingServiceConfig(
            models_dir="models",
            namespace="nom",
            version_tag_key="nom:version",
        ),
        bts=bts or MagicMock(),
        config_service=MagicMock(),
    )


class TestIsApplyRunning:
    """Tests for BTS-backed apply status polling."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_apply_running_true_when_bts_status_running(self) -> None:
        """Running BTS status should surface as apply running."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {"status": "running"}
        service = _make_service(bts=mock_bts)

        result = service.is_apply_running()

        assert result is True
        mock_bts.get_task_status.assert_called_once_with(CALIBRATION_APPLY_TASK_ID)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_apply_running_false_when_bts_status_none(self) -> None:
        """Missing BTS task state should surface as apply not running."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(bts=mock_bts)

        result = service.is_apply_running()

        assert result is False
        mock_bts.get_task_status.assert_called_once_with(CALIBRATION_APPLY_TASK_ID)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_apply_running_false_when_bts_status_complete(self) -> None:
        """Completed BTS status should not surface as apply running."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {"status": "complete"}
        service = _make_service(bts=mock_bts)

        result = service.is_apply_running()

        assert result is False
        mock_bts.get_task_status.assert_called_once_with(CALIBRATION_APPLY_TASK_ID)


class TestStartApplyCalibrationBackground:
    """Tests for BTS-backed apply dispatch."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_registers_managed_task_with_bts(self) -> None:
        """Service should register a ManagedTask with the expected task id."""
        mock_bts = MagicMock()
        service = _make_service(bts=mock_bts)

        service.start_apply_calibration_background()

        mock_bts.start_task.assert_called_once()
        managed_task = mock_bts.start_task.call_args.args[0]
        assert isinstance(managed_task, ManagedTask)
        assert managed_task.task_id == CALIBRATION_APPLY_TASK_ID

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_skips_if_already_running(self) -> None:
        """Dispatch should be skipped when apply is already running."""
        mock_bts = MagicMock()
        service = _make_service(bts=mock_bts)

        with patch.object(service, "is_apply_running", return_value=True):
            service.start_apply_calibration_background()

        mock_bts.start_task.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_handles_bts_value_error_gracefully(self) -> None:
        """Duplicate BTS start attempts should be swallowed without raising."""
        mock_bts = MagicMock()
        mock_bts.start_task.side_effect = ValueError("already running")
        service = _make_service(bts=mock_bts)

        with patch.object(service, "is_apply_running", return_value=False):
            service.start_apply_calibration_background()

        mock_bts.start_task.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_resets_result_and_error_before_start(self) -> None:
        """Starting a new apply run should clear previous result and error state."""
        mock_bts = MagicMock()
        service = _make_service(bts=mock_bts)
        service._apply_result = MagicMock()
        service._apply_error = RuntimeError("old")

        with patch.object(service, "is_apply_running", return_value=False):
            service.start_apply_calibration_background()

        assert service._apply_result is None
        assert service._apply_error is None


class TestGetApplyStatus:
    """Tests for apply status snapshots."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_apply_status_idle(self) -> None:
        """Fresh service should report idle status."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(bts=mock_bts)

        status = service.get_apply_status()

        assert status == {"status": "idle", "result": None, "error": None}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_apply_status_running(self) -> None:
        """Running BTS status should report running without a result."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {"status": "running"}
        service = _make_service(bts=mock_bts)

        status = service.get_apply_status()

        assert status["status"] == "running"
        assert status["result"] is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_apply_status_completed(self) -> None:
        """Stored apply result should surface as completed status."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(bts=mock_bts)
        service._apply_result = MagicMock(processed=5, failed=0, total=5, message="done")

        status = service.get_apply_status()

        assert status["status"] == "completed"
        assert status["result"]["processed"] == 5

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_apply_status_failed(self) -> None:
        """Stored apply error should surface as failed status."""
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(bts=mock_bts)
        service._apply_error = RuntimeError("boom")

        status = service.get_apply_status()

        assert status["status"] == "failed"
        assert status["error"] == "boom"


class TestRunApplyCalibration:
    """Tests for managed apply execution."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_run_apply_calibration_stores_result(self) -> None:
        """Successful apply should be stored on the service."""
        service = _make_service()
        expected = MagicMock(processed=3, failed=0, total=3)

        with patch.object(service, "tag_library", return_value=expected):
            result = service._run_apply_calibration()

        assert result is expected
        assert service._apply_result is expected

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_run_apply_calibration_stores_error_and_reraises(self) -> None:
        """Failed apply should store the error and re-raise it."""
        service = _make_service()
        error = RuntimeError("fail")

        with patch.object(service, "tag_library", side_effect=error), pytest.raises(RuntimeError, match="fail"):
            service._run_apply_calibration()

        assert service._apply_error is error
