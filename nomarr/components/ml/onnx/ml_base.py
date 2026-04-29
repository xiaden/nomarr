"""Base class for ONNX model session lifecycle management.

All ONNX model wrappers in nomarr inherit from ``BaseONNXModel``, which owns
the ``InferenceSession`` lifecycle. Subclasses derive metadata from the
``.onnx`` path in their ``__init__`` and implement :meth:`run`.
"""

from __future__ import annotations

import logging
import os
import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

import numpy as np

import nomarr.components.ml.resources.ml_vram_coordinator_comp as _coordinator
import nomarr.components.ml.resources.ml_worker_context_comp as _worker_ctx
from nomarr.components.ml.onnx import ml_session_comp as backend_onnx
from nomarr.components.ml.resources.ml_vram_oom_helper_comp import (
    parse_oom_requested_bytes,
    update_model_vram_from_oom,
)

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
        vram_limit_bytes: int | None = None
        if device == "gpu":
            ctx = _worker_ctx.get_worker_context()
            if ctx is not None:
                db, worker_id = ctx
                raw_doc = db.meta.key.get(f"{_VRAM_META_PREFIX}{self._path}")
                raw = None if raw_doc is None else raw_doc.get("value")
                if raw is not None:
                    vram_limit_bytes = int(raw)
                    if vram_limit_bytes == sys.maxsize:
                        raise VramFitError(f"VRAM probe marked {self._path} as GPU-incompatible")
                logger.debug(
                    "[model] load(%s) gpu: DB key=%s%s raw=%r vram_limit_bytes=%s",
                    self._path,
                    _VRAM_META_PREFIX,
                    self._path,
                    raw,
                    vram_limit_bytes,
                )
                registered = _coordinator.register_vram_promise(
                    db,
                    worker_id,
                    os.getpid(),
                    self._path,
                    vram_limit_bytes / (1024 * 1024) if vram_limit_bytes is not None else 0.0,
                )
                if not registered:
                    raise VramFitError(
                        f"VRAM coordinator rejected GPU placement for {self._path}: insufficient fleet headroom"
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
    def _run(self, inputs: np.ndarray) -> np.ndarray:
        """Execute one forward pass on *inputs*.

        Subclasses implement this.  External callers use :meth:`run`, which
        wraps this with BFC-arena OOM recovery.

        Raises:
            RuntimeError: If the model is not loaded.

        """

    def run(self, inputs: np.ndarray) -> np.ndarray:
        """Run inference, self-healing and falls back to CPU when needed.

        The loop repeats until either:
        - inference succeeds, or
        - the model is running on CPU (no further VRAM adjustments possible),
          in which case the error propagates.

        Non-BFC errors (wrong shapes, missing session, etc.) are re-raised
        immediately on the first occurrence.

        Args:
            inputs: Input tensor for the model.

        Returns:
            Float32 output array from the model.

        Raises:
            RuntimeError: If the model is not loaded, inputs are invalid, or
                the error is not a recoverable BFC arena OOM.

        """
        while True:
            try:
                return self._run(inputs)
            except Exception as e:
                if self._device != "gpu":
                    raise  # already on CPU — nothing to heal
                requested = parse_oom_requested_bytes(e)
                if requested is None:
                    raise  # not a BFC arena OOM — propagate unchanged
                ctx = _worker_ctx.get_worker_context()
                if ctx is None:
                    raise  # probe / test context — no DB, cannot self-heal
                db, _ = ctx
                new_limit = update_model_vram_from_oom(db, self._path, requested)
                logger.warning(
                    "[model] BFC OOM on %s (requested=%d bytes) — "
                    "updated DB limit to %d bytes; reloading (will fall to CPU if still too large)",
                    self._path,
                    requested,
                    new_limit,
                )
                # Force a reload to pick up the updated VRAM limit from DB.
                # Cannot use self.device = "gpu" here — the setter is a no-op
                # when _device is already "gpu" (session failed at inference
                # time, not at load time).
                self.unload()
                try:
                    self.load("gpu")
                except VramFitError:
                    # Coordinator rejected the larger limit — not enough free
                    # VRAM in the fleet.  Model is already on CPU after the
                    # VramFitError path in load().  Loop will see
                    # self._device == "cpu" and raise on next iteration.
                    self.load("cpu")
