"""Base class for ONNX model session lifecycle management.

All ONNX model wrappers in nomarr inherit from ``BaseONNXModel``, which owns
the ``InferenceSession`` lifecycle. Subclasses derive metadata from the
``.onnx`` path in their ``__init__`` and implement :meth:`run`.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

import numpy as np

from nomarr.components.ml import ml_backend_onnx_comp as backend_onnx
from nomarr.components.ml import ml_vram_coordinator_comp as _coordinator
from nomarr.components.ml import ml_worker_context_comp as _worker_ctx

if TYPE_CHECKING:
    import onnxruntime as ort


logger = logging.getLogger(__name__)

DevicePlacement = Literal["cpu", "gpu"]
"""Device on which an ONNX session is loaded.  Matches Essentia C++ values."""

# Meta key prefix for per-model VRAM measurements (written by ml_vram_probe_comp).
_VRAM_META_PREFIX = "ml_model_vram:"


class VramFitError(RuntimeError):
    """Raised by :meth:`BaseONNXModel.load` when the VRAM coordinator rejects
    the GPU placement request for this model.

    The caller (typically the :attr:`ONNXModelCache.warm` setter) should catch
    this and retry the same model with ``device="cpu"``.
    """


class BaseONNXModel(ABC):
    """Abstract base for ONNX model session lifecycle management.

    Owns ``_session`` and ``_device``. Subclasses derive metadata from the
    ``.onnx`` path in their ``__init__`` and implement :meth:`run`.

    Session transitions are synchronous and blocking:

    - ``model.device = "gpu"`` — unloads, then reloads on GPU.
    - ``model.device = "cpu"`` — unloads, then reloads on CPU.
    - Setting the same device is a no-op.
    - ``model.device`` returns ``None`` while unloaded.
    """

    def __init__(self, path: str) -> None:
        """Store the model path; does not load a session.

        Args:
            path: Absolute path to the ``.onnx`` file.
        """
        self._path: str = path
        self._session: ort.InferenceSession | None = None
        self._device: DevicePlacement | None = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def load(self, device: DevicePlacement) -> None:
        """Create and store an ONNX session for *device*.

        When *device* is ``"gpu"``, retrieves the worker context from
        the process-local registry and:

        1. Reads the VRAM limit for this model from the database
           (``ml_model_vram:<path>`` meta key, written by the VRAM probe with
           10% headroom already included).  Falls back to ``0`` (no cap) if no
           measurement exists yet.
        2. Calls the VRAM coordinator to atomically register a fleet-wide
           promise.  Raises :exc:`VramFitError` if headroom is exhausted.

        If no worker context is registered (probe processes, tests), both the
        DB read and coordinator check are skipped.

        Args:
            device: Target execution device (``"cpu"`` or ``"gpu"``).

        Raises:
            VramFitError: If ``device == "gpu"`` and the VRAM coordinator
                rejects the GPU placement request.
        """
        vram_limit_bytes = 0
        if device == "gpu":
            ctx = _worker_ctx.get_worker_context()
            if ctx is not None:
                db, worker_id = ctx
                raw = db.meta.get(f"{_VRAM_META_PREFIX}{self._path}")
                if raw is not None:
                    vram_limit_bytes = int(raw)
                registered = _coordinator.register_vram_promise(
                    db,
                    worker_id,
                    os.getpid(),
                    self._path,
                    vram_limit_bytes / (1024 * 1024),
                )
                if not registered:
                    raise VramFitError(
                        f"VRAM coordinator rejected GPU placement for {self._path}: "
                        f"insufficient fleet headroom"
                    )

        self._session = backend_onnx.create_session(
            self._path,
            device,
            vram_limit_bytes if device == "gpu" else None,
        )
        self._device = device

    def unload(self) -> None:
        """Release the ONNX session and free associated memory.

        If the model was loaded on GPU and a worker context is registered,
        releases the VRAM promise from the coordinator so the headroom is
        returned to the fleet.
        """
        if self._device == "gpu":
            ctx = _worker_ctx.get_worker_context()
            if ctx is not None:
                db, worker_id = ctx
                _coordinator.release_vram_promise(db, worker_id, self._path)
        self._session = None
        self._device = None

    # ------------------------------------------------------------------
    # Device property (getter + setter)
    # ------------------------------------------------------------------

    @property
    def device(self) -> DevicePlacement | None:
        """Current device, or ``None`` if not loaded."""
        return self._device

    @device.setter
    def device(self, value: DevicePlacement) -> None:
        """Transition to *value*, unloading then reloading if needed.

        No-op if already loaded on the requested device.  VRAM limit is
        re-fetched from the DB on reload so OOM-updated values are respected.

        If *value* is ``"gpu"`` and the VRAM coordinator rejects the request,
        the model is loaded on CPU instead and :exc:`VramFitError` is re-raised
        so the caller knows the preferred device was not honoured.
        """
        if value == self._device:
            return
        self.unload()
        try:
            self.load(value)
        except VramFitError:
            logger.warning(
                "[model] VRAM coordinator rejected GPU for %s — falling back to CPU",
                self._path,
            )
            self.load("cpu")
            raise

    # ------------------------------------------------------------------
    # Inference (subclass responsibility)
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, inputs: np.ndarray) -> np.ndarray:
        """Run inference on *inputs*.

        Raises:
            RuntimeError: If the model is not loaded.
        """
