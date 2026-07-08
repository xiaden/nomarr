"""Tests for ``nomarr.components.ml.resources.ml_vram_coordinator_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.resources.ml_vram_coordinator_comp import (
    register_vram_promise,
    release_vram_promise,
    release_worker_promises,
)


@pytest.mark.unit
class TestRegisterVramPromise:
    def test_registers_promise_via_vram_facade(self) -> None:
        db = MagicMock()
        db.vram_promises.try_register.return_value = True

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
        db.vram_promises.try_register.assert_called_once_with(
            worker_id="worker:1",
            pid=999,
            model_path="model.onnx",
            promised_mb=512.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )

    def test_returns_false_when_headroom_is_insufficient(self) -> None:
        db = MagicMock()
        db.vram_promises.try_register.return_value = False

        with (
            patch("nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.reset_telemetry_cache"),
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.get_vram_usage_mb",
                return_value={"used_mb": 600.0, "total_mb": 8000.0, "error": None},
            ),
        ):
            result = register_vram_promise(db, "worker:1", 999, "model.onnx", 512.0)

        assert result is False
        db.vram_promises.try_register.assert_called_once_with(
            worker_id="worker:1",
            pid=999,
            model_path="model.onnx",
            promised_mb=512.0,
            total_mb=8000.0,
            used_mb=600.0,
        )


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
        db.vram_promises.release_all_for_worker.return_value = 2

        result = release_worker_promises(db, "worker:1")

        assert result == 2
        db.vram_promises.release_all_for_worker.assert_called_once_with(worker_id="worker:1")
