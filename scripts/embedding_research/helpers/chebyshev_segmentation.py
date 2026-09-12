"""Secondary coordinate-input temporal Chebyshev experiment.

This module is deliberately separate from the primary Gram/L2 engine.  It accepts
coordinate rows, computes a running spherical centroid, and applies the strict
per-dimension boundary directly.  It has no Gram imports or cache identity and is
not part of the primary threshold sweep.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


class ChebyshevRefusalError(ValueError):
    """Fail-closed refusal for malformed coordinate evidence."""


SECONDARY_EXPERIMENT = "temporal_perdim_chebyshev_secondary"


@dataclass(frozen=True)
class ChebyshevSegment:
    """One source-ordered coordinate-input segment."""

    start_idx: int
    end_idx: int
    absorbed_indices: tuple[int, ...]
    indices: tuple[int, ...]


@dataclass(frozen=True)
class ChebyshevResult:
    """Strict Chebyshev segmentation for one explicitly selected threshold."""

    threshold: float
    segments: tuple[ChebyshevSegment, ...]

    @property
    def ranges(self) -> tuple[tuple[int, int], ...]:
        return tuple((segment.start_idx, segment.end_idx) for segment in self.segments)


def _coordinates(stream: Any) -> np.ndarray:
    values = np.asarray(stream)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ChebyshevRefusalError("coordinate stream must be a non-empty two-dimensional matrix")
    if values.dtype != np.dtype("float32") or not np.isfinite(values).all():
        raise ChebyshevRefusalError("coordinate stream must be finite float32 evidence")
    unit = np.zeros(values.shape, dtype=np.float32)
    for row_index, row in enumerate(values):
        norm_sq = np.float32(0.0)
        for value in row:
            norm_sq = np.float32(norm_sq + np.float32(value) * np.float32(value))
        norm = np.float32(np.sqrt(norm_sq, dtype=np.float32))
        if norm > np.float32(0.0):
            for dimension, value in enumerate(row):
                unit[row_index, dimension] = np.float32(value / norm)
    if not np.isfinite(unit).all():
        raise ChebyshevRefusalError("normalized coordinates are non-finite")
    return unit


def _threshold(value: Any) -> np.float32:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ChebyshevRefusalError("threshold must be numeric")
    result = np.float32(value)
    if not np.isfinite(result) or result < np.float32(0.0):
        raise ChebyshevRefusalError("threshold must be finite and non-negative")
    return result


def temporal_perdim_from_coordinates(stream: Any, threshold: Any, *, outlier_window: int = 3) -> ChebyshevResult:
    """Run the secondary coordinate-input Chebyshev temporal experiment.

    A boundary is strict ``max(abs(patch - centroid)) > threshold``.  In-range
    rows update a renormalized running spherical centroid.  Up to three boundary
    rows are absorbed when a later row returns; otherwise the run hard-splits.
    """
    if isinstance(outlier_window, bool) or not isinstance(outlier_window, int) or outlier_window < 1:
        raise ChebyshevRefusalError("outlier_window must be a positive integer")
    values = _coordinates(stream)
    limit = _threshold(threshold)
    segments: list[ChebyshevSegment] = []
    active = [0]
    absorbed: list[int] = []
    centroid_sum = values[0].copy()
    i = 1

    def centroid() -> np.ndarray:
        norm = np.float32(np.sqrt(np.sum(centroid_sum * centroid_sum, dtype=np.float32), dtype=np.float32))
        return centroid_sum / norm if norm > np.float32(0.0) else np.zeros_like(centroid_sum)

    def boundary(index: int) -> bool:
        return np.max(np.abs(values[index] - centroid())) > limit

    while i < values.shape[0]:
        if not boundary(i):
            active.append(i)
            centroid_sum = np.asarray(centroid_sum + values[i], dtype=np.float32)
            i += 1
            continue
        run = [i]
        j = i + 1
        returned = False
        while j < values.shape[0] and len(run) <= outlier_window:
            if not boundary(j):
                absorbed.extend(run)
                active.append(j)
                centroid_sum = np.asarray(centroid_sum + values[j], dtype=np.float32)
                i = j + 1
                returned = True
                break
            run.append(j)
            j += 1
        if not returned:
            segments.append(ChebyshevSegment(active[0], run[0], tuple(absorbed), tuple(active)))
            active = run
            absorbed = []
            centroid_sum = np.asarray(values[run].sum(axis=0, dtype=np.float32), dtype=np.float32)
            i = j
    segments.append(ChebyshevSegment(active[0], values.shape[0], tuple(absorbed), tuple(active)))
    return ChebyshevResult(float(limit), tuple(segments))


__all__ = [
    "SECONDARY_EXPERIMENT",
    "ChebyshevRefusalError",
    "ChebyshevResult",
    "ChebyshevSegment",
    "temporal_perdim_from_coordinates",
]
