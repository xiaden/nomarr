"""ONNXHeadModel: classification / regression head wrapper for ONNX models.

Head models accept embedding vectors produced by a backbone and return
per-class activation scores.  Unlike backbone models, head node names and
tensor dimensions are not fixed in advance; they are introspected from the
loaded ONNX session at :meth:`load` time and cached as attributes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from nomarr.components.ml.ml_inference_comp import _run_in_batches
from nomarr.components.ml.ml_onnx_base import BaseONNXModel
from nomarr.components.ml.ml_onnx_types import MODEL_SUITE_VERSION

if TYPE_CHECKING:
    from nomarr.components.ml.ml_onnx_base import DevicePlacement

logger = logging.getLogger(__name__)

_HEAD_BATCH_SIZE = 11
"""Number of embedding rows per ONNX forward pass for head classification models.

Smaller than the backbone batch size: head batches are already-computed
embeddings (cheap) rather than mel patches, so a modest batch size is
sufficient to bound memory without sacrificing throughput.
"""


def _head_parts_from_path(path: str) -> tuple[str, str, str]:
    """Derive backbone name, head type, and model name from a head ONNX path.

    Expects the conventional directory structure::

        models/<backbone>/heads/<head_type>/<model_name>.onnx

    Args:
        path: Absolute or relative path to the head ``.onnx`` file.

    Returns:
        ``(backbone_name, head_type, model_name)`` tuple.

    Raises:
        ValueError: If no ``heads`` segment is found in the path.
    """
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part == "heads" and i >= 2:
            backbone_name = parts[i - 1]
            head_type = parts[i + 1]
            model_name = Path(path).stem
            return backbone_name, head_type, model_name
    msg = f"Cannot derive head info from path: {path!r}"
    raise ValueError(msg)



class ONNXHeadModel(BaseONNXModel):
    """ONNX wrapper for classification and regression head models.

    Accepts a float32 embedding matrix of shape ``(n_patches, embed_dim)``
    and returns a float32 activation matrix of shape
    ``(n_patches, num_classes)``.

    Node names, tensor dimensions, and regression flag are resolved at
    :meth:`load` time; the attributes are ``None`` until the model is loaded.

    Example usage::

        model = ONNXHeadModel("/models/effnet/heads/sigmoid/happy.onnx")
        model.load("cpu")
        scores = model.run(embeddings)   # shape: (n_patches, num_classes)
        model.unload()
    """

    backbone_name: str
    """Backbone the head was trained against (e.g. ``"effnet"``)"""

    head_type: str
    """ONNX activation type directory name (e.g. ``"sigmoid"``, ``"identity"``)"""

    model_name: str
    """Stem of the ONNX filename (e.g. ``"happy"``)."""

    labels: list[str]
    """Class label strings; injected via constructor or empty."""

    is_regression: bool
    """True when *head_type* is ``"identity"`` (linear activation → regression)."""

    input_node: str | None
    """ONNX input tensor name; resolved by :meth:`load`, ``None`` before then."""

    output_node: str | None
    """ONNX output tensor name; resolved by :meth:`load`, ``None`` before then."""

    input_dim: int | None
    """Embedding dimension expected by this head; resolved at :meth:`load` time."""

    num_classes: int | None
    """Number of output activations; resolved at :meth:`load` time."""

    def __init__(
        self,
        path: str,
        *,
        labels: list[str] | None = None,
        head_release_date: str = "",
        embedder_release_date: str = "",
    ) -> None:
        """Initialise the head model wrapper.

        Args:
            path: Absolute path to the head ``.onnx`` file.
            labels: Class label strings.  When ``None`` (default) labels
                are left empty — the caller is responsible for injecting
                labels read from the database.
            head_release_date: ISO date string (e.g. ``"2022-08-25"``).
            embedder_release_date: ISO date string for the backbone embedder.
        """
        super().__init__(path)
        self.backbone_name, self.head_type, self.model_name = _head_parts_from_path(path)
        self.labels = list(labels) if labels is not None else []
        self.is_regression = self.head_type == "identity"
        self.input_node = None
        self.output_node = None
        self.input_dim = None
        self.num_classes = None
        self._head_release_date = head_release_date
        self._embedder_release_date = embedder_release_date

    def load(self, device: DevicePlacement) -> None:
        """Load the ONNX session and resolve tensor metadata.

        After calling :meth:`load`, ``input_node``, ``output_node``,
        ``input_dim``, and ``num_classes`` are all populated from the session.

        Args:
            request: Load parameters forwarded to :meth:`BaseONNXModel.load`.

        Raises:
            VramFitError: If ``request.device == "gpu"`` and the VRAM
                coordinator rejects the GPU placement request.
        """
        super().load(device)
        assert self._session is not None  # guaranteed by super().load()
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        self.input_node = inputs[0].name
        self.output_node = outputs[0].name
        input_shape = inputs[0].shape
        output_shape = outputs[0].shape
        self.input_dim = int(input_shape[1]) if len(input_shape) >= 2 else None
        self.num_classes = int(output_shape[1]) if len(output_shape) >= 2 else None
        logger.debug(
            "[head] Loaded %s/%s/%s: input=%s(%s) output=%s(%s) device=%s",
            self.backbone_name,
            self.head_type,
            self.model_name,
            self.input_node,
            self.input_dim,
            self.output_node,
            self.num_classes,
            self._device,
        )

    def unload(self) -> None:
        """Unload the ONNX session and reset all tensor metadata."""
        super().unload()
        self.input_node = None
        self.output_node = None
        self.input_dim = None
        self.num_classes = None

    def _run(self, embeddings: np.ndarray) -> np.ndarray:
        """Run head inference on a batch of embedding vectors.

        Called by :meth:`BaseONNXModel.run`, which wraps this with BFC OOM
        recovery.  Do not call this directly.

        Args:
            embeddings: Float32 array of shape ``(n_patches, embed_dim)``.

        Returns:
            Float32 activation array of shape ``(n_patches, num_classes)``.

        Raises:
            RuntimeError: If the model has not been loaded.
        """
        if self._session is None:
            msg = "ONNXHeadModel is not loaded — call load() first"
            raise RuntimeError(msg)

        session = self._session  # local ref so mypy sees it as non-None inside closure
        input_node = self.input_node
        output_node = self.output_node

        def _session_fn(batch: np.ndarray) -> np.ndarray:
            result = session.run([output_node], {input_node: batch.astype(np.float32)})
            return np.asarray(result[0], dtype=np.float32)

        return _run_in_batches(_session_fn, embeddings, _HEAD_BATCH_SIZE)


    @property
    def name(self) -> str:
        """Display name derived from the ONNX filename stem."""
        return self.model_name

    def build_versioned_tag_key(
        self,
        label: str,
        calib_method: str = "none",
        calib_version: int = 0,
    ) -> tuple[str, str]:
        """Build a versioned tag key mirroring :meth:`HeadInfo.build_versioned_tag_key`.

        Format::

            {label}_{suite_version}_{backbone}{embedder_date}_{label}{head_date}

        Args:
            label: Normalised tag label (e.g. ``"happy"``).
            calib_method: Calibration method string (default ``"none"``).
            calib_version: Calibration version integer (default ``0``).

        Returns:
            ``(model_key, calibration_id)`` tuple matching the HeadInfo convention.
        """
        embedder_date = (
            self._embedder_release_date.replace("-", "")
            if self._embedder_release_date
            else "unknown"
        )
        head_date = (
            self._head_release_date.replace("-", "")
            if self._head_release_date
            else "unknown"
        )
        embedder_part = f"{self.backbone_name}{embedder_date}"
        head_part = f"{label}{head_date}"
        model_key = f"{label}_{MODEL_SUITE_VERSION}_{embedder_part}_{head_part}"
        calibration_id = f"{calib_method}_{calib_version}"
        return (model_key, calibration_id)
