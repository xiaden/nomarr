"""Tests for ``nomarr.components.ml.onnx.ml_base``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nomarr.components.ml.onnx.ml_base import BaseONNXModel, VramFitError


class _ConcreteModel(BaseONNXModel):
    """Minimal concrete subclass for testing the abstract base."""

    def _run(self, inputs: np.ndarray) -> np.ndarray:
        return np.array([[1.0, 2.0]], dtype=np.float32)


@pytest.mark.unit
class TestBaseONNXModelInit:
    def test_init_stores_path_and_none_session_device(self) -> None:
        model = _ConcreteModel("/models/effnet/model.onnx")

        assert model._path == "/models/effnet/model.onnx"
        assert model._session is None
        assert model._device is None


@pytest.mark.unit
class TestBaseONNXModelLoad:
    @patch("nomarr.components.ml.onnx.ml_base.backend_onnx.create_session")
    @patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=None)
    def test_load_cpu_creates_session_and_sets_device(
        self, mock_get_ctx: MagicMock, mock_create_session: MagicMock
    ) -> None:
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        model = _ConcreteModel("/models/effnet/model.onnx")
        model.load("cpu")

        assert model._session is mock_session
        assert model._device == "cpu"
        mock_create_session.assert_called_once_with("/models/effnet/model.onnx", "cpu", None)

    @patch("nomarr.components.ml.onnx.ml_base.backend_onnx.create_session")
    @patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=None)
    def test_load_gpu_without_worker_context_loads_directly(
        self, mock_get_ctx: MagicMock, mock_create_session: MagicMock
    ) -> None:
        """No worker context (probe/test) → skip DB read and coordinator, load directly."""
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        model = _ConcreteModel("/models/effnet/model.onnx")
        model.load("gpu")

        assert model._session is mock_session
        assert model._device == "gpu"
        # vram_limit_bytes is None when no worker context (probe mode)
        mock_create_session.assert_called_once_with("/models/effnet/model.onnx", "gpu", None)


@pytest.mark.unit
class TestBaseONNXModelLoadWithWorkerContext:
    @patch("nomarr.components.ml.onnx.ml_base.backend_onnx.create_session")
    @patch("nomarr.components.ml.onnx.ml_base._coordinator.register_vram_promise", return_value=True)
    def test_load_gpu_with_worker_context_reads_vram_and_registers_promise(
        self, mock_register: MagicMock, mock_create_session: MagicMock
    ) -> None:
        db = MagicMock()
        db.app.get_model_vram_limit.return_value = 1048576  # 1MB
        ctx = (db, "worker:1")

        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        model = _ConcreteModel("/models/effnet/model.onnx")
        with patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=ctx):
            model.load("gpu")

        assert model._device == "gpu"
        mock_register.assert_called_once()
        mock_create_session.assert_called_once_with("/models/effnet/model.onnx", "gpu", 1048576)

    @patch("nomarr.components.ml.onnx.ml_base.backend_onnx.create_session")
    @patch("nomarr.components.ml.onnx.ml_base._coordinator.register_vram_promise", return_value=False)
    def test_load_gpu_raises_vram_fit_error_when_coordinator_rejects(
        self, mock_register: MagicMock, mock_create_session: MagicMock
    ) -> None:
        db = MagicMock()
        db.app.get_model_vram_limit.return_value = 1048576
        ctx = (db, "worker:1")

        model = _ConcreteModel("/models/effnet/model.onnx")
        with (
            patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=ctx),
            pytest.raises(VramFitError, match="insufficient fleet headroom"),
        ):
            model.load("gpu")

        mock_create_session.assert_not_called()

    @patch("nomarr.components.ml.onnx.ml_base.backend_onnx.create_session")
    def test_load_gpu_raises_vram_fit_error_when_probe_marked_incompatible(
        self, mock_create_session: MagicMock
    ) -> None:
        import sys

        db = MagicMock()
        db.app.get_model_vram_limit.return_value = sys.maxsize
        ctx = (db, "worker:1")

        model = _ConcreteModel("/models/effnet/model.onnx")
        with (
            patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=ctx),
            pytest.raises(VramFitError, match="GPU-incompatible"),
        ):
            model.load("gpu")

        mock_create_session.assert_not_called()


@pytest.mark.unit
class TestBaseONNXModelUnload:
    @patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=None)
    def test_unload_releases_session_and_clears_device(self, mock_get_ctx: MagicMock) -> None:
        model = _ConcreteModel("/models/effnet/model.onnx")
        model._session = MagicMock()
        model._device = "cpu"

        model.unload()

        assert model._session is None
        assert model._device is None

    @patch("nomarr.components.ml.onnx.ml_base._coordinator.release_vram_promise")
    def test_unload_on_gpu_releases_vram_promise(self, mock_release: MagicMock) -> None:
        db = MagicMock()
        ctx = (db, "worker:1")

        model = _ConcreteModel("/models/effnet/model.onnx")
        model._session = MagicMock()
        model._device = "gpu"

        with patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=ctx):
            model.unload()

        assert model._session is None
        assert model._device is None
        mock_release.assert_called_once_with(db, "worker:1", "/models/effnet/model.onnx")


@pytest.mark.unit
class TestBaseONNXModelDeviceProperty:
    def test_device_getter_returns_device(self) -> None:
        model = _ConcreteModel("/models/effnet/model.onnx")
        assert model.device is None

        model._device = "cpu"
        assert model.device == "cpu"

        model._device = "gpu"
        assert model.device == "gpu"

    @patch("nomarr.components.ml.onnx.ml_base.backend_onnx.create_session")
    @patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=None)
    def test_device_setter_no_op_when_same(self, mock_get_ctx: MagicMock, mock_create_session: MagicMock) -> None:
        model = _ConcreteModel("/models/effnet/model.onnx")
        model._session = MagicMock()
        model._device = "cpu"

        model.device = "cpu"

        # Should not have called create_session (no-op)
        mock_create_session.assert_not_called()
        assert model._device == "cpu"

    @patch("nomarr.components.ml.onnx.ml_base.backend_onnx.create_session")
    @patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=None)
    def test_device_setter_unloads_and_loads_when_different(
        self, mock_get_ctx: MagicMock, mock_create_session: MagicMock
    ) -> None:
        new_session = MagicMock()
        mock_create_session.return_value = new_session

        model = _ConcreteModel("/models/effnet/model.onnx")
        old_session = MagicMock()
        model._session = old_session
        model._device = "cpu"

        model.device = "gpu"

        assert model._session is new_session
        assert model._device == "gpu"
        mock_create_session.assert_called_once()


@pytest.mark.unit
class TestBaseONNXModelRun:
    def test_run_delegates_to_subclass_run(self) -> None:
        model = _ConcreteModel("/models/effnet/model.onnx")
        model._device = "cpu"

        inputs = np.array([[1.0, 2.0]], dtype=np.float32)
        result = model.run(inputs)

        np.testing.assert_array_equal(result, np.array([[1.0, 2.0]], dtype=np.float32))

    @patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=None)
    def test_run_non_bfc_error_propagates_immediately(self, mock_get_ctx: MagicMock) -> None:
        class FailingModel(BaseONNXModel):
            def _run(self, inputs: np.ndarray) -> np.ndarray:
                raise RuntimeError("wrong input shape")

        model = FailingModel("/models/effnet/model.onnx")
        model._device = "cpu"

        with pytest.raises(RuntimeError, match="wrong input shape"):
            model.run(np.zeros((1, 2), dtype=np.float32))


@pytest.mark.unit
class TestBaseONNXModelRunBfcOom:
    def test_bfc_oom_self_heals_and_succeeds_on_second_attempt(self) -> None:
        class FailingOnceModel(BaseONNXModel):
            call_count = 0

            def _run(self, inputs: np.ndarray) -> np.ndarray:
                FailingOnceModel.call_count += 1
                if FailingOnceModel.call_count == 1:
                    raise RuntimeError("Resource exhausted: requested bytes of 1048576")
                return np.array([[42.0]], dtype=np.float32)

        db = MagicMock()
        db.app.get_model_vram_limit.return_value = None  # no stored VRAM limit
        ctx = (db, "worker:1")

        model = FailingOnceModel("/models/effnet/model.onnx")
        model._device = "gpu"
        model._session = MagicMock()

        inputs = np.array([[1.0]], dtype=np.float32)

        with (
            patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=ctx),
            patch(
                "nomarr.components.ml.onnx.ml_base.update_model_vram_from_oom",
                return_value=2097152,
            ) as mock_update,
            patch("nomarr.components.ml.onnx.ml_base.backend_onnx.create_session") as mock_create,
        ):
            mock_create.return_value = MagicMock()
            result = model.run(inputs)

        np.testing.assert_array_equal(result, np.array([[42.0]], dtype=np.float32))
        mock_update.assert_called_once_with(db, "/models/effnet/model.onnx", 1048576)
        # Model was reloaded: unload() + load("gpu") → create_session called
        assert mock_create.called

    def test_bfc_oom_on_cpu_raises_immediately(self) -> None:
        class BfcOomModel(BaseONNXModel):
            def _run(self, inputs: np.ndarray) -> np.ndarray:
                raise RuntimeError("Resource exhausted: requested bytes of 1048576")

        model = BfcOomModel("/models/effnet/model.onnx")
        model._device = "cpu"
        model._session = MagicMock()

        inputs = np.array([[1.0]], dtype=np.float32)

        with (
            patch("nomarr.components.ml.onnx.ml_base.update_model_vram_from_oom") as mock_update,
            pytest.raises(RuntimeError, match="requested bytes of 1048576"),
        ):
            model.run(inputs)

        mock_update.assert_not_called()

    def test_bfc_oom_without_worker_context_raises_immediately(self) -> None:
        class BfcOomModel(BaseONNXModel):
            def _run(self, inputs: np.ndarray) -> np.ndarray:
                raise RuntimeError("Resource exhausted: requested bytes of 1048576")

        model = BfcOomModel("/models/effnet/model.onnx")
        model._device = "gpu"
        model._session = MagicMock()

        inputs = np.array([[1.0]], dtype=np.float32)

        with (
            patch("nomarr.components.ml.onnx.ml_base._worker_ctx.get_worker_context", return_value=None),
            patch("nomarr.components.ml.onnx.ml_base.update_model_vram_from_oom") as mock_update,
            pytest.raises(RuntimeError, match="requested bytes of 1048576"),
        ):
            model.run(inputs)

        mock_update.assert_not_called()
