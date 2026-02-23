"""Base class for ONNX model session lifecycle management.

All ONNX model wrappers in nomarr inherit from ``BaseONNXModel``, which owns
the ``InferenceSession`` lifecycle. Subclasses derive metadata from the
``.onnx`` path in their ``__init__`` and implement :meth:`run`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

import numpy as np

from nomarr.components.ml import ml_backend_onnx_comp as backend_onnx

if TYPE_CHECKING:
    import onnxruntime as ort

logger = logging.getLogger(__name__)

DevicePlacement = Literal["cpu", "gpu"]
"""Device on which an ONNX session is loaded.  Matches Essentia C++ values."""


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
        """Create and store an ONNX session on *device*.

        Blocks until the session is ready. Replaces any existing session.

        Args:
            device: ``"cpu"`` or ``"gpu"``.
        """
        self._session = backend_onnx.create_session(self._path, device)
        self._device = device

    def unload(self) -> None:
        """Release the ONNX session and free associated memory."""
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

        No-op if already loaded on the requested device.
        """
        if value == self._device:
            return
        self.unload()
        self.load(value)

    # ------------------------------------------------------------------
    # Inference (subclass responsibility)
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, inputs: np.ndarray) -> np.ndarray:
        """Run inference on *inputs*.

        Raises:
            RuntimeError: If the model is not loaded.
        """
