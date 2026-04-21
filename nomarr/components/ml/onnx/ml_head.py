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

from nomarr.components.ml.onnx.ml_base import BaseONNXModel
from nomarr.components.ml.onnx.ml_session_comp import _run_in_batches

if TYPE_CHECKING:
    from nomarr.components.ml.onnx.ml_base import DevicePlacement
    from nomarr.helpers.dto.ml_head_dto import HeadInfo

logger = logging.getLogger(__name__)

_HEAD_BATCH_SIZE = 11
"""Number of embedding rows per ONNX forward pass for head classification models.

Smaller than the backbone batch size: head batches are already-computed
embeddings (cheap) rather than mel patches, so a modest batch size is
sufficient to bound memory without sacrificing throughput.
"""


def head_parts_from_path(path: str) -> tuple[str, str, str]:
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

    Node names and tensor dimensions are resolved at
    :meth:`load` time; the attributes are ``None`` until the model is loaded.

    Example usage::

        model = ONNXHeadModel("/models/effnet/heads/sigmoid/happy.onnx", meta=head_info)
        model.load("cpu")
        scores = model.run(embeddings)  # shape: (n_patches, num_classes)
        model.unload()
    """

    meta: HeadInfo
    """Head model metadata."""

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
        meta: HeadInfo,
    ) -> None:
        """Initialise the head model wrapper.

        Args:
            path: Absolute path to the head ``.onnx`` file.
            meta: Head metadata describing labels, backbone, and model identity.
        """
        super().__init__(path)
        self.meta = meta
        self.input_node = None
        self.output_node = None
        self.input_dim = None
        self.num_classes = None

    def load(self, device: DevicePlacement) -> None:
        """Load the ONNX session and resolve tensor metadata.

        After calling :meth:`load`, ``input_node``, ``output_node``,
        ``input_dim``, and ``num_classes`` are all populated from the session.

        Args:
            device: Device placement for the ONNX session (e.g. ``"cpu"`` or ``"gpu"``).

        Raises:
            VramFitError: If ``device == "gpu"`` and the VRAM
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
            self.meta.backbone,
            self.meta.head_type,
            self.meta.model_stem,
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
