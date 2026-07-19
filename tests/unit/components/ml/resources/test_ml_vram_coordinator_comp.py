"""Tests for ``nomarr.components.ml.resources.ml_vram_coordinator_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.resources.ml_vram_coordinator_comp import (
    get_fleet_vram_state,
    register_vram_promise,
    release_vram_promise,
    release_worker_promises,
)


@pytest.mark.unit
class TestRegisterVramPromise:
    def test_registers_promise_via_vram_facade(self) -> None:
        db = MagicMock()
        db.vram_promises.list_all.return_value = []

        with (
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.reset_telemetry_cache"
            ) as mock_reset,
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.get_vram_usage_mb",
                return_value={"used_mb": 1000, "total_mb": 8000, "error": None},
            ),
        ):
            result = register_vram_promise(db, "worker:1", 999, "model.onnx", 512.0)

        assert result is True
        mock_reset.assert_called_once_with()
        db.vram_promises.promise.assert_called_once_with(
            worker_id="worker:1",
            pid=999,
            model_path="model.onnx",
            promised_mb=512.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )

    def test_returns_false_when_nvidia_smi_reports_error(self) -> None:
        db = MagicMock()

        with (
            patch("nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.reset_telemetry_cache"),
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.get_vram_usage_mb",
                return_value={"error": "nvidia-smi failed"},
            ),
        ):
            result = register_vram_promise(db, "worker:1", 999, "model.onnx", 512.0)

        assert result is False
        db.vram_promises.promise.assert_not_called()

    def test_headroom_fit_check_accepts_when_under_90_percent(self) -> None:
        db = MagicMock()
        db.vram_promises.list_all.return_value = [
            {"promised_mb": 1000},
            {"promised_mb": 1000},
        ]

        with (
            patch("nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.reset_telemetry_cache"),
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.get_vram_usage_mb",
                return_value={"used_mb": 3000, "total_mb": 8000, "error": None},
            ),
        ):
            result = register_vram_promise(db, "worker:1", 999, "model.onnx", 1000.0)

        # 1000 + 2000 = 3000 < 7200 (90% of 8000)
        assert result is True
        db.vram_promises.promise.assert_called_once()

    def test_headroom_fit_check_rejects_when_over_90_percent(self) -> None:
        db = MagicMock()
        db.vram_promises.list_all.return_value = [
            {"promised_mb": 3500},
            {"promised_mb": 3000},
        ]

        with (
            patch("nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.reset_telemetry_cache"),
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.get_vram_usage_mb",
                return_value={"used_mb": 5000, "total_mb": 8000, "error": None},
            ),
        ):
            result = register_vram_promise(db, "worker:1", 999, "model.onnx", 1000.0)

        # 1000 + 6500 = 7500 > 7200 (90% of 8000)
        assert result is False
        db.vram_promises.promise.assert_not_called()

    def test_headroom_fit_check_accepts_at_exact_90_percent(self) -> None:
        db = MagicMock()
        db.vram_promises.list_all.return_value = [
            {"promised_mb": 3200},
            {"promised_mb": 3000},
        ]

        with (
            patch("nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.reset_telemetry_cache"),
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.get_vram_usage_mb",
                return_value={"used_mb": 5000, "total_mb": 8000, "error": None},
            ),
        ):
            result = register_vram_promise(db, "worker:1", 999, "model.onnx", 1000.0)

        # 1000 + 6200 = 7200 == 7200 (90% of 8000); boundary is accepted (> not >=)
        assert result is True
        db.vram_promises.promise.assert_called_once()


@pytest.mark.unit
class TestReleaseVramPromise:
    def test_deletes_single_promise_via_vram_facade(self) -> None:
        db = MagicMock()

        release_vram_promise(db, "worker:1", "model.onnx")

        db.vram_promises.release.assert_called_once_with(worker_id="worker:1", model_path="model.onnx")


@pytest.mark.unit
class TestReleaseWorkerPromises:
    def test_releases_all_for_worker_via_vram_facade(self) -> None:
        db = MagicMock()
        db.app.list_vram_promises.return_value = [{"worker_id": "worker:1"}, {"worker_id": "worker:1"}]

        result = release_worker_promises(db, "worker:1")

        assert result == 2
        db.app.list_vram_promises.assert_called_once_with()
        db.vram_promises.release_all_for_worker.assert_called_once_with(worker_id="worker:1")


@pytest.mark.unit
class TestGetFleetVramState:
    def test_get_fleet_vram_state_returns_promises_and_vram(self) -> None:
        db = MagicMock()
        mock_promises = [
            {"worker_id": "worker:1", "model_path": "a.onnx", "promised_mb": 512},
            {"worker_id": "worker:2", "model_path": "b.onnx", "promised_mb": 256},
        ]
        db.vram_promises.list_all.return_value = mock_promises

        with patch(
            "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.get_vram_usage_mb",
            return_value={"used_mb": 2000, "total_mb": 8000, "error": None},
        ):
            result = get_fleet_vram_state(db)

        assert result["promises"] == mock_promises
        assert result["vram"] == {"used_mb": 2000, "total_mb": 8000, "error": None}
        db.vram_promises.list_all.assert_called_once()
