"""Backbone embedding computation with parallel/sequential dispatch.

Runs ONNX backbone inference across all backbones, parallelising when 2+
backbones are present (ONNX C++ kernels release the GIL).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from nomarr.components.ml import ml_worker_context_comp as _worker_ctx
from nomarr.components.ml.ml_vram_probe_comp import (
    parse_oom_requested_bytes,
    update_model_vram_from_oom,
)
from nomarr.helpers.time_helper import internal_ms

if TYPE_CHECKING:
    from nomarr.components.ml.ml_onnx_cache import ONNXModelCache
    from nomarr.components.ml.ml_onnx_head import ONNXHeadModel

logger = logging.getLogger(__name__)

_PARALLEL_THRESHOLD = 2  # Use ThreadPoolExecutor when at least this many backbones


@dataclass
class BackboneEmbedding:
    """Embeddings produced by one backbone model."""

    backbone: str
    heads: list[ONNXHeadModel]
    embeddings: np.ndarray


@dataclass
class BackboneEmbeddingResult:
    """Aggregated output from compute_backbone_embeddings."""

    embeddings: list[BackboneEmbedding] = field(default_factory=list)
    """Successfully computed embeddings, one entry per backbone."""

    errors: dict[str, str] = field(default_factory=dict)
    """Backbones that failed; value is the error message."""

    timings: dict[str, float] = field(default_factory=dict)
    """Timing entries: ``emb_wall`` (parallel only) and ``emb_<backbone>`` per backbone."""


def compute_backbone_embeddings(
    cache: ONNXModelCache,
    heads_by_backbone: dict[str, list[ONNXHeadModel]],
    waveform: np.ndarray,
) -> BackboneEmbeddingResult:
    """Compute embeddings for all backbones, parallelising when 2+ are present.

    Audio array is read-only numpy — safe to share across threads without copying.
    ONNX C++ kernels release the GIL, so ThreadPoolExecutor gives real parallelism.

    Args:
        cache: Warmed ONNXModelCache with loaded backbone sessions.
        heads_by_backbone: Mapping of backbone name to its head models.
        waveform: Mono float32 waveform array shared across all backbones.

    Returns:
        BackboneEmbeddingResult with embeddings, per-backbone errors, and timings.

    """
    wave_f32 = waveform.astype(np.float32)
    backbone_items = list(heads_by_backbone.items())
    result = BackboneEmbeddingResult()

    def _run_one(backbone: str, backbone_heads: list[ONNXHeadModel]) -> BackboneEmbedding:
        t0 = internal_ms()
        model = cache.backbones[backbone]
        try:
            embeddings_2d = model.run(wave_f32)
        except RuntimeError as _oom_e:
            requested = parse_oom_requested_bytes(_oom_e)
            if requested is None:
                raise  # not a BFC arena OOM — propagate unchanged
            ctx = _worker_ctx.get_worker_context()
            if ctx is None:
                raise  # probe / test context — no DB, cannot self-heal
            db, _ = ctx
            update_model_vram_from_oom(db, model._path, requested)
            # Re-assigning device re-reads the updated limit from DB.
            # If it still doesn't fit, VramFitError in the setter silently
            # falls back to CPU, and the retry run() below succeeds on CPU.
            model.device = "gpu"
            embeddings_2d = model.run(wave_f32)  # single retry
        result.timings[f"emb_{backbone}"] = internal_ms().value - t0.value
        return BackboneEmbedding(backbone=backbone, heads=backbone_heads, embeddings=embeddings_2d)

    if len(backbone_items) >= _PARALLEL_THRESHOLD:
        t_wall = internal_ms()
        logger.debug(
            "[embeddings] Computing %d backbones in parallel (ThreadPoolExecutor)",
            len(backbone_items),
        )
        with ThreadPoolExecutor(max_workers=len(backbone_items), thread_name_prefix="backbone") as pool:
            future_to_backbone = {pool.submit(_run_one, bb, heads): bb for bb, heads in backbone_items}
            for future in as_completed(future_to_backbone):
                bb = future_to_backbone[future]
                try:
                    result.embeddings.append(future.result())
                except RuntimeError as e:
                    logger.warning("[embeddings] Skipping backbone %s: %s", bb, e)
                    result.errors[bb] = str(e)
        wall_ms = internal_ms().value - t_wall.value
        sequential_ms = sum(v for k, v in result.timings.items() if k.startswith("emb_"))
        result.timings["emb_wall"] = wall_ms
        logger.debug(
            "[embeddings] Parallel done: wall=%dms, sum=%dms, speedup=%.2fx",
            wall_ms,
            sequential_ms,
            sequential_ms / max(wall_ms, 1),
        )
    else:
        for backbone, backbone_heads in backbone_items:
            try:
                result.embeddings.append(_run_one(backbone, backbone_heads))
            except RuntimeError as e:
                logger.warning("[embeddings] Skipping backbone %s: %s", backbone, e)
                result.errors[backbone] = str(e)

    return result
