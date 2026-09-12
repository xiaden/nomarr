"""Test-only scalar coordinate oracle for the temporal-global Gram engine (DD R3).

This is the retired scalar stream implementation preserved ONLY as an independent test
oracle: it segments raw unit-vector coordinates with a renormalized spherical running
centroid, strict ``>`` boundary, ``OUTLIER_WINDOW=3`` absorption, and hard splits.  It
must never be imported by production code or by any non-test module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

OUTLIER_WINDOW = 3


@dataclass(frozen=True)
class OracleSegment:
    start_idx: int
    end_idx: int
    absorbed_indices: tuple[int, ...]


def _global_dist(left: np.ndarray, right: np.ndarray) -> float:
    """Direct L2 distance between two unit vectors (temporal_global metric)."""
    return float(np.linalg.norm(np.asarray(left, dtype=np.float64) - np.asarray(right, dtype=np.float64)))


def run_spherical_segmentation_global(
    unit_patches: np.ndarray,
    threshold: float,
    *,
    outlier_window: int = OUTLIER_WINDOW,
) -> list[OracleSegment]:
    patches = np.asarray(unit_patches)
    if patches.ndim != 2:
        raise ValueError("unit_patches must be 2-D")
    if not np.all(np.isfinite(patches)):
        raise ValueError("non-finite input patches")
    count = len(patches)
    if count == 0:
        return []
    threshold = float(threshold)
    norms = np.linalg.norm(patches, axis=1)
    normed = patches.copy()
    nonzero = norms > 0
    normed[nonzero] = patches[nonzero] / norms[nonzero, None]

    def is_boundary(index: int, centroid: np.ndarray) -> bool:
        return _global_dist(normed[index], centroid) > threshold

    def renorm(vector: np.ndarray) -> np.ndarray:
        magnitude = float(np.linalg.norm(vector))
        return vector / magnitude if magnitude > 1e-9 else vector

    out: list[OracleSegment] = []
    in_range: list[int] = [0]
    absorbed: list[int] = []
    centroid_sum = normed[0].copy()
    centroid = renorm(centroid_sum)

    def flush(members: list[int], absorbed_local: list[int]) -> None:
        all_indices = sorted(set(members) | set(absorbed_local))
        out.append(
            OracleSegment(
                start_idx=int(all_indices[0]),
                end_idx=int(all_indices[-1]) + 1,
                absorbed_indices=tuple(sorted({int(i) for i in absorbed_local})),
            )
        )

    index = 1
    while index < count:
        if not is_boundary(index, centroid):
            in_range.append(index)
            centroid_sum = centroid_sum + normed[index]
            centroid = renorm(centroid_sum)
            index += 1
            continue

        run: list[int] = [index]
        probe = index + 1
        returned = False
        while probe < count and len(run) <= outlier_window:
            if not is_boundary(probe, centroid):
                absorbed.extend(run)
                in_range.append(probe)
                centroid_sum = centroid_sum + normed[probe]
                centroid = renorm(centroid_sum)
                index = probe + 1
                returned = True
                break
            run.append(probe)
            probe += 1
        if not returned:
            flush(in_range, absorbed)
            absorbed = []
            in_range = list(run)
            centroid_sum = normed[np.asarray(run, dtype=int)].sum(axis=0)
            centroid = renorm(centroid_sum)
            index = probe
    if in_range:
        flush(in_range, absorbed)
    return out


__all__ = ["OUTLIER_WINDOW", "OracleSegment", "run_spherical_segmentation_global"]
