"""ONNXBackboneModel: embedding-extractor wrapper for backbone ONNX models.

Backbone models consume mel-spectrogram patches and produce per-patch embedding
vectors.  For each backbone the ONNX graph exposes a fixed input node
(``"melspectrogram"``) and a fixed output node (``"embeddings"``).

The model stores no per-inference state; all inference context lives in the
``ort.InferenceSession`` owned by the parent ``BaseONNXModel``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from nomarr.components.ml.audio.ml_preprocess_comp import get_params, preprocess_for_backbone
from nomarr.components.ml.onnx.ml_base import BaseONNXModel
from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches

if TYPE_CHECKING:
    from nomarr.components.ml.audio.ml_preprocess_comp import BackbonePreprocessParams

logger = logging.getLogger(__name__)


def _backbone_name_from_path(path: str) -> str:
    """Derive backbone identifier from an embeddings ONNX path.

    Expects the conventional directory structure::

        models/<backbone>/embeddings/<file>.onnx
        models/<backbone>/embedding/<file>.onnx  # musicnn variant

    Args:
        path: Absolute or relative path to the backbone ``.onnx`` file.

    Returns:
        Backbone identifier, e.g. ``"effnet"``, ``"musicnn"``.

    Raises:
        ValueError: If no ``embeddings``/``embedding`` segment is found.
    """
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part in {"embeddings", "embedding"} and i > 0:
            return parts[i - 1]
    msg = f"Cannot derive backbone name from path: {path!r}"
    raise ValueError(msg)


class ONNXBackboneModel(BaseONNXModel):
    """ONNX wrapper for embedding-extractor backbone models.

    Takes a mono float32 waveform at 16 kHz and returns a float32 array of
    shape ``(n_patches, embed_dim)`` where *embed_dim* depends on the backbone.

    Preprocessing (mel-spectrogram + patch extraction) is performed inside
    :meth:`run` using parameters resolved from *path* at construction time.

    Example usage::

        model = ONNXBackboneModel("/models/effnet/embeddings/effnet.onnx")
        model.load("gpu")
        embeddings = model.run(waveform)   # shape: (n_patches, 512)
        model.unload()
    """

    backbone_name: str
    """Backbone identifier derived from the model path (e.g. ``"effnet"``)"""

    input_node: str
    """ONNX input tensor name — always ``"melspectrogram"`` for backbones."""

    output_node: str
    """ONNX output tensor name — always ``"embeddings"`` for backbones."""

    preprocess_params: BackbonePreprocessParams
    """Preprocessing parameters (mel bins, patch frames, hop) for this backbone."""

    def __init__(self, path: str) -> None:
        """Initialise the backbone model wrapper.

        Args:
            path: Absolute path to the backbone ``.onnx`` file.
        """
        super().__init__(path)
        self.backbone_name = _backbone_name_from_path(path)
        self.input_node = "melspectrogram"
        self.output_node = "embeddings"
        self.preprocess_params = get_params(self.backbone_name)

    def _run(self, waveform: np.ndarray) -> np.ndarray:
        """Run backbone inference on a mono float32 waveform.

        Called by :meth:`BaseONNXModel.run`, which wraps this with BFC OOM
        recovery.  Do not call this directly.

        Args:
            waveform: Mono float32 audio at 16 kHz.

        Returns:
            Float32 embedding matrix of shape ``(n_patches, embed_dim)``.

        Raises:
            RuntimeError: If the model has not been loaded or the waveform is
                too short to produce any patches.
        """
        if self._session is None:
            msg = "ONNXBackboneModel is not loaded — call load() first"
            raise RuntimeError(msg)

        patches = preprocess_for_backbone(waveform, self.backbone_name)
        if patches.shape[0] == 0:
            msg = (
                f"No patches produced for backbone {self.backbone_name!r} "
                "— audio may be too short"
            )
            raise RuntimeError(msg)

        session = self._session  # local ref so mypy sees it as non-None inside closure

        def _session_fn(batch: np.ndarray) -> np.ndarray:
            result = session.run([self.output_node], {self.input_node: batch})
            return np.asarray(result[0], dtype=np.float32)

        return _run_in_batches(_session_fn, patches, _BACKBONE_BATCH_SIZE)
