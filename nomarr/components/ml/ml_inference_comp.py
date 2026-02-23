"""ONNX model inference operations.

Handles embedding computation, head prediction, and batched processing using
ONNX Runtime. Mel spectrogram preprocessing and patch extraction are performed
externally via ml_preprocess_comp before each session call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import numpy as np

from nomarr.components.ml import ml_backend_onnx_comp as backend_onnx
from nomarr.components.ml.ml_discovery_comp import get_embedding_output_node
from nomarr.components.ml.ml_preprocess_comp import preprocess_for_backbone

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nomarr.components.ml.ml_cache_comp import DevicePlacement
    from nomarr.components.ml.ml_discovery_comp import HeadInfo
    from nomarr.helpers.dto.ml_dto import ComputeEmbeddingsForBackboneParams


def _create_backbone_predictor(
    backbone: str,
    emb_graph: str,
    device_placement: DevicePlacement = "gpu",
) -> Callable[[np.ndarray], np.ndarray]:
    """Construct an ONNX backbone embedding predictor.

    Creates an ONNX Runtime session and wraps it together with the
    backbone-specific mel spectrogram preprocessing into a single callable.
    This is the expensive operation (session creation) that should be done
    once and cached.

    The returned callable accepts a mono float32 waveform at 16 kHz and
    returns embeddings of shape ``(n_patches, embed_dim)``.

    Args:
        backbone: Backbone name (yamnet, vggish, effnet, musicnn)
        emb_graph: Absolute path to the .onnx embedding model file
        device_placement: Device for inference (``"cpu"`` or ``"gpu"``)
    """
    backend_onnx.require()

    session = backend_onnx.create_session(emb_graph, device=device_placement)
    input_name: str = session.get_inputs()[0].name
    output_name: str = get_embedding_output_node(backbone)

    logger.debug(
        "[inference] Created ONNX backbone session for %s "
        "(input=%s output=%s device=%s)",
        backbone,
        input_name,
        output_name,
        device_placement,
    )

    def predict(waveform: np.ndarray) -> np.ndarray:
        patches = preprocess_for_backbone(waveform, backbone)
        if patches.shape[0] == 0:
            msg = f"[inference] No patches produced for backbone {backbone} — audio too short"
            raise RuntimeError(msg)
        result = session.run([output_name], {input_name: patches})
        return np.asarray(result[0], dtype=np.float32)

    return predict


def compute_embeddings_for_backbone(
    params: ComputeEmbeddingsForBackboneParams,
) -> tuple[np.ndarray, float, str]:
    """Compute embeddings for an audio file using a specific backbone.

    Uses cached backbone predictors when available to avoid repeated model loading.
    The ONNX backbone models process the entire audio clip as overlapping patches
    (via ml_preprocess_comp), preserving temporal resolution.

    When pre_loaded_audio and pre_computed_chromaprint are provided on params,
    audio loading and chromaprint computation are skipped (caller already did them).

    Args:
        params: Parameters including backbone, emb_graph, target_sr, segment_s, hop_s,
                path, min_duration_s, allow_short

    Returns: (embeddings_2d, duration, chromaprint) where embeddings_2d is (num_patches, embed_dim),
              num_patches depends on the backbone's patch stride (not our segment_s/hop_s),
              duration is in seconds, and chromaprint is the audio fingerprint hash
    """
    backend_onnx.require()
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
        "[inference] Processing full track: %.1fs (%d samples @ %dHz)",
        audio_result.duration,
        len(audio_result.waveform),
        audio_result.sample_rate,
    )

    # Device-aware cache: check if cached predictor is on the desired device
    desired_device: DevicePlacement = "gpu" if params.prefer_gpu else "cpu"
    if not params.prefer_gpu:
        logger.info(
            "[inference] CPU spill requested for %s (GPU VRAM pressure detected)",
            params.backbone,
        )
    cached_device = get_cached_backbone_device(params.backbone, params.emb_graph)
    if cached_device is not None and cached_device != desired_device:
        logger.info(
            "[inference] Device transition for %s: %s → %s",
            params.backbone,
            cached_device,
            desired_device,
        )
        evict_backbone_predictor(params.backbone, params.emb_graph)
        emb_predictor = _create_backbone_predictor(
            params.backbone, params.emb_graph, device_placement=desired_device
        )
        cache_backbone_predictor(
            params.backbone, params.emb_graph, emb_predictor, device=desired_device
        )
    elif cached_device is not None:
        emb_predictor = cast(
            "Callable[[np.ndarray], np.ndarray]",
            get_cached_backbone_predictor(params.backbone, params.emb_graph),
        )
        logger.debug(
            "[inference] Using cached %s backbone predictor (device=%s)",
            params.backbone,
            cached_device,
        )
    else:
        logger.info(
            "[inference] Creating %s backbone predictor (device=%s, not cached)",
            params.backbone,
            desired_device,
        )
        emb_predictor = _create_backbone_predictor(
            params.backbone, params.emb_graph, device_placement=desired_device
        )
        cache_backbone_predictor(
            params.backbone, params.emb_graph, emb_predictor, device=desired_device
        )

    wave_f32 = audio_result.waveform.astype(np.float32)
    emb = emb_predictor(wave_f32)
    emb = np.asarray(emb, dtype=np.float32)

    logger.debug(
        "[inference] %s backbone output shape: %s "
        "(audio input: %d samples @ %dHz = %.2fs)",
        params.backbone,
        emb.shape,
        len(wave_f32),
        audio_result.sample_rate,
        len(wave_f32) / audio_result.sample_rate,
    )

    embeddings_2d: np.ndarray
    if emb.ndim == 1:
        logger.debug("[inference] Backbone returned 1D embedding (already pooled)")
        embeddings_2d = emb.reshape(1, -1)
    elif emb.ndim == 2:
        logger.debug(
            "[inference] Backbone returned 2D patches: %d patches x %d dims",
            emb.shape[0],
            emb.shape[1],
        )
        embeddings_2d = emb
    elif emb.ndim == 3:
        logger.warning(
            "[inference] Backbone returned 3D output: %s, averaging first two dimensions",
            emb.shape,
        )
        embeddings_2d = np.mean(emb, axis=(0, 1)).reshape(1, -1)
    else:
        logger.warning(
            "[inference] Unexpected backbone output shape: %s, flattening to 1D", emb.shape
        )
        embeddings_2d = emb.reshape(1, -1)

    logger.debug(
        "[inference] Computed %d patches for %s: shape=%s duration=%.1fs",
        embeddings_2d.shape[0],
        params.backbone,
        embeddings_2d.shape,
        audio_result.duration,
    )
    return (embeddings_2d, audio_result.duration, chromaprint)


def _create_head_only_predictor(
    head_info: HeadInfo,
    device_placement: DevicePlacement = "cpu",
) -> Callable[[np.ndarray], np.ndarray]:
    """Construct an ONNX head predictor.

    Creates an ONNX Runtime session for a head model and wraps it into a
    callable that accepts ``[batch_size, embed_dim]`` embeddings and returns
    ``[batch_size, num_classes]`` predictions.

    This is the expensive operation (session creation) that should be done
    once and cached.

    Args:
        head_info: Head metadata and model paths
        device_placement: Device for inference (``"cpu"`` or ``"gpu"``)
    """
    backend_onnx.require()

    head_graph = head_info.sidecar.graph_abs("")
    if head_graph is None:
        msg = f"No graph file found for head {head_info.name}"
        raise FileNotFoundError(msg)

    session = backend_onnx.create_session(head_graph, device=device_placement)
    input_name: str = session.get_inputs()[0].name
    output_name: str = session.get_outputs()[0].name

    logger.debug(
        "[inference] Created ONNX head session for %s (%s/%s) "
        "input=%s output=%s device=%s",
        head_info.name,
        head_info.backbone,
        head_info.head_type,
        input_name,
        output_name,
        device_placement,
    )

    def predict(embeddings: np.ndarray) -> np.ndarray:
        result = session.run([output_name], {input_name: embeddings.astype(np.float32)})
        return np.asarray(result[0], dtype=np.float32)

    return predict


def make_head_only_predictor_batched(
    head_info: HeadInfo,
    embeddings_2d: np.ndarray,
    batch_size: int = 11,
    device_placement: DevicePlacement = "cpu",
) -> Callable[[], np.ndarray]:
    """Create a batched predictor that processes segments in fixed-size batches.
    Returns a function that takes no args and returns predictions for all segments.

    Uses cached head-only predictor when available (populated at warmup or on first
    use). ONNX session construction is expensive (model load + provider setup),
    but once cached, reuse is essentially free.

    Supports device transitions: if cached on a different device than requested,
    evicts and recreates on the desired device.

    Args:
        head_info: Head metadata and model paths
        embeddings_2d: Pre-computed embeddings [num_segments, embed_dim]
        batch_size: Fixed batch size for inference (default 11 segments = 60s)
        device_placement: Device for inference (``"cpu"`` or ``"gpu"``)

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
        logger.info(
            "[inference] Device transition for head %s: %s → %s",
            head_info.name,
            cached_device,
            device_placement,
        )
        evict_head_predictor(head_info)
        head_predictor = _create_head_only_predictor(
            head_info, device_placement=device_placement
        )
        cache_head_predictor(head_info, head_predictor, device=device_placement)
    elif cached_device is not None:
        head_predictor = cast(
            "Callable[[np.ndarray], np.ndarray]",
            get_cached_head_predictor(head_info),
        )
        logger.debug(
            "[inference] Using cached head predictor for %s (device=%s)",
            head_info.name,
            cached_device,
        )
    else:
        head_predictor = _create_head_only_predictor(
            head_info, device_placement=device_placement
        )
        cache_head_predictor(head_info, head_predictor, device=device_placement)

    embed_dim = head_info.sidecar.input_dim()

    def predict_all_segments() -> np.ndarray:
        """Process all segments in fixed-size batches."""
        batch_emb = embeddings_2d
        if embed_dim and batch_emb.shape[1] != embed_dim:
            if batch_emb.shape[1] > embed_dim:
                logger.warning(
                    "[inference] ⚠️  DIMENSION TRUNCATION: %s expects %d dims "
                    "but embeddings are %d dims. Truncating batch.",
                    head_info.name,
                    embed_dim,
                    batch_emb.shape[1],
                )
                batch_emb = batch_emb[:, :embed_dim]
            else:
                msg = (
                    f"Embedding dimension mismatch for {head_info.name}: "
                    f"got {batch_emb.shape[1]}, expected {embed_dim} (cannot pad)"
                )
                raise RuntimeError(msg)

        num_segments = batch_emb.shape[0]
        all_predictions: list[np.ndarray] = []
        for i in range(0, num_segments, batch_size):
            batch_slice = batch_emb[i : i + batch_size]
            batch_preds = head_predictor(batch_slice)
            batch_preds = np.asarray(batch_preds, dtype=np.float32)
            if batch_preds.ndim == 1:
                batch_preds = batch_preds.reshape(-1, 1)
            all_predictions.append(batch_preds)
        return np.vstack(all_predictions)

    return predict_all_segments
