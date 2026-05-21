"""Temporal-binning algorithms and config constants shared by strategy_binned and classify.

Moving these here eliminates the awkward dependency where ``classify.py`` had to
import pure algorithms from the ``strategy_binned`` strategy-implementation module.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .toml import load_research_config

_cfg = load_research_config()

# ── Config-derived constants ──────────────────────────────────────────────────

STD_THRESHOLDS: list[float] = _cfg.get("binning", {}).get(
    "std_thresholds", [round(i * 0.1, 1) for i in range(1, 21)]
)
BIN_MODES: list[str] = _cfg.get("binning", {}).get(
    "bin_modes", ["temporal_global", "temporal_perdim"]
)
OUTLIER_WINDOW: int = 3


# ── Distance functions ────────────────────────────────────────────────────────


def global_dist(patch: np.ndarray, centroid: np.ndarray) -> float:
    """L2 distance between a patch and the current segment centroid."""
    return float(np.linalg.norm(patch - centroid))


def perdim_dist(patch: np.ndarray, centroid: np.ndarray) -> float:
    """Per-dimension (Chebyshev) distance between a patch and the centroid."""
    return float(np.max(np.abs(patch - centroid)))


DIST_FNS: dict[str, Callable[[np.ndarray, np.ndarray], float]] = {
    "temporal_global": global_dist,
    "temporal_perdim": perdim_dist,
}


# ── Segmentation algorithm ────────────────────────────────────────────────────


def temporal_segment(
    norm_patches: np.ndarray,
    threshold: float,
    dist_fn: Callable[[np.ndarray, np.ndarray], float],
    outlier_window: int = OUTLIER_WINDOW,
) -> list[dict]:
    """Segment a sequence of L2-normalised patch vectors into coherent bins.

    Returns a list of ``{"indices": [...], "outlier_count": int}`` dicts, one
    per segment.  Patches that stray beyond *threshold* from the running
    centroid are treated as outliers; if a patch within *outlier_window* steps
    returns below the threshold the outliers are absorbed into the current
    segment, otherwise a new segment starts.
    """
    n = len(norm_patches)
    if n == 0:
        return []

    segments: list[dict] = []
    total_outliers = 0
    seg_indices: list[int] = [0]
    centroid_sum: np.ndarray = norm_patches[0].copy()
    centroid_count = 1
    centroid = centroid_sum

    i = 1
    while i < n:
        d = dist_fn(norm_patches[i], centroid)
        if d <= threshold:
            seg_indices.append(i)
            centroid_sum = centroid_sum + norm_patches[i]
            centroid_count += 1
            centroid = centroid_sum / centroid_count
            i += 1
            continue

        run: list[int] = [i]
        j = i + 1
        returned = False
        while j < n and len(run) <= outlier_window:
            d_j = dist_fn(norm_patches[j], centroid)
            if d_j <= threshold:
                total_outliers += len(run)
                seg_indices.append(j)
                centroid_sum = centroid_sum + norm_patches[j]
                centroid_count += 1
                centroid = centroid_sum / centroid_count
                i = j + 1
                returned = True
                break
            run.append(j)
            j += 1

        if not returned:
            segments.append({"indices": seg_indices, "outlier_count": total_outliers})
            total_outliers = 0
            seg_indices = run
            centroid_sum = norm_patches[run].sum(axis=0)
            centroid_count = len(run)
            centroid = centroid_sum / centroid_count
            i = j

    if seg_indices:
        segments.append({"indices": seg_indices, "outlier_count": total_outliers})

    return segments
