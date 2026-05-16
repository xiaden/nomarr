"""Tests for ``nomarr.components.ml.resources.ml_vram_coordinator_comp``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.ml.resources.ml_vram_coordinator_comp import (
    _promise_key,
    register_vram_promise,
    release_vram_promise,
    release_worker_promises,
)


@pytest.mark.unit
class TestRegisterVramPromise:
    def test_registers_promise_via_app_facade(self) -> None:
        db = MagicMock()
        db.app.list_vram_promises.return_value = []

        with (
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.reset_telemetry_cache"
            ) as mock_reset,
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.get_vram_usage_mb",
                return_value={"used_mb": 1000, "total_mb": 8000, "error": None},
            ),
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp.now_ms",
                return_value=SimpleNamespace(value=123456),
            ),
        ):
            result = register_vram_promise(db, "worker:1", 999, "model.onnx", 512.0)

        assert result is True
        mock_reset.assert_called_once_with()
        promise_id = f"vram_promises/{_promise_key('worker:1', 'model.onnx')}"
        db.app.remove_vram_promise.assert_called_once_with(promise_id)
        db.app.add_vram_promise.assert_called_once_with(
            {
                "_key": _promise_key("worker:1", "model.onnx"),
                "worker_id": "worker:1",
                "pid": 999,
                "model_path": "model.onnx",
                "promised_mb": 512.0,
                "total_mb": 8000.0,
                "used_mb": 1000.0,
                "last_seen_ms": 123456,
            }
        )

    def test_returns_false_when_headroom_is_insufficient(self) -> None:
        db = MagicMock()
        db.app.list_vram_promises.return_value = [{"promised_mb": 7000.0}]

        with (
            patch("nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.reset_telemetry_cache"),
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp._resource_monitor.get_vram_usage_mb",
                return_value={"used_mb": 600.0, "total_mb": 8000.0, "error": None},
            ),
        ):
            result = register_vram_promise(db, "worker:1", 999, "model.onnx", 512.0)

        assert result is False
        db.app.remove_vram_promise.assert_not_called()
        db.app.add_vram_promise.assert_not_called()


@pytest.mark.unit
class TestReleaseVramPromise:
    def test_deletes_single_promise_id_via_app_facade(self) -> None:
        db = MagicMock()

        release_vram_promise(db, "worker:1", "model.onnx")

        db.app.remove_vram_promise.assert_called_once_with(f"vram_promises/{_promise_key('worker:1', 'model.onnx')}")


@pytest.mark.unit
class TestReleaseWorkerPromises:
    def test_deletes_promises_by_id_or_key_for_matching_worker(self) -> None:
        db = MagicMock()
        db.app.list_vram_promises.return_value = [
            {"_id": "vram_promises/first", "worker_id": "worker:1"},
            {"_key": "second", "worker_id": "worker:1"},
            {"_id": "vram_promises/other", "worker_id": "worker:2"},
        ]

        result = release_worker_promises(db, "worker:1")

        assert result == 2
        assert db.app.remove_vram_promise.call_args_list == [
            call("vram_promises/first"),
            call("vram_promises/second"),
        ]
