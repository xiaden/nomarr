"""Head pipeline component: parallel head inference for ONNX classification heads.

Owns the reusable thread pool for parallel head predictions and exposes:
- ``run_single_head``   — process one head prediction (thread-safe).
- ``run_backbone_heads`` — dispatch all heads for a backbone in parallel.
- ``shutdown_head_pool`` — orderly pool teardown (call on worker exit).

Kept separate from the workflow layer so the pool lifecycle and inference
dispatch logic can be tested and reasoned about independently of orchestration.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.components.ml.ml_embed_comp import pool_scores
from nomarr.components.ml.ml_heads_comp import HeadSpec, run_head_decision
from nomarr.components.tagging.mood_labels_comp import normalize_tag_label
from nomarr.helpers.dto.ml_dto import ProcessHeadPredictionsResult, SingleHeadResult
from nomarr.helpers.time_helper import internal_ms

if TYPE_CHECKING:
    from nomarr.components.ml.ml_onnx_head import ONNXHeadModel

logger = logging.getLogger(__name__)

# Reusable thread pool for parallel head predictions.
# Capped at 12 workers (max heads per backbone group). Lives for the process
# lifetime — avoids repeated pool creation/teardown overhead per file.
_HEAD_POOL = ThreadPoolExecutor(max_workers=12, thread_name_prefix="head")


def shutdown_head_pool(*, timeout: float = 5.0) -> None:
    """Shut down the module-level head prediction thread pool.

    Safe to call multiple times or when the pool has already exited.
    Called by the worker during cleanup to ensure a bounded exit time.

    Args:
        timeout: Max seconds to wait for in-flight predictions before
                 forcing cancellation. Defaults to 5s — enough for any
                 single head prediction to finish.
    """
    _HEAD_POOL.shutdown(wait=True, cancel_futures=True)


def _build_tag_key(label: str, *, head_model: ONNXHeadModel) -> str:
    """Build a versioned tag key for a label — module-level to avoid per-head closure creation."""
    model_key, _ = head_model.build_versioned_tag_key(
        normalize_tag_label(label),
        calib_method="none",
        calib_version=0,
    )
    return model_key


def _make_predict(m: ONNXHeadModel, e: np.ndarray) -> Callable[[], np.ndarray]:
    """Pre-resolve a predictor closure binding an ONNX session + embedding matrix.

    Hoisting resolution to the caller avoids per-thread cache lookup + lock
    contention inside the ThreadPoolExecutor workers.
    """

    def _fn() -> np.ndarray:
        return m.run(e)

    return _fn


def run_single_head(
    head_model: ONNXHeadModel,
    predict_fn: Callable[[], np.ndarray],
) -> SingleHeadResult:
    """Process a single head prediction — fully independent, no shared state mutation.

    Thread-safe: all inputs are read-only, all outputs returned via SingleHeadResult.
    ONNX inference releases the GIL so multiple heads get real parallelism.

    Args:
        head_model: ONNX head model wrapper (provides labels, sidecar, name, etc.).
        predict_fn: Pre-resolved cached predictor closure that calls head_model.run().
            Hoisting resolution to the caller avoids per-thread cache lookup + lock contention.

    """
    head_name = head_model.name
    t_head = internal_ms()
    # Phase 1: ONNX inference (GPU/CPU, releases GIL)
    try:
        segment_scores = predict_fn()
        pooled_vec = pool_scores(segment_scores, mode="trimmed_mean", trim_perc=0.1, nan_policy="omit")
        seg_std: np.ndarray | None = None
        if segment_scores.ndim == 2 and segment_scores.shape[0] > 1:
            seg_std = np.std(segment_scores, axis=0).astype(np.float32, copy=False)
    except Exception as e:
        logger.error(f"[processor] Processing error for {head_name}: {e}", exc_info=True)
        return SingleHeadResult(
            head_name=head_name,
            status="error_processing",
            error=str(e),
            elapsed_ms=internal_ms().value - t_head.value,
        )
    # Phase 2: Decision + tag generation (pure Python/numpy)
    try:
        spec = HeadSpec(
            name=head_model.name,
            kind=head_model.head_type,
            labels=head_model.labels,
        )
        decision = run_head_decision(spec, pooled_vec, prefix="", segment_std=seg_std)

        key_builder = partial(_build_tag_key, head_model=head_model)

        head_outputs = decision.to_head_outputs(
            head_info=head_model,
            key_builder=key_builder,
        )
        head_tags = decision.as_tags(key_builder=key_builder)
        logger.debug(f"[processor] Head {head_name} ({head_model.head_type}) produced {len(head_tags)} tags")
        if head_tags:
            sample_keys = list(head_tags.keys())[:3]
            logger.debug(f"[processor]   Sample keys: {sample_keys}")
        elapsed_ms = internal_ms().value - t_head.value
        logger.debug(
            f"[processor] Head {head_name} complete: {len(segment_scores)} patches \u2192 {len(head_tags)} tags in {elapsed_ms / 1000:.1f}s",
        )
        if len(head_tags) == 0:
            logger.warning(f"[processor] Head {head_name} produced ZERO tags")
        # Regression data
        regression_data: tuple[Any, list[float]] | None = None
        if head_model.is_regression:
            if segment_scores.ndim == 2:
                raw_values = [float(x) for x in segment_scores[:, 0]]
            else:
                raw_values = [float(x) for x in segment_scores]
            regression_data = (head_model, raw_values)
            logger.debug(
                f"[processor] Captured {len(raw_values)} segment predictions for {head_name} (mean={np.mean(raw_values):.3f}, std={np.std(raw_values):.3f})",
            )
        # Defer segment stats computation to async DB write thread.
        # Keep raw scores alive (numpy ref, no copy needed — it's from vstack).
        raw_segment_scores: np.ndarray | None = None
        segment_labels: list[str] | None = None
        if segment_scores.ndim == 2 and len(head_model.labels) > 0:
            raw_segment_scores = segment_scores
            segment_labels = head_model.labels
        return SingleHeadResult(
            head_name=head_name,
            status="success",
            head_tags=head_tags,
            head_outputs=head_outputs,
            regression_data=regression_data,
            raw_segment_scores=raw_segment_scores,
            segment_labels=segment_labels,
            elapsed_ms=elapsed_ms,
            decisions_count=len(decision.details),
        )
    except Exception as e:
        logger.error(f"[processor] Aggregation error for {head_name}: {e}", exc_info=True)
        return SingleHeadResult(
            head_name=head_name,
            status="error_aggregation",
            error=str(e),
            elapsed_ms=internal_ms().value - t_head.value,
        )


def run_heads(
    backbone_heads: list[ONNXHeadModel],
    embeddings_2d: np.ndarray,
    tags_accum: dict[str, Any],
) -> ProcessHeadPredictionsResult:
    """Process all head predictions for a single backbone using cached embeddings.

    Runs heads in parallel via a reusable module-level ThreadPoolExecutor (_HEAD_POOL).
    Predictor resolution is hoisted to the main thread to avoid per-thread cache
    lookup + lock contention. The dispatched threads only call predict_fn() which
    releases the GIL for real CPU parallelism.

    Args:
        backbone_heads: List of heads for this backbone.
        embeddings_2d: Pre-computed embeddings.
        tags_accum: Accumulator dict for tags (modified in place).

    Returns:
        ProcessHeadPredictionsResult with per-head outcomes.

    """
    # Pre-resolve cached predictors on the main thread (no lock contention).
    # Each predict_fn is a lightweight closure binding the ONNX session + embeddings.
    predict_fns: dict[str, Callable[[], np.ndarray]] = {
        hm.name: _make_predict(hm, embeddings_2d) for hm in backbone_heads
    }

    head_results_list: list[SingleHeadResult] = []
    n_heads = len(backbone_heads)
    if n_heads > 1:
        futures = {_HEAD_POOL.submit(run_single_head, hm, predict_fns[hm.name]): hm.name for hm in backbone_heads}
        head_results_list.extend(fut.result() for fut in as_completed(futures))
        logger.debug("[processor] Parallel heads complete (%d heads)", n_heads)
    else:
        head_results_list.extend(run_single_head(hm, predict_fns[hm.name]) for hm in backbone_heads)

    # Merge results sequentially (safe dict mutations)
    heads_succeeded = 0
    head_results: dict[str, Any] = {}
    regression_heads: list[tuple[Any, list[float]]] = []
    all_head_outputs: list[Any] = []
    raw_segments_per_head: dict[str, tuple[np.ndarray, list[str]]] = {}
    per_head_timings: dict[str, float] = {}
    for r in head_results_list:
        per_head_timings[r.head_name] = r.elapsed_ms
        if r.status == "success":
            heads_succeeded += 1
            if r.head_tags:
                tags_accum.update(r.head_tags)
            if r.head_outputs:
                all_head_outputs.extend(r.head_outputs)
            if r.regression_data:
                regression_heads.append(r.regression_data)
            if r.raw_segment_scores is not None and r.segment_labels is not None:
                raw_segments_per_head[r.head_name] = (r.raw_segment_scores, r.segment_labels)
            head_results[r.head_name] = {
                "status": "success",
                "tags_written": len(r.head_tags or {}),
                "decisions": r.decisions_count,
            }
        elif r.status == "error_processing":
            head_results[r.head_name] = {"status": "error", "error": r.error, "stage": "processing"}
        else:
            head_results[r.head_name] = {"status": "error", "error": r.error, "stage": "aggregation"}
    return ProcessHeadPredictionsResult(
        heads_succeeded=heads_succeeded,
        head_results=head_results,
        regression_heads=regression_heads,
        all_head_outputs=all_head_outputs,
        raw_segments_per_head=raw_segments_per_head,
        per_head_timings=per_head_timings,
    )
