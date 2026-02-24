"""ONNXHeadModel: classification / regression head wrapper for ONNX models.

Head models accept embedding vectors produced by a backbone and return
per-class activation scores.  Unlike backbone models, head node names and
tensor dimensions are not fixed in advance; they are introspected from the
loaded ONNX session at :meth:`load` time and cached as attributes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.components.ml.ml_inference_comp import _run_in_batches
from nomarr.components.ml.ml_onnx_base import BaseONNXModel
from nomarr.components.ml.ml_onnx_types import MODEL_SUITE_VERSION, Sidecar

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


def _read_labels(path: str) -> list[str]:
    """Read class labels from the co-located sidecar JSON, if present.

    Looks for a ``.json`` file with the same base name as the ``.onnx`` file.
    Checks the ``"classes"`` and ``"labels"`` keys, in that order.  Returns
    an empty list if the file does not exist or contains no recognised key.

    Args:
        path: Absolute path to the ``.onnx`` file.

    Returns:
        List of class label strings (may be empty).
    """
    labels_path = Path(path).with_suffix(".json")
    if not labels_path.exists():
        return []
    try:
        data = json.loads(labels_path.read_text(encoding="utf-8"))
        return list(data.get("classes") or data.get("labels") or [])
    except (json.JSONDecodeError, OSError):
        logger.warning("[head] Failed to read labels from %s", labels_path)
        return []



def _read_sidecar_json(path: str) -> dict[str, Any]:
    """Read the co-located JSON sidecar for an ONNX file.

    Looks for a ``.json`` file with the same base name as the ``.onnx`` file
    and returns the parsed content.  Returns an empty dict if the file does
    not exist or cannot be parsed.

    Args:
        path: Absolute path to the ``.onnx`` file.

    Returns:
        Parsed sidecar data, or ``{}`` on failure.
    """
    json_path = Path(path).with_suffix(".json")
    if not json_path.exists():
        return {}
    try:
        return dict(json.loads(json_path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        logger.warning("[head] Failed to read sidecar from %s", json_path)
        return {}


def _find_backbone_sidecar_json(head_onnx_path: str) -> dict[str, Any]:
    """Locate and read the backbone embedding sidecar JSON for a head model.

    Directory convention::

        models/<backbone>/heads/<head_type>/<model>.onnx
        models/<backbone>/embeddings/<backbone>.json   ← backbone sidecar

    Navigates three levels up from the ``.onnx`` file to reach the backbone
    root, then searches the ``embeddings`` (or ``embedding``) sub-directory
    for the first ``.json`` file.

    Args:
        head_onnx_path: Absolute path to the head ``.onnx`` file.

    Returns:
        Parsed backbone sidecar data, or ``{}`` if not found.
    """
    backbone_dir = Path(head_onnx_path).parent.parent.parent
    for emb_dir_name in ("embeddings", "embedding"):
        emb_dir = backbone_dir / emb_dir_name
        if emb_dir.is_dir():
            for json_file in sorted(emb_dir.glob("*.json")):
                try:
                    return dict(json.loads(json_file.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    continue
    return {}
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
    """Class label strings read from the co-located JSON sidecar; may be empty."""

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

    def __init__(self, path: str) -> None:
        """Initialise the head model wrapper.

        Args:
            path: Absolute path to the head ``.onnx`` file.
        """
        super().__init__(path)
        self.backbone_name, self.head_type, self.model_name = _head_parts_from_path(path)
        self.labels = _read_labels(path)
        self.is_regression = self.head_type == "identity"
        self.input_node = None
        self.output_node = None
        self.input_dim = None
        self.num_classes = None
        self._head_data: dict[str, Any] = _read_sidecar_json(path)
        self._backbone_data: dict[str, Any] = _find_backbone_sidecar_json(path)
        _json_path = str(Path(path).with_suffix(".json"))
        self._sidecar = Sidecar(_json_path, self._head_data)

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

    def run(self, embeddings: np.ndarray) -> np.ndarray:
        """Run head inference on a batch of embedding vectors.

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
        """Display name from sidecar data, falling back to the model filename stem.

        Checks ``"name"`` then ``"head_name"`` keys in the sidecar JSON before
        returning :attr:`model_name` as a last resort.
        """
        return (
            self._head_data.get("name")
            or self._head_data.get("head_name")
            or self.model_name
        )

    def build_versioned_tag_key(
        self,
        label: str,
        calib_method: str = "none",
        calib_version: int = 0,
    ) -> tuple[str, str]:
        """Build a versioned tag key mirroring the :meth:`HeadInfo.build_versioned_tag_key` format.

        Format::

            {label}_{suite_version}_{backbone}{embedder_date}_{label}{head_date}

        Release dates are read from the sidecar JSON files:
        - backbone embedder date → :attr:`_backbone_data`
        - head release date → :attr:`_head_data`

        Args:
            label: Normalised tag label (e.g. ``"happy"``).
            calib_method: Calibration method string (default ``"none"``).
            calib_version: Calibration version integer (default ``0``).

        Returns:
            ``(model_key, calibration_id)`` tuple matching the HeadInfo convention.
        """

        embedder_release = self._backbone_data.get("release_date", "")
        embedder_date = embedder_release.replace("-", "") if embedder_release else "unknown"
        head_release = self._head_data.get("release_date", "")
        head_date = head_release.replace("-", "") if head_release else "unknown"
        embedder_part = f"{self.backbone_name}{embedder_date}"
        head_part = f"{label}{head_date}"
        model_key = f"{label}_{MODEL_SUITE_VERSION}_{embedder_part}_{head_part}"
        calibration_id = f"{calib_method}_{calib_version}"
        return (model_key, calibration_id)
