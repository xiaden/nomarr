"""
Low-level TensorFlow model inference operations.

Handles embedding computation, head prediction, and batched processing.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

# Import TensorFlow for device placement (force head models to CPU)
try:
    import tensorflow as tf

    HAVE_TF = True
except ImportError:
    HAVE_TF = False
    tf = None

if TYPE_CHECKING:
    from nomarr.components.ml.models.discovery import HeadInfo

# TensorFlow logging and GPU settings (TF_CPP_MIN_LOG_LEVEL,
# TF_FORCE_GPU_ALLOW_GROWTH, TF_GPU_THREAD_MODE) are set in Dockerfile

# All Essentia imports go through the backend module
from nomarr.components.ml import ml_backend_essentia_comp as backend_essentia
from nomarr.helpers.dto.ml_dto import ComputeEmbeddingsForBackboneParams

# Check if Essentia is available, but don't fail at import time
# Functions will call backend_essentia.require() when they actually need Essentia
if backend_essentia.is_available():
    # Access Essentia classes through the backend
    TensorflowPredict2D = backend_essentia.essentia_tf.TensorflowPredict2D

    # Suppress Essentia INFO messages (e.g., "MusicExtractorSVM: no classifier models...")
    try:
        eslog = backend_essentia.essentia_tf.log
        eslog.setLevel(eslog.WARNING)
    except (ImportError, AttributeError):
        pass  # Older Essentia versions may not have log module

    # Optional specialized predictors (may not be available in all Essentia versions)
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
    # Essentia not available - set placeholders
    # Functions will fail with clear error when called
    TensorflowPredict2D = None
    TensorflowPredictEffnetDiscogs = None
    TensorflowPredictMusiCNN = None
    TensorflowPredictVGGish = None

if TYPE_CHECKING:
    from nomarr.components.ml.ml_discovery_comp import HeadInfo


def make_predictor_uncached(head_info: HeadInfo) -> Callable[[np.ndarray, int], np.ndarray]:
    """
    Build full two-stage predictor (waveform -> embedding -> head predictions).

    Used by cache warmup to pre-load all predictors at startup.
    Uses folder structure to determine backbone and embedding graph.
    """
    # Require Essentia at function call time (not module import time)
    backend_essentia.require()

    from nomarr.components.ml.ml_discovery_comp import get_embedding_output_node, get_head_output_node

    backbone = head_info.backbone
    emb_graph = head_info.embedding_graph
    head_graph = head_info.sidecar.graph_abs("")

    if not head_graph or not os.path.exists(head_graph):
        raise RuntimeError(f"Head graph not found for {head_info.name}")

    emb_output = get_embedding_output_node(backbone)

    emb_predictor = None
    if backbone == "yamnet":
        if TensorflowPredictVGGish is None:
            raise RuntimeError("TensorflowPredictVGGish not available")
        emb_predictor = TensorflowPredictVGGish(graphFilename=emb_graph, input="melspectrogram", output=emb_output)
    elif backbone == "vggish":
        if TensorflowPredictVGGish is None:
            raise RuntimeError("TensorflowPredictVGGish not available")
        emb_predictor = TensorflowPredictVGGish(graphFilename=emb_graph, output=emb_output)
    elif backbone == "effnet":
        if TensorflowPredictEffnetDiscogs is None:
            raise RuntimeError("TensorflowPredictEffnetDiscogs not available")
        emb_predictor = TensorflowPredictEffnetDiscogs(graphFilename=emb_graph, output=emb_output)
    elif backbone == "musicnn":
        if TensorflowPredictMusiCNN is None:
            raise RuntimeError("TensorflowPredictMusiCNN not available")
        emb_predictor = TensorflowPredictMusiCNN(graphFilename=emb_graph, output=emb_output)
    else:
        raise RuntimeError(f"Unsupported backbone {backbone}")

    head_output = get_head_output_node(head_info.head_type, head_info.sidecar)
    head_input = head_info.sidecar.head_input_name()

    if head_input:
        head_predictor = TensorflowPredict2D(graphFilename=head_graph, input=head_input, output=head_output)  # type: ignore[misc]
    else:
        head_predictor = TensorflowPredict2D(graphFilename=head_graph, output=head_output)  # type: ignore[misc]

    embed_dim = head_info.sidecar.input_dim()

    logging.info(
        f"[inference] Built predictor for {head_info.name}: "
        f"{backbone} ({emb_output}) -> {head_info.head_type} ({head_output})"
    )

    def predict_fn(wave: np.ndarray, sr: int) -> np.ndarray:
        """Two-stage predictor: wave -> embeddings -> predictions."""
        if sr != head_info.sidecar.sr:
            raise RuntimeError(f"Sample rate mismatch for {head_info.name}: got {sr}, expected {head_info.sidecar.sr}")

        wave_f32 = wave.astype(np.float32)
        # Suppress noisy Essentia/TF logs during inference
        embeddings = emb_predictor(wave_f32)
        embeddings = np.asarray(embeddings, dtype=np.float32)

        if embeddings.ndim == 1:
            pass
        elif embeddings.ndim == 2:
            if embeddings.shape[0] == 1:
                embeddings = embeddings.reshape(-1)
            else:
                embeddings = np.mean(embeddings, axis=0)
        elif embeddings.ndim == 3:
            embeddings = np.mean(embeddings, axis=(0, 1))
        else:
            embeddings = embeddings.reshape(-1)

        if embed_dim and embeddings.shape[0] != embed_dim:
            raise RuntimeError(
                f"Embedding dimension mismatch for {head_info.name}: got {embeddings.shape[0]}, expected {embed_dim}"
            )

        emb_input = embeddings.reshape(1, -1)
        predictions = head_predictor(emb_input)
        predictions = np.asarray(predictions, dtype=np.float32)

        if predictions.ndim > 1:
            predictions = predictions.reshape(-1)

        result: np.ndarray = predictions
        return result

    return predict_fn


def compute_embeddings_for_backbone(
    params: ComputeEmbeddingsForBackboneParams,
) -> tuple[np.ndarray, float]:
    """
    Compute embeddings for an audio file using a specific backbone.

    The backbone models (YAMNet, EffNet) internally create patches with their own
    segment/hop sizes. We feed the entire audio clip to get all patches in one call,
    preserving temporal resolution.

    Args:
        params: Parameters including backbone, emb_graph, target_sr, segment_s, hop_s,
                path, min_duration_s, allow_short

    Returns: (embeddings_2d, duration) where embeddings_2d is (num_patches, embed_dim)
              num_patches depends on the backbone's internal patching (not our segment_s/hop_s)
    """
    # Require Essentia at function call time (not module import time)
    backend_essentia.require()

    from nomarr.components.ml.ml_audio_comp import load_audio_mono, should_skip_short
    from nomarr.components.ml.ml_discovery_comp import get_embedding_output_node

    # Load audio (no manual segmentation - let the backbone do it)
    audio_result = load_audio_mono(params.path, target_sr=params.target_sr)
    if should_skip_short(audio_result.duration, params.min_duration_s, params.allow_short):
        raise RuntimeError(f"audio too short ({audio_result.duration:.2f}s < {params.min_duration_s}s)")

    # Process full track - no trimming
    # Trimming was removed because backbones process efficiently with single-pass
    # and trimming reduces accuracy by losing intro/outro information
    logging.debug(
        f"[inference] Processing full track: {audio_result.duration:.1f}s ({len(audio_result.waveform)} samples @ {audio_result.sample_rate}Hz)"
    )

    # Build embedding predictor for this backbone
    emb_output = get_embedding_output_node(params.backbone)

    if params.backbone == "yamnet":
        if TensorflowPredictVGGish is None:
            raise RuntimeError("TensorflowPredictVGGish not available")
        emb_predictor = TensorflowPredictVGGish(
            graphFilename=params.emb_graph, input="melspectrogram", output=emb_output
        )
    elif params.backbone == "vggish":
        if TensorflowPredictVGGish is None:
            raise RuntimeError("TensorflowPredictVGGish not available")
        emb_predictor = TensorflowPredictVGGish(graphFilename=params.emb_graph, output=emb_output)
    elif params.backbone == "effnet":
        if TensorflowPredictEffnetDiscogs is None:
            raise RuntimeError("TensorflowPredictEffnetDiscogs not available")
        emb_predictor = TensorflowPredictEffnetDiscogs(graphFilename=params.emb_graph, output=emb_output)
    elif params.backbone == "musicnn":
        if TensorflowPredictMusiCNN is None:
            raise RuntimeError("TensorflowPredictMusiCNN not available")
        emb_predictor = TensorflowPredictMusiCNN(graphFilename=params.emb_graph, output=emb_output)
    else:
        raise RuntimeError(f"Unsupported backbone {params.backbone}")

    # Single-pass backbone processing: feed entire audio clip once
    # Backbone models (YAMNet, EffNet) internally create patches with their own hop/stride
    wave_f32 = audio_result.waveform.astype(np.float32)
    emb = emb_predictor(wave_f32)
    emb = np.asarray(emb, dtype=np.float32)

    logging.info(
        f"[inference] {params.backbone} backbone output shape: {emb.shape} "
        f"(audio input: {len(wave_f32)} samples @ {audio_result.sample_rate}Hz = {len(wave_f32) / audio_result.sample_rate:.2f}s)"
    )

    # Normalize output to 2D (num_patches, embed_dim)
    embeddings_2d: np.ndarray
    if emb.ndim == 1:
        # Already pooled to 1D - expand to (1, embed_dim)
        logging.info("[inference] Backbone returned 1D embedding (already pooled)")
        embeddings_2d = emb.reshape(1, -1)
    elif emb.ndim == 2:
        # Native 2D patches - use directly
        logging.info(f"[inference] Backbone returned 2D patches: {emb.shape[0]} patches × {emb.shape[1]} dims")
        embeddings_2d = emb
    elif emb.ndim == 3:
        # 3D output (rare) - average first two dimensions
        logging.warning(f"[inference] Backbone returned 3D output: {emb.shape}, averaging first two dimensions")
        embeddings_2d = np.mean(emb, axis=(0, 1)).reshape(1, -1)
    else:
        # Unexpected - flatten to 1D then expand
        logging.warning(f"[inference] Unexpected backbone output shape: {emb.shape}, flattening to 1D")
        embeddings_2d = emb.reshape(1, -1)

    logging.info(
        f"[inference] Computed {embeddings_2d.shape[0]} patches for {params.backbone}: "
        f"shape={embeddings_2d.shape} duration={audio_result.duration:.1f}s"
    )

    return embeddings_2d, audio_result.duration


def make_head_only_predictor_batched(
    head_info: HeadInfo, embeddings_2d: np.ndarray, batch_size: int = 11
) -> Callable[[], np.ndarray]:
    """
    Create a batched predictor that processes segments in fixed-size batches.
    Returns a function that takes no args and returns predictions for all segments.

    This is MUCH faster than per-segment prediction:
    - Processes in batches of `batch_size` (default 11 = 60s clip)
    - GPU can parallelize across segments within each batch
    - Reduces Python/TensorFlow overhead
    - Fixed batch size helps TensorFlow optimize VRAM allocation

    Args:
        head_info: Head metadata and model paths
        embeddings_2d: Pre-computed embeddings [num_segments, embed_dim]
        batch_size: Fixed batch size for inference (default 11 segments = 60s)

    Returns: Callable that returns [num_segments, num_classes] array
    """
    # Require Essentia at function call time (not module import time)
    backend_essentia.require()

    from nomarr.components.ml.ml_discovery_comp import get_head_output_node

    head_graph = head_info.sidecar.graph_abs("")
    head_output = get_head_output_node(head_info.head_type, head_info.sidecar)
    head_input = head_info.sidecar.head_input_name()

    # Force head models to CPU to save VRAM (embeddings stay on GPU)
    # Head models are small and fast enough for CPU inference
    if HAVE_TF and tf is not None:
        device_context = tf.device("/CPU:0")
    else:
        device_context = contextlib.nullcontext()

    with device_context:
        if head_input:
            head_predictor = TensorflowPredict2D(graphFilename=head_graph, input=head_input, output=head_output)  # type: ignore[misc]
        else:
            head_predictor = TensorflowPredict2D(graphFilename=head_graph, output=head_output)  # type: ignore[misc]

    embed_dim = head_info.sidecar.input_dim()

    def predict_all_segments() -> np.ndarray:
        """Process all segments in fixed-size batches."""
        batch_emb = embeddings_2d  # Already shape [num_segments, embed_dim]

        # Handle dimension mismatch (truncate if embedding > expected)
        if embed_dim and batch_emb.shape[1] != embed_dim:
            if batch_emb.shape[1] > embed_dim:
                logging.warning(
                    f"[inference] ⚠️  DIMENSION TRUNCATION: {head_info.name} expects {embed_dim} dims "
                    f"but embeddings are {batch_emb.shape[1]} dims. Truncating batch."
                )
                batch_emb = batch_emb[:, :embed_dim]  # Truncate columns (dims)
            else:
                raise RuntimeError(
                    f"Embedding dimension mismatch for {head_info.name}: "
                    f"got {batch_emb.shape[1]}, expected {embed_dim} (cannot pad)"
                )

        num_segments = batch_emb.shape[0]

        # Process in fixed-size batches to control VRAM usage
        all_predictions = []
        for i in range(0, num_segments, batch_size):
            batch_slice = batch_emb[i : i + batch_size]  # [batch_size or less, embed_dim]

            # Run batched inference
            batch_preds = head_predictor(batch_slice)  # [batch_size, num_classes]
            batch_preds = np.asarray(batch_preds, dtype=np.float32)

            # Ensure 2D output
            if batch_preds.ndim == 1:
                batch_preds = batch_preds.reshape(-1, 1)

            all_predictions.append(batch_preds)

        # Concatenate all batch results
        predictions = np.vstack(all_predictions)  # [num_segments, num_classes]

        return predictions  # [num_segments, num_classes]

    return predict_all_segments
