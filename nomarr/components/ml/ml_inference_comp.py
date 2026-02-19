"""Low-level TensorFlow model inference operations.

Handles embedding computation, head prediction, and batched processing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.components.ml import ml_backend_essentia_comp as backend_essentia

logger = logging.getLogger(__name__)

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

    from nomarr.components.ml.ml_cache_comp import DevicePlacement
    from nomarr.components.ml.ml_discovery_comp import HeadInfo
    from nomarr.helpers.dto.ml_dto import ComputeEmbeddingsForBackboneParams






def _create_backbone_predictor(backbone: str, emb_graph: str, device_placement: DevicePlacement = "gpu") -> Any:
    """Construct a backbone embedding predictor.

    This is the expensive operation (graph parse + session creation) that should
    be done once and cached. Session persists after creation (no-op reset).

    Predictor instantiation triggers GPU enumeration from TensorFlow's C++ library,
    which emits logs directly to stderr before absl::InitializeLog(). We filter
    these at the fd level to keep logs clean.

    Args:
        backbone: Backbone name (yamnet, vggish, effnet, musicnn)
        emb_graph: Path to the embedding model graph file
        device_placement: Device for TF session ("cpu" or "gpu")
    """
    backend_essentia.require()
    from nomarr.components.ml.ml_discovery_comp import get_embedding_output_node

    emb_output = get_embedding_output_node(backbone)

    # Wrap predictor creation in stderr filter to suppress C++ GPU logs
    with backend_essentia.filter_tf_stderr():
        if backbone == "yamnet":
            if TensorflowPredictVGGish is None:
                msg = "TensorflowPredictVGGish not available"
                raise RuntimeError(msg)
            predictor = TensorflowPredictVGGish(graphFilename=emb_graph, input="melspectrogram", output=emb_output, devicePlacement=device_placement)
        elif backbone == "vggish":
            if TensorflowPredictVGGish is None:
                msg = "TensorflowPredictVGGish not available"
                raise RuntimeError(msg)
            predictor = TensorflowPredictVGGish(graphFilename=emb_graph, output=emb_output, devicePlacement=device_placement)
        elif backbone == "effnet":
            if TensorflowPredictEffnetDiscogs is None:
                msg = "TensorflowPredictEffnetDiscogs not available"
                raise RuntimeError(msg)
            predictor = TensorflowPredictEffnetDiscogs(graphFilename=emb_graph, output=emb_output, patchHopSize=93, devicePlacement=device_placement)
        elif backbone == "musicnn":
            if TensorflowPredictMusiCNN is None:
                msg = "TensorflowPredictMusiCNN not available"
                raise RuntimeError(msg)
            predictor = TensorflowPredictMusiCNN(graphFilename=emb_graph, output=emb_output, patchHopSize=128, devicePlacement=device_placement)
        else:
            msg = f"Unsupported backbone {backbone}"
            raise RuntimeError(msg)

    logger.debug(f"[inference] Created backbone predictor for {backbone} (device={device_placement})")
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
    from nomarr.components.ml.ml_cache_comp import (
        cache_backbone_predictor,
        evict_backbone_predictor,
        get_cached_backbone_device,
        get_cached_backbone_predictor,
    )

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
    # Device-aware cache: check if cached predictor is on the desired device
    desired_device: DevicePlacement = "gpu" if params.prefer_gpu else "cpu"
    if not params.prefer_gpu:
        logger.info(f"[inference] CPU spill requested for {params.backbone} (GPU VRAM pressure detected)")
    cached_device = get_cached_backbone_device(params.backbone, params.emb_graph)
    if cached_device is not None and cached_device != desired_device:
        # Device transition: evict and recreate
        logger.info(f"[inference] Device transition for {params.backbone}: {cached_device} → {desired_device}")
        evict_backbone_predictor(params.backbone, params.emb_graph)
        emb_predictor = _create_backbone_predictor(params.backbone, params.emb_graph, device_placement=desired_device)
        cache_backbone_predictor(params.backbone, params.emb_graph, emb_predictor, device=desired_device)
    elif cached_device is not None:
        # Cached on correct device
        emb_predictor = get_cached_backbone_predictor(params.backbone, params.emb_graph)
        logger.debug(f"[inference] Using cached {params.backbone} backbone predictor (device={cached_device})")
    else:
        # Not cached — create fresh
        logger.info(f"[inference] Creating {params.backbone} backbone predictor (device={desired_device}, not cached)")
        emb_predictor = _create_backbone_predictor(params.backbone, params.emb_graph, device_placement=desired_device)
        cache_backbone_predictor(params.backbone, params.emb_graph, emb_predictor, device=desired_device)
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



def _create_head_only_predictor(head_info: HeadInfo, device_placement: DevicePlacement = "cpu") -> Any:
    """Construct a TensorflowPredict2D object for a head model.

    This is the expensive operation (graph parse + session creation) that should
    be done once and cached. Session persists after creation (no-op reset).

    Predictor instantiation triggers GPU enumeration from TensorFlow's C++ library,
    which emits logs directly to stderr before absl::InitializeLog(). We filter
    these at the fd level to keep logs clean.

    Args:
        head_info: Head metadata and model paths
        device_placement: Device for TF session ("cpu" or "gpu")
    """
    backend_essentia.require()
    from nomarr.components.ml.ml_discovery_comp import get_head_output_node

    head_graph = head_info.sidecar.graph_abs("")
    head_output = get_head_output_node(head_info.head_type, head_info.sidecar)
    head_input = head_info.sidecar.head_input_name()

    # Wrap predictor creation in stderr filter to suppress C++ GPU logs
    with backend_essentia.filter_tf_stderr():
        if head_input:
            head_predictor = TensorflowPredict2D(graphFilename=head_graph, input=head_input, output=head_output, devicePlacement=device_placement)
        else:
            head_predictor = TensorflowPredict2D(graphFilename=head_graph, output=head_output, devicePlacement=device_placement)

    logger.debug(f"[inference] Created head-only predictor for {head_info.name} ({head_info.backbone}/{head_info.head_type}) device={device_placement}")
    return head_predictor


def make_head_only_predictor_batched(
    head_info: HeadInfo, embeddings_2d: np.ndarray, batch_size: int = 11,
    device_placement: DevicePlacement = "cpu",
) -> Callable[[], np.ndarray]:
    """Create a batched predictor that processes segments in fixed-size batches.
    Returns a function that takes no args and returns predictions for all segments.

    Uses cached head-only predictor when available (populated at warmup or on first
    use). The TensorflowPredict2D construction is expensive (model graph parse +
    session setup), but once cached, reuse is essentially free.

    Supports device transitions: if cached on a different device than requested,
    evicts and recreates on the desired device.

    Args:
        head_info: Head metadata and model paths
        embeddings_2d: Pre-computed embeddings [num_segments, embed_dim]
        batch_size: Fixed batch size for inference (default 11 segments = 60s)
        device_placement: Device for TF session ("cpu" or "gpu")

    Returns: Callable that returns [num_segments, num_classes] array

    """
    from nomarr.components.ml.ml_cache_comp import (
        cache_head_predictor,
        evict_head_predictor,
        get_cached_head_device,
        get_cached_head_predictor,
    )

    # Device-aware cache: check if cached predictor is on the desired device
    cached_device = get_cached_head_device(head_info)
    if cached_device is not None and cached_device != device_placement:
        # Device transition: evict and recreate
        logger.info(f"[inference] Device transition for head {head_info.name}: {cached_device} → {device_placement}")
        evict_head_predictor(head_info)
        head_predictor = _create_head_only_predictor(head_info, device_placement=device_placement)
        cache_head_predictor(head_info, head_predictor, device=device_placement)
    elif cached_device is not None:
        # Cached on correct device
        head_predictor = get_cached_head_predictor(head_info)
        logger.debug(f"[inference] Using cached head predictor for {head_info.name} (device={cached_device})")
    else:
        # Not cached — create fresh
        head_predictor = _create_head_only_predictor(head_info, device_placement=device_placement)
        cache_head_predictor(head_info, head_predictor, device=device_placement)
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
