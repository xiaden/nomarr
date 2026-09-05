"""Temporal-segmentation algorithms and distance/config constants (retained surface).

This module is the retained temporal-segmentation helper library for the active
catalog/segmentation/run surfaces.  It provides the strict ``>`` boundary
:func:`temporal_segment` semantics (with the frozen ``OUTLIER_WINDOW=3`` outlier
absorption), the L2 / Chebyshev distance functions behind ``DIST_FNS``, and the
frozen catalog sweep literals (``DIST_THRESHOLDS`` / ``BIN_MODES``) that replaced the
removed ``[binning]`` config grid.  The obsolete copied-vector/CTP sweep constants and
cache-semantics-version helpers were removed with their deleted surfaces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

# Frozen catalog sweep literals (previously driven by the removed ``[binning]``
# config section).  The strict current schema does not carry these; they are frozen
# constants consumed by run.py's catalog input generation.
DIST_THRESHOLDS: list[float] = [0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5]
BIN_MODES: list[str] = ["temporal_global", "temporal_perdim"]

OUTLIER_WINDOW: int = 3

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
