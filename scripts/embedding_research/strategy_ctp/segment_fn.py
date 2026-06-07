"""Thin segment-phase adapter for CTP score-stream temporal-binning strategies."""

from __future__ import annotations

from typing import Any

import numpy as np

from scripts.embedding_research.cache import binned_ctp
from scripts.embedding_research.common.segment import SegmentFn
from scripts.embedding_research.config import HEAD_LABELS, HEADS
from scripts.embedding_research.helpers.binning import global_dist, temporal_segment
from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS as STD_THRESHOLDS
from scripts.embedding_research.strategy_binned._constants import _BIN_POOL_STRATEGIES, REP_TYPES

_KNOWN_HEAD_NAMES: list[str] = sorted({head for head_map in HEADS.values() for head in head_map} or HEAD_LABELS.keys())

STRATEGY_NAMES: list[str] = [
    f"ctp_{head_name}_{std_thresh:.2f}"
    for head_name in _KNOWN_HEAD_NAMES
    for std_thresh in STD_THRESHOLDS
]


def make_strategy_names(head_names) -> list[str]:
    """Return CTP strategy names for the given head names only."""
    return [
        f"ctp_{head_name}_{std_thresh:.2f}"
        for head_name in sorted(head_names)
        for std_thresh in STD_THRESHOLDS
    ]


def _decode_strategy_name(strategy_name: str) -> tuple[str, float]:
    prefix = "ctp_"
    if not strategy_name.startswith(prefix):
        raise ValueError(f"Unsupported CTP strategy name: {strategy_name}")

    encoded = strategy_name[len(prefix) :]
    try:
        head_name, std_thresh_text = encoded.rsplit("_", 1)
    except ValueError as exc:
        raise ValueError(f"Malformed CTP strategy name: {strategy_name}") from exc

    return head_name, float(std_thresh_text)


