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

DIST_THRESHOLDS: list[float] = _cfg.get("binning", {}).get("dist_thresholds", [0.3, 0.5, 0.7, 1.0])
BIN_MODES: list[str] = _cfg.get("binning", {}).get("bin_modes", ["temporal_global", "temporal_perdim"])

# Cache/data semantics versions used for cache identity and invalidation.
VECTOR_SEMANTICS_VERSION: int = 2
THRESHOLD_SEMANTICS_VERSION: int = 2
OPTIMIZER_SEMANTICS_VERSION: int = 2
BIN_PAYLOAD_VERSION: int = 3

OUTLIER_WINDOW: int = 3


def threshold_key(x: float) -> str:
    """Canonical threshold identity used in paths/keys/report rows."""
    return f"{float(x):.3f}"


def canonical_threshold(x: float) -> float:
    """Canonical threshold float used for numeric comparisons/math."""
    return round(float(x), 3)


def temporal_global_equivalents(dist_thresh: float) -> tuple[float, float]:
    """Return (cosine_equivalent, angle_degrees) for temporal_global L2 threshold.

    For unit vectors: dist = sqrt(2 - 2*cos(theta))
                    => cos(theta) = 1 - dist^2 / 2
    """
    cos_equiv = 1.0 - (float(dist_thresh) ** 2) / 2.0
    cos_equiv = float(np.clip(cos_equiv, -1.0, 1.0))
    angle_deg = float(np.degrees(np.arccos(cos_equiv)))
    return cos_equiv, angle_deg


def cache_semantics_tag() -> str:
    """Stable cache-tag carrying semantics versions for invalidation."""
    return (
        f"vs{VECTOR_SEMANTICS_VERSION}"
        f"_ts{THRESHOLD_SEMANTICS_VERSION}"
        f"_os{OPTIMIZER_SEMANTICS_VERSION}"
        f"_bp{BIN_PAYLOAD_VERSION}"
    )


# ── Distance functions ────────────────────────────────────────────────────────


def global_dist(patch: np.ndarray, centroid: np.ndarray) -> float:
    """L2 distance between a patch and the current segment centroid.

    IMPORTANT: For temporal_global, threshold is a direct unit-vector L2
    distance (not a std multiplier).
    """
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

    Each bin maintains a renormalized running centroid (spherical mean) so that
    the distance metric stays on the unit sphere throughout.  A patch triggers a
    bin boundary when it exceeds *threshold* via *dist_fn*.  Up to
    *outlier_window* consecutive boundary patches are absorbed as outliers when
    the next in-range patch returns; if no return occurs a new bin is started.

    Args:
        norm_patches:   (n, D) array of L2-normalised patch vectors.
        threshold:      Boundary distance.  Patches farther than this from the
                        bin centroid trigger a boundary check.
        dist_fn:        Distance function — ``global_dist`` (L2) or
                        ``perdim_dist`` (Chebyshev).
        outlier_window: Maximum consecutive boundary patches absorbed as
                        outliers before a hard bin split (default 3).

    Returns:
        List of ``{"indices": [...], "outlier_count": int}`` dicts, one per bin.
        Outlier patches are *not* included in ``indices`` (they are excluded
        from bin pooling).
    """
    n = len(norm_patches)
    if n == 0:
        return []

    def _is_boundary(idx: int, centroid: np.ndarray) -> bool:
        return dist_fn(norm_patches[idx], centroid) > threshold

    def _renorm(vec: np.ndarray) -> np.ndarray:
        n_ = float(np.linalg.norm(vec))
        return vec / n_ if n_ > 1e-9 else vec

    segments: list[dict] = []
    total_outliers = 0

    seg_indices: list[int] = [0]
    centroid_sum: np.ndarray = norm_patches[0].copy()
    centroid = _renorm(centroid_sum)

    i = 1
    while i < n:
        if not _is_boundary(i, centroid):
            seg_indices.append(i)
            centroid_sum = centroid_sum + norm_patches[i]
            centroid = _renorm(centroid_sum)
            i += 1
            continue

        run: list[int] = [i]
        j = i + 1
        returned = False
        while j < n and len(run) <= outlier_window:
            if not _is_boundary(j, centroid):
                total_outliers += len(run)
                seg_indices.append(j)
                centroid_sum = centroid_sum + norm_patches[j]
                centroid = _renorm(centroid_sum)
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
            centroid = _renorm(centroid_sum)
            i = j

    if seg_indices:
        segments.append({"indices": seg_indices, "outlier_count": total_outliers})

    return segments


def temporal_segment_with_diagnostics(
    norm_patches: np.ndarray,
    threshold: float,
    dist_fn: Callable[[np.ndarray, np.ndarray], float],
    outlier_window: int = OUTLIER_WINDOW,
) -> tuple[list[dict], dict[str, int]]:
    """Run temporal segmentation and return boundary-reason diagnostics.

    This mirrors :func:`temporal_segment` behavior while additionally returning
    counters that explain why boundaries occurred.
    """
    n = len(norm_patches)
    if n == 0:
        return [], {
            "distance_boundary_count": 0,
            "absorbed_outlier_count": 0,
            "hard_split_count": 0,
            "return_from_outlier_count": 0,
        }

    def _is_boundary(idx: int, centroid: np.ndarray) -> bool:
        return dist_fn(norm_patches[idx], centroid) > threshold

    def _renorm(vec: np.ndarray) -> np.ndarray:
        n_ = float(np.linalg.norm(vec))
        return vec / n_ if n_ > 1e-9 else vec

    diagnostics = {
        "distance_boundary_count": 0,
        "absorbed_outlier_count": 0,
        "hard_split_count": 0,
        "return_from_outlier_count": 0,
    }

    segments: list[dict] = []
    total_outliers = 0

    seg_indices: list[int] = [0]
    centroid_sum: np.ndarray = norm_patches[0].copy()
    centroid = _renorm(centroid_sum)

    i = 1
    while i < n:
        if not _is_boundary(i, centroid):
            seg_indices.append(i)
            centroid_sum = centroid_sum + norm_patches[i]
            centroid = _renorm(centroid_sum)
            i += 1
            continue

        diagnostics["distance_boundary_count"] += 1
        run: list[int] = [i]
        j = i + 1
        returned = False

        while j < n and len(run) <= outlier_window:
            if not _is_boundary(j, centroid):
                total_outliers += len(run)
                diagnostics["absorbed_outlier_count"] += len(run)
                diagnostics["return_from_outlier_count"] += 1
                seg_indices.append(j)
                centroid_sum = centroid_sum + norm_patches[j]
                centroid = _renorm(centroid_sum)
                i = j + 1
                returned = True
                break
            run.append(j)
            j += 1

        if not returned:
            diagnostics["hard_split_count"] += 1
            segments.append({"indices": seg_indices, "outlier_count": total_outliers})
            total_outliers = 0
            seg_indices = run
            centroid_sum = norm_patches[run].sum(axis=0)
            centroid = _renorm(centroid_sum)
            i = j

    if seg_indices:
        segments.append({"indices": seg_indices, "outlier_count": total_outliers})

    return segments, diagnostics
