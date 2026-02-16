"""Low-level TensorFlow model inference operations.

Handles embedding computation, head prediction, and batched processing.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.components.ml import ml_backend_essentia_comp as backend_essentia

logger = logging.getLogger(__name__)
try:
    import tensorflow as tf

    HAVE_TF = True
except ImportError:
    HAVE_TF = False
    tf = None  # type: ignore[assignment]

if backend_essentia.essentia_tf is not None:
    TensorflowPredict2D = backend_essentia.essentia_tf.TensorflowPredict2D
    try:
        eslog = backend_essentia.essentia_tf.log
        eslog.setLevel(eslog.ERROR)
    except (ImportError, AttributeError):
        pass
    try:
        TensorflowPredictEffnetDiscogs = backend_essentia.essentia_tf.TensorflowPredictEffnetDiscogs
    except AttributeError:
        TensorflowPredictEffnetDiscogs = None
    try:
        TensorflowPredictMusiCNN = backend_essentia.essentia_tf.TensorflowPredictMusiCNN
    except AttributeError:
        TensorflowPredictMusiCNN = None
    try:
        TensorflowPredictVGGish = backend_essentia.essentia_tf.TensorflowPredictVGGish
    except AttributeError:
        TensorflowPredictVGGish = None
else:
    TensorflowPredict2D = None
    TensorflowPredictEffnetDiscogs = None
    TensorflowPredictMusiCNN = None
    TensorflowPredictVGGish = None
if TYPE_CHECKING:
    from collections.abc import Callable

    from nomarr.components.ml.ml_discovery_comp import HeadInfo
    from nomarr.helpers.dto.ml_dto import ComputeEmbeddingsForBackboneParams






def _create_backbone_predictor(backbone: str, emb_graph: str) -> Any:
    """Construct a backbone embedding predictor.

    This is the expensive operation (graph parse + session creation) that should
    be done once and cached. Runs on GPU for maximum throughput.
    """
    backend_essentia.require()
    from nomarr.components.ml.ml_discovery_comp import get_embedding_output_node

    emb_output = get_embedding_output_node(backbone)
    if backbone == "yamnet":
        if TensorflowPredictVGGish is None:
            msg = "TensorflowPredictVGGish not available"
            raise RuntimeError(msg)
        predictor = TensorflowPredictVGGish(graphFilename=emb_graph, input="melspectrogram", output=emb_output)
    elif backbone == "vggish":
        if TensorflowPredictVGGish is None:
            msg = "TensorflowPredictVGGish not available"
            raise RuntimeError(msg)
        predictor = TensorflowPredictVGGish(graphFilename=emb_graph, output=emb_output)
    elif backbone == "effnet":
        if TensorflowPredictEffnetDiscogs is None:
            msg = "TensorflowPredictEffnetDiscogs not available"
            raise RuntimeError(msg)
        predictor = TensorflowPredictEffnetDiscogs(graphFilename=emb_graph, output=emb_output, patchHopSize=93)
    elif backbone == "musicnn":
        if TensorflowPredictMusiCNN is None:
            msg = "TensorflowPredictMusiCNN not available"
            raise RuntimeError(msg)
        predictor = TensorflowPredictMusiCNN(graphFilename=emb_graph, output=emb_output, patchHopSize=128)
    else:
        msg = f"Unsupported backbone {backbone}"
        raise RuntimeError(msg)
    logger.debug(f"[inference] Created backbone predictor for {backbone}")
    return predictor


def compute_embeddings_for_backbone(params: ComputeEmbeddingsForBackboneParams) -> tuple[np.ndarray, float, str]:
    """Compute embeddings for an audio file using a specific backbone.

    Uses cached backbone predictors when available to avoid repeated model loading.
    The backbone models (YAMNet, EffNet) internally create patches with their own
    segment/hop sizes. We feed the entire audio clip to get all patches in one call,
    preserving temporal resolution.

    When pre_loaded_audio and pre_computed_chromaprint are provided on params,
    audio loading and chromaprint computation are skipped (caller already did them).

    Args:
        params: Parameters including backbone, emb_graph, target_sr, segment_s, hop_s,
                path, min_duration_s, allow_short

    Returns: (embeddings_2d, duration, chromaprint) where embeddings_2d is (num_patches, embed_dim),
              num_patches depends on the backbone's internal patching (not our segment_s/hop_s),
              duration is in seconds, and chromaprint is the audio fingerprint hash

    """
    backend_essentia.require()
    from nomarr.components.ml.ml_audio_comp import load_audio_mono, should_skip_short
    from nomarr.components.ml.ml_cache_comp import cache_backbone_predictor, get_cached_backbone_predictor

    if params.pre_loaded_audio is not None:
        audio_result = params.pre_loaded_audio
    else:
        audio_result = load_audio_mono(params.path, target_sr=params.target_sr)
    if should_skip_short(audio_result.duration, params.min_duration_s, params.allow_short):
        msg = f"audio too short ({audio_result.duration:.2f}s < {params.min_duration_s}s)"
        raise RuntimeError(msg)

    if params.pre_computed_chromaprint is not None:
        chromaprint = params.pre_computed_chromaprint
    else:
        from nomarr.components.ml.chromaprint_comp import compute_chromaprint

        chromaprint = compute_chromaprint(audio_result.waveform, audio_result.sample_rate)
    logger.debug(
        f"[inference] Processing full track: {audio_result.duration:.1f}s ({len(audio_result.waveform)} samples @ {audio_result.sample_rate}Hz)",
    )
    if not params.prefer_gpu:
        logger.info(f"[inference] CPU spill requested for {params.backbone} (GPU VRAM pressure detected)")
    emb_predictor = get_cached_backbone_predictor(params.backbone, params.emb_graph)
    if emb_predictor is None:
        logger.info(f"[inference] Creating {params.backbone} backbone predictor (device=GPU, not cached)")
        emb_predictor = _create_backbone_predictor(params.backbone, params.emb_graph)
        cache_backbone_predictor(params.backbone, params.emb_graph, emb_predictor)
    else:
        logger.debug(f"[inference] Using cached {params.backbone} backbone predictor (device=GPU)")
    wave_f32 = audio_result.waveform.astype(np.float32)
    emb = emb_predictor(wave_f32)
    emb = np.asarray(emb, dtype=np.float32)
    logger.debug(
        f"[inference] {params.backbone} backbone output shape: {emb.shape} (audio input: {len(wave_f32)} samples @ {audio_result.sample_rate}Hz = {len(wave_f32) / audio_result.sample_rate:.2f}s)",
    )
    embeddings_2d: np.ndarray
    if emb.ndim == 1:
        logger.debug("[inference] Backbone returned 1D embedding (already pooled)")
        embeddings_2d = emb.reshape(1, -1)
    elif emb.ndim == 2:
        logger.debug(f"[inference] Backbone returned 2D patches: {emb.shape[0]} patches x {emb.shape[1]} dims")
        embeddings_2d = emb
    elif emb.ndim == 3:
        logger.warning(f"[inference] Backbone returned 3D output: {emb.shape}, averaging first two dimensions")
        embeddings_2d = np.mean(emb, axis=(0, 1)).reshape(1, -1)
    else:
        logger.warning(f"[inference] Unexpected backbone output shape: {emb.shape}, flattening to 1D")
        embeddings_2d = emb.reshape(1, -1)
    logger.debug(
        f"[inference] Computed {embeddings_2d.shape[0]} patches for {params.backbone}: shape={embeddings_2d.shape} duration={audio_result.duration:.1f}s",
    )
    return (embeddings_2d, audio_result.duration, chromaprint)



def _create_head_only_predictor(head_info: HeadInfo) -> Any:
    """Construct a TensorflowPredict2D object for a head model.

    This is the expensive operation (graph parse + session creation) that should
    be done once and cached. Runs on CPU to avoid GPU VRAM contention with
    backbone models.
    """
    backend_essentia.require()
    from nomarr.components.ml.ml_discovery_comp import get_head_output_node

    head_graph = head_info.sidecar.graph_abs("")
    head_output = get_head_output_node(head_info.head_type, head_info.sidecar)
    head_input = head_info.sidecar.head_input_name()
    device_context = tf.device("/CPU:0") if HAVE_TF and tf is not None else contextlib.nullcontext()
    with device_context:
        if head_input:
            head_predictor = TensorflowPredict2D(graphFilename=head_graph, input=head_input, output=head_output)
        else:
            head_predictor = TensorflowPredict2D(graphFilename=head_graph, output=head_output)
    logger.debug(f"[inference] Created head-only predictor for {head_info.name} ({head_info.backbone}/{head_info.head_type})")
    return head_predictor


def make_head_only_predictor_batched(
    head_info: HeadInfo, embeddings_2d: np.ndarray, batch_size: int = 11,
) -> Callable[[], np.ndarray]:
    """Create a batched predictor that processes segments in fixed-size batches.
    Returns a function that takes no args and returns predictions for all segments.

    Uses cached head-only predictor when available (populated at warmup or on first
    use). The TensorflowPredict2D construction is expensive (model graph parse +
    session setup), but once cached, reuse is essentially free.

    Args:
        head_info: Head metadata and model paths
        embeddings_2d: Pre-computed embeddings [num_segments, embed_dim]
        batch_size: Fixed batch size for inference (default 11 segments = 60s)

    Returns: Callable that returns [num_segments, num_classes] array

    """
    from nomarr.components.ml.ml_cache_comp import cache_head_predictor, get_cached_head_predictor

    head_predictor = get_cached_head_predictor(head_info)
    if head_predictor is None:
        head_predictor = _create_head_only_predictor(head_info)
        cache_head_predictor(head_info, head_predictor)
    embed_dim = head_info.sidecar.input_dim()

    def predict_all_segments() -> np.ndarray:
        """Process all segments in fixed-size batches."""
        batch_emb = embeddings_2d
        if embed_dim and batch_emb.shape[1] != embed_dim:
            if batch_emb.shape[1] > embed_dim:
                logger.warning(
                    f"[inference] ⚠️  DIMENSION TRUNCATION: {head_info.name} expects {embed_dim} dims but embeddings are {batch_emb.shape[1]} dims. Truncating batch.",
                )
                batch_emb = batch_emb[:, :embed_dim]
            else:
                msg = f"Embedding dimension mismatch for {head_info.name}: got {batch_emb.shape[1]}, expected {embed_dim} (cannot pad)"
                raise RuntimeError(msg)
        num_segments = batch_emb.shape[0]
        all_predictions = []
        for i in range(0, num_segments, batch_size):
            batch_slice = batch_emb[i : i + batch_size]
            batch_preds = head_predictor(batch_slice)
            batch_preds = np.asarray(batch_preds, dtype=np.float32)
            if batch_preds.ndim == 1:
                batch_preds = batch_preds.reshape(-1, 1)
            all_predictions.append(batch_preds)
        return np.vstack(all_predictions)

    return predict_all_segments