def _l2_normalise_vec(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    return (v / norm).astype(np.float32) if norm > 1e-9 else v.astype(np.float32)


def _run_head_session(session: object, embed_batch: np.ndarray) -> np.ndarray:
    inp = embed_batch if embed_batch.ndim == 2 else embed_batch[None, :]
    out = session.run(["activations"], {"embeddings": inp.astype(np.float32)})[0]
    return np.asarray(out, dtype=np.float32)


def _empty_result() -> dict[str, np.ndarray]:
    return {
        "bins": np.empty(0, dtype=np.int32),
        "weights": np.empty(0, dtype=np.int32),
        "outlier_counts": np.empty(0, dtype=np.int32),
        "bin_start_idx": np.empty(0, dtype=np.int32),
        "bin_end_idx": np.empty(0, dtype=np.int32),
        "pool_names": np.empty(0, dtype=str),
    }


def _cache_write(song_id: str, backbone: str, strategy_name: str, result: dict[str, np.ndarray]) -> None:
    head_name, std_thresh = _decode_strategy_name(strategy_name)
    bins = np.asarray(result.get("bins", np.empty(0, dtype=np.int32)), dtype=np.int32)
    if bins.size == 0:
        return

    weights = np.asarray(result["weights"], dtype=np.int32)
    outlier_counts = np.asarray(result.get("outlier_counts", np.zeros_like(weights)), dtype=np.int32)
    bin_start_idx = np.asarray(result.get("bin_start_idx", np.full_like(weights, -1)), dtype=np.int32)
    bin_end_idx = np.asarray(result.get("bin_end_idx", np.full_like(weights, -1)), dtype=np.int32)
    pool_names = [str(name) for name in np.asarray(result.get("pool_names", np.empty(0, dtype=str))).tolist()]

    bulk_vecs: list[tuple[Any, ...]] = []
    for row_idx, bin_id in enumerate(bins.tolist()):
        for pool_name in pool_names:
            vec_raw = np.asarray(result[f"pool_{pool_name}_vec_raw"][row_idx], dtype=np.float32)
            vec_norm = np.asarray(result[f"pool_{pool_name}_vec_norm"][row_idx], dtype=np.float32)
            bulk_vecs.append(
                (
                    song_id,
                    backbone,
                    head_name,
                    std_thresh,
                    int(bin_id),
                    pool_name,
                    vec_raw.astype(np.float32, copy=False).tobytes(),
                    vec_norm.astype(np.float32, copy=False).tobytes(),
                    int(weights[row_idx]),
                    int(outlier_counts[row_idx]),
                    -1,
                    -1,
                    np.nan,
                    int(bin_start_idx[row_idx]),
                    int(bin_end_idx[row_idx]),
                )
            )

    binned_ctp.save(backbone, head_name, std_thresh, song_id, bulk_vecs)


CACHE_WRITE_FN = _cache_write

_DONE_KEYS_CACHE: set[tuple[str, str, str, float]] | None = None


def _get_done_keys() -> set[tuple[str, str, str, float]]:
    global _DONE_KEYS_CACHE
    if _DONE_KEYS_CACHE is None:
        _DONE_KEYS_CACHE = binned_ctp.list_done_keys()
    return _DONE_KEYS_CACHE


def _skip_check(song_id: str, backbone: str, strategy_name: str) -> bool:
    head_name, std_thresh = _decode_strategy_name(strategy_name)
    return (song_id, backbone, head_name, std_thresh) in _get_done_keys()


SKIP_CHECK_FN = _skip_check


def _segment_score_stream(scores: np.ndarray, threshold: float) -> list[dict]:
    """Segment a 1-D score stream.
    
    The scores are reshaped to (-1, 1) for temporal_segment, which requires
    2-D input.  For a 1-D signal the distance function choice (global vs
    per-dimension) is irrelevant — both reduce to absolute difference.
    """
    return temporal_segment(scores.reshape(-1, 1).astype(np.float32), threshold, global_dist)


def make_segment_fn(head_sessions: dict[str, object], run_in_batches_fn) -> SegmentFn:
    """Build the CTP segmenting closure for a set of classifier head sessions.

    Parameters
    ----------
    head_sessions
        Mapping of head names to ONNX inference sessions used to score patch
        embeddings.
    run_in_batches_fn
        Callable that runs a batch-processing function over the patch matrix and
        concatenates the resulting activations.

    Returns
    -------
    SegmentFn
        Callable that decodes a CTP strategy name, runs the selected head to
        obtain a score stream, segments patches from the score variance, pools
        each segment with the configured global strategies, and returns segment
        metadata plus pooled vector arrays.
    """

    def segment_fn(patches: np.ndarray, backbone: str, strategy_name: str) -> dict[str, np.ndarray]:
        del backbone
        if patches.size == 0:
            return _empty_result()

        head_name, std_thresh = _decode_strategy_name(strategy_name)
        head_session = head_sessions.get(head_name)
        if head_session is None:
            raise KeyError(f"Missing CTP head session for {head_name!r}")

        acts = np.asarray(
            run_in_batches_fn(
                lambda batch: _run_head_session(head_session, batch),
                patches,
            ),
            dtype=np.float32,
        )
        if acts.size == 0:
            return _empty_result()
        if acts.ndim != 2 or acts.shape[1] < 2:
            raise ValueError(
                f"CTP head {head_name!r} returned activations with invalid shape {acts.shape}; expected [n_patches, n_classes]"
            )

        scores = acts[:, 1]
        score_std = float(scores.std())
        if score_std < 1e-9:
            score_std = 1.0

        threshold = float(std_thresh) * score_std
        segments = _segment_score_stream(scores, threshold)
        if not segments:
            return _empty_result()

        rep_set = set(REP_TYPES)
        pool_names = [name for name in _BIN_POOL_STRATEGIES if name in rep_set]
        pooled_by_name: dict[str, list[np.ndarray]] = {pool_name: [] for pool_name in pool_names}
        pooled_norm_by_name: dict[str, list[np.ndarray]] = {pool_name: [] for pool_name in pool_names}
        weights: list[int] = []
        outlier_counts: list[int] = []
        bin_start_idx: list[int] = []
        bin_end_idx: list[int] = []

        for seg in segments:
            indices = [int(idx) for idx in seg["indices"]]
            if not indices:
                continue

            seg_patches = patches[indices].astype(np.float32, copy=False)
            weights.append(len(indices))
            outlier_counts.append(int(seg.get("outlier_count", 0)))
            bin_start_idx.append(indices[0])
            bin_end_idx.append(indices[-1])

            for pool_name in pool_names:
                pool_fn = _BIN_POOL_STRATEGIES[pool_name]
                pooled_raw = np.asarray(pool_fn(seg_patches), dtype=np.float32)
                pooled_by_name[pool_name].append(pooled_raw)
                pooled_norm_by_name[pool_name].append(_l2_normalise_vec(pooled_raw))

        if not weights:
            return _empty_result()

        result: dict[str, np.ndarray] = {
            "bins": np.arange(len(weights), dtype=np.int32),
            "weights": np.asarray(weights, dtype=np.int32),
            "outlier_counts": np.asarray(outlier_counts, dtype=np.int32),
            "bin_start_idx": np.asarray(bin_start_idx, dtype=np.int32),
            "bin_end_idx": np.asarray(bin_end_idx, dtype=np.int32),
            "pool_names": np.asarray(pool_names, dtype=str),
        }
        for pool_name in pool_names:
            result[f"pool_{pool_name}_vec_raw"] = np.stack(pooled_by_name[pool_name]).astype(np.float32)
            result[f"pool_{pool_name}_vec_norm"] = np.stack(pooled_norm_by_name[pool_name]).astype(np.float32)
        return result

    return segment_fn
