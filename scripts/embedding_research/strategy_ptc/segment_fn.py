"""Thin segment-phase adapter for PTC temporal-binning strategies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from scripts.embedding_research.cache import binned_ptc
from scripts.embedding_research.helpers.binning import BIN_MODES, DIST_FNS, temporal_segment
from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS as STD_THRESHOLDS
from scripts.embedding_research.helpers.thresholds import DIRECT_L2 as _DIRECT_L2
from scripts.embedding_research.helpers.thresholds import STD_SCALED as _STD_SCALED
from scripts.embedding_research.helpers.thresholds import (
    ThresholdSemantics as _ThresholdSemantics,
)
from scripts.embedding_research.helpers.thresholds import (
    resolve_threshold as _resolve_threshold,
)
from scripts.embedding_research.helpers.thresholds import (
    validate_semantics as _validate_semantics,
)
from scripts.embedding_research.strategy_binned._pool import _pool_segment
from scripts.embedding_research.vector_types import RawTensor, UnitTensor

if TYPE_CHECKING:
    from collections.abc import Mapping

    from scripts.embedding_research.common.segment import SegmentFn

STRATEGY_NAMES: list[str] = [
    f"ptc_{bin_mode}_{std_thresh:.2f}" for bin_mode in BIN_MODES for std_thresh in STD_THRESHOLDS
]

_DONE_KEYS_CACHE: set[tuple[str, str, str, float]] | None = None


def _decode_strategy_name(strategy_name: str) -> tuple[str, float]:
    prefix = "ptc_"
    if not strategy_name.startswith(prefix):
        raise ValueError(f"Unsupported PTC strategy name: {strategy_name}")

    encoded = strategy_name[len(prefix) :]
    try:
        bin_mode, std_thresh_text = encoded.rsplit("_", 1)
    except ValueError as exc:
        raise ValueError(f"Malformed PTC strategy name: {strategy_name}") from exc

    if bin_mode not in BIN_MODES:
        raise ValueError(f"Unknown PTC bin mode in strategy name: {strategy_name}")

    std_thresh = float(std_thresh_text)
    return bin_mode, std_thresh


def _get_done_keys() -> set[tuple[str, str, str, float]]:
    global _DONE_KEYS_CACHE
    if _DONE_KEYS_CACHE is None:
        _DONE_KEYS_CACHE = binned_ptc.list_done_keys()
    return _DONE_KEYS_CACHE


def _skip_check(song_id: str, backbone: str, strategy_name: str) -> bool:
    bin_mode, std_thresh = _decode_strategy_name(strategy_name)
    return (song_id, backbone, bin_mode, std_thresh) in _get_done_keys()


SKIP_CHECK_FN = _skip_check


def _cache_write(song_id: str, backbone: str, strategy_name: str, result: dict[str, np.ndarray]) -> None:
    bin_mode, std_thresh = _decode_strategy_name(strategy_name)
    bins = np.asarray(result.get("bins", np.empty(0, dtype=np.int32)), dtype=np.int32)
    if bins.size == 0:
        return

    weights = np.asarray(result["weights"], dtype=np.int32)
    outlier_counts = np.asarray(result.get("outlier_counts", np.zeros_like(weights)), dtype=np.int32)
    bin_start_idx = np.asarray(result.get("bin_start_idx", np.full_like(weights, -1)), dtype=np.int32)
    bin_end_idx = np.asarray(result.get("bin_end_idx", np.full_like(weights, -1)), dtype=np.int32)
    pool_names = [str(name) for name in np.asarray(result.get("pool_names", np.empty(0, dtype=str))).tolist()]

    bulk_vecs: list[tuple] = []
    for row_idx, bin_id in enumerate(bins.tolist()):
        for pool_name in pool_names:
            vec_raw = np.asarray(result[f"pool_{pool_name}_vec_raw"][row_idx], dtype=np.float32)
            vec_norm = np.asarray(result[f"pool_{pool_name}_vec_norm"][row_idx], dtype=np.float32)
            selected_global_idx = int(
                np.asarray(result[f"pool_{pool_name}_selected_global_idx"], dtype=np.int32)[row_idx]
            )
            selected_local_idx = int(
                np.asarray(result[f"pool_{pool_name}_selected_local_idx"], dtype=np.int32)[row_idx]
            )
            medoid_centrality = float(
                np.asarray(result[f"pool_{pool_name}_medoid_centrality"], dtype=np.float32)[row_idx]
            )
            bulk_vecs.append(
                (
                    song_id,
                    backbone,
                    bin_mode,
                    std_thresh,
                    int(bin_id),
                    pool_name,
                    vec_raw.astype(np.float32, copy=False).tobytes(),
                    vec_norm.astype(np.float32, copy=False).tobytes(),
                    int(weights[row_idx]),
                    int(outlier_counts[row_idx]),
                    selected_global_idx,
                    selected_local_idx,
                    medoid_centrality,
                    int(bin_start_idx[row_idx]),
                    int(bin_end_idx[row_idx]),
                )
            )

    binned_ptc.save(backbone, bin_mode, std_thresh, song_id, bulk_vecs, bulk_heads=[])
    _get_done_keys().add((song_id, backbone, bin_mode, std_thresh))


CACHE_WRITE_FN = _cache_write


def make_segment_fn(
    con,
    *,
    semantics: _ThresholdSemantics = _DIRECT_L2,
    calibration_records: Mapping[str, Mapping[str, object]] | None = None,
) -> SegmentFn:
    """Build the PTC segmenting closure.

    The DEFAULT threshold semantics is ``direct_l2``: the configured threshold
    decoded from the strategy name is applied as a DIRECT unit-vector L2 distance
    (``effective == configured``) and no calibration source is consulted.  The
    explicit ``std_scaled`` legacy-fidelity track is available ONLY by requesting
    ``semantics="std_scaled"`` together with an explicit per-bin-mode calibration
    basis in ``calibration_records`` (a mapping keyed by bin mode whose values are
    explicit calibration records carrying the multiplier basis).  Without a usable
    explicit basis, ``std_scaled`` raises — the old silent ``x0.1`` fallback is
    gone.  ``con`` is retained for signature compatibility (``run.py`` and existing
    tests pass it); the resolved threshold never requires a DB connection under
    either track.  The running-centroid segmentation algorithm itself is
    preserved exactly.

    Returns
    -------
    SegmentFn
        Callable that decodes a PTC strategy name, resolves its effective
        segmentation threshold, temporally segments the patch matrix, pools each
        segment, and returns the segment metadata plus pooled vector arrays.
    """
    _validate_semantics(semantics)
    del con  # signature-compat seam only: threshold resolution needs no DB connection.
    calibration_records = dict(calibration_records) if calibration_records else {}

    def _resolve(bin_mode: str, configured: float) -> Any:
        if semantics == _STD_SCALED:
            basis = calibration_records.get(bin_mode)
            if basis is None:
                raise ValueError(
                    f"std_scaled PTC segmentation requires an explicit calibration basis for "
                    f"bin_mode={bin_mode!r}; no implicit p50/0.1 fallback is permitted"
                )
            return _resolve_threshold(configured, semantics=_STD_SCALED, calibration_record=basis)
        return _resolve_threshold(configured, semantics=_DIRECT_L2)

    def segment_fn(patches: np.ndarray, backbone: str, strategy_name: str) -> dict[str, np.ndarray]:
        del backbone  # SegmentFn contract: backbone arg required; resolution is backbone-independent.
        bin_mode, std_thresh = _decode_strategy_name(strategy_name)

        raw_patches = RawTensor(patches)
        norm_patches = UnitTensor(patches)
        resolution = _resolve(bin_mode, std_thresh)
        threshold = resolution.effective
        segments = temporal_segment(norm_patches.data, threshold, DIST_FNS[bin_mode])
        if not segments:
            return {
                "bins": np.empty(0, dtype=np.int32),
                "weights": np.empty(0, dtype=np.int32),
                "outlier_counts": np.empty(0, dtype=np.int32),
                "bin_start_idx": np.empty(0, dtype=np.int32),
                "bin_end_idx": np.empty(0, dtype=np.int32),
                "pool_names": np.empty(0, dtype=str),
            }

        pool_names: list[str] = []
        pooled_by_name: dict[str, dict[str, list[Any]]] = {}
        weights: list[int] = []
        outlier_counts: list[int] = []
        bin_start_idx: list[int] = []
        bin_end_idx: list[int] = []

        for seg in segments:
            indices = [int(idx) for idx in seg["indices"]]
            if not indices:
                continue

            pooled = _pool_segment(raw_patches, norm_patches, indices)
            if not pool_names:
                pool_names = list(pooled.keys())
                pooled_by_name = {
                    pool_name: {
                        "vec_raw": [],
                        "vec_norm": [],
                        "selected_global_idx": [],
                        "selected_local_idx": [],
                        "medoid_centrality": [],
                    }
                    for pool_name in pool_names
                }

            weights.append(len(indices))
            outlier_counts.append(int(seg.get("outlier_count", 0)))
            bin_start_idx.append(indices[0])
            bin_end_idx.append(indices[-1])

            for pool_name in pool_names:
                pdata = pooled[pool_name]
                pooled_by_name[pool_name]["vec_raw"].append(np.asarray(pdata["vec_raw"], dtype=np.float32))
                pooled_by_name[pool_name]["vec_norm"].append(np.asarray(pdata["vec_norm"], dtype=np.float32))
                pooled_by_name[pool_name]["selected_global_idx"].append(
                    -1 if pdata["selected_global_idx"] is None else int(pdata["selected_global_idx"])
                )
                pooled_by_name[pool_name]["selected_local_idx"].append(
                    -1 if pdata["selected_local_idx"] is None else int(pdata["selected_local_idx"])
                )
                pooled_by_name[pool_name]["medoid_centrality"].append(
                    np.nan if pdata["medoid_centrality"] is None else float(pdata["medoid_centrality"])
                )

        if not weights:
            return {
                "bins": np.empty(0, dtype=np.int32),
                "weights": np.empty(0, dtype=np.int32),
                "outlier_counts": np.empty(0, dtype=np.int32),
                "bin_start_idx": np.empty(0, dtype=np.int32),
                "bin_end_idx": np.empty(0, dtype=np.int32),
                "pool_names": np.empty(0, dtype=str),
            }

        result: dict[str, np.ndarray] = {
            "bins": np.arange(len(weights), dtype=np.int32),
            "weights": np.asarray(weights, dtype=np.int32),
            "outlier_counts": np.asarray(outlier_counts, dtype=np.int32),
            "bin_start_idx": np.asarray(bin_start_idx, dtype=np.int32),
            "bin_end_idx": np.asarray(bin_end_idx, dtype=np.int32),
            "pool_names": np.asarray(pool_names, dtype=str),
        }
        for pool_name in pool_names:
            result[f"pool_{pool_name}_vec_raw"] = np.stack(pooled_by_name[pool_name]["vec_raw"]).astype(np.float32)
            result[f"pool_{pool_name}_vec_norm"] = np.stack(pooled_by_name[pool_name]["vec_norm"]).astype(np.float32)
            result[f"pool_{pool_name}_selected_global_idx"] = np.asarray(
                pooled_by_name[pool_name]["selected_global_idx"],
                dtype=np.int32,
            )
            result[f"pool_{pool_name}_selected_local_idx"] = np.asarray(
                pooled_by_name[pool_name]["selected_local_idx"],
                dtype=np.int32,
            )
            result[f"pool_{pool_name}_medoid_centrality"] = np.asarray(
                pooled_by_name[pool_name]["medoid_centrality"],
                dtype=np.float32,
            )
        return result

    return segment_fn
