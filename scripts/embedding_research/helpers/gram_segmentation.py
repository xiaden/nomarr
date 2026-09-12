"""Gram geometry and deterministic temporal-global PTC.

The production Gram matrix is built by NumPy row normalization followed by
float32 ``np.matmul`` and serialized as little-endian C-order float32 bytes.
The temporal-global PTC derivation itself remains deterministic scalar float32
arithmetic over that matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

OUTLIER_WINDOW = 3

if TYPE_CHECKING:
    from collections.abc import Iterable


class GramRefusalError(ValueError):
    """Fail-closed refusal for malformed or non-finite Gram input."""


@dataclass(frozen=True)
class StructuralSegment:
    """One source-ordered structural range and its absorbed source rows."""

    start_idx: int
    end_idx: int
    absorbed_indices: tuple[int, ...]
    indices: tuple[int, ...]

    @property
    def outlier_count(self) -> int:
        return len(self.absorbed_indices)


@dataclass(frozen=True)
class StructuralResult:
    """Threshold-specific structural PTC result derived solely from a Gram matrix."""

    threshold_index: int
    threshold: float
    segments: tuple[StructuralSegment, ...]
    diagnostics: dict[str, int]

    @property
    def ranges(self) -> tuple[tuple[int, int], ...]:
        return tuple((segment.start_idx, segment.end_idx) for segment in self.segments)

    @property
    def absorbed_indices(self) -> tuple[tuple[int, ...], ...]:
        return tuple(segment.absorbed_indices for segment in self.segments)


def _f32(value: float | np.float32) -> np.float32:
    return np.float32(value)


def _add(a: np.float32, b: np.float32) -> np.float32:
    return _f32(_f32(a) + _f32(b))


def _mul(a: np.float32, b: np.float32) -> np.float32:
    return _f32(_f32(a) * _f32(b))


def _sqrt(value: np.float32) -> np.float32:
    return _f32(np.sqrt(_f32(value), dtype=np.float32))


def normalize_float32(stream: Any) -> np.ndarray:
    """Normalize rows with NumPy float32 row arithmetic.

    Zero rows are retained as zero rows.  Inputs are validated before any
    normalization so non-finite evidence cannot reach the matrix kernel.
    """
    values = np.asarray(stream)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise GramRefusalError("stream must be a non-empty two-dimensional matrix")
    if values.dtype != np.dtype("float32") or not np.isfinite(values).all():
        raise GramRefusalError("stream must be finite float32 evidence")
    norms = np.linalg.norm(values, axis=1, keepdims=True).astype(np.float32)
    safe_norms = np.where(norms > np.float32(0.0), norms, np.float32(1.0))
    result = np.divide(values, safe_norms, dtype=np.float32)
    if not np.isfinite(result).all():
        raise GramRefusalError("normalized stream is non-finite")
    result = np.asarray(result, dtype="<f4", order="C")
    result.setflags(write=False)
    return result


def gram_from_stream(stream: Any) -> tuple[np.ndarray, bytes]:
    """Produce the canonical full square Gram matrix and raw bytes."""
    unit = normalize_float32(stream)
    count = unit.shape[0]
    gram = np.matmul(unit, unit.T, dtype=np.float32)
    if gram.shape != (count, count) or not np.isfinite(gram).all():
        raise GramRefusalError("Gram matrix is non-finite or non-square")
    gram = np.asarray(gram, dtype="<f4", order="C")
    blob = gram.tobytes(order="C")
    if len(blob) != 4 * count * count:
        raise GramRefusalError("invalid Gram serialization length")
    decoded = np.frombuffer(blob, dtype="<f4").reshape((count, count), order="C")
    if not np.array_equal(decoded, gram) or decoded.tobytes(order="C") != blob:
        raise GramRefusalError("Gram serialization failed byte round-trip")
    gram.setflags(write=False)
    return gram, blob


def _threshold(threshold_index: int) -> np.float32:
    if isinstance(threshold_index, bool) or not isinstance(threshold_index, (int, np.integer)):
        raise GramRefusalError("threshold_index must be an integer")
    if int(threshold_index) < 0:
        raise GramRefusalError("threshold_index must be non-negative")
    value = _f32(_f32(0.30) + _f32(_f32(threshold_index) * _f32(0.01)))
    if not np.isfinite(value):
        raise GramRefusalError("threshold is non-finite")
    return value


def _validate_gram(gram: Any) -> np.ndarray:
    matrix = np.asarray(gram)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[0] != matrix.shape[1]:
        raise GramRefusalError("Gram must be a non-empty square matrix")
    if matrix.dtype != np.dtype("float32") or not np.isfinite(matrix).all():
        raise GramRefusalError("Gram must be finite float32")
    return np.asarray(matrix, dtype="<f4", order="C")


def _row_distance(gram: np.ndarray, row: int, indices: list[int]) -> np.float32:
    centroid_norm_sq = np.float32(0.0)
    for left in indices:
        for right in indices:
            centroid_norm_sq = _add(centroid_norm_sq, gram[left, right])
    centroid_norm = _sqrt(max(np.float32(0.0), centroid_norm_sq))
    row_norm_sq = max(np.float32(0.0), gram[row, row])
    row_centroid = np.float32(0.0)
    for source in indices:
        row_centroid = _add(row_centroid, gram[row, source])
    if centroid_norm > np.float32(0.0):
        row_centroid = _f32(row_centroid / centroid_norm)
    else:
        row_centroid = np.float32(0.0)
    distance_sq = _f32(row_norm_sq + np.float32(1.0) - _f32(np.float32(2.0) * row_centroid))
    return _sqrt(max(np.float32(0.0), distance_sq))


def derive_temporal_global_from_gram(gram: Any, threshold_index: int) -> StructuralResult:
    """Derive strict-boundary temporal-global PTC from one in-memory Gram matrix."""
    matrix = _validate_gram(gram)
    threshold = _threshold(threshold_index)
    count = matrix.shape[0]
    diagnostics = {
        "distance_boundary_count": 0,
        "absorbed_outlier_count": 0,
        "hard_split_count": 0,
        "return_from_outlier_count": 0,
    }
    segments: list[StructuralSegment] = []
    active = [0]
    absorbed: list[int] = []
    i = 1
    while i < count:
        if _row_distance(matrix, i, active) <= threshold:
            active.append(i)
            i += 1
            continue
        diagnostics["distance_boundary_count"] += 1
        run = [i]
        j = i + 1
        returned = False
        while j < count and len(run) <= OUTLIER_WINDOW:
            if _row_distance(matrix, j, active) <= threshold:
                absorbed.extend(run)
                diagnostics["absorbed_outlier_count"] += len(run)
                diagnostics["return_from_outlier_count"] += 1
                active.append(j)
                i = j + 1
                returned = True
                break
            run.append(j)
            j += 1
        if not returned:
            diagnostics["hard_split_count"] += 1
            segments.append(StructuralSegment(active[0], run[0], tuple(absorbed), tuple(active)))
            active = run
            absorbed = []
            i = j
    segments.append(StructuralSegment(active[0], count, tuple(absorbed), tuple(active)))
    return StructuralResult(int(threshold_index), float(threshold), tuple(segments), diagnostics)


def derive_all_temporal_global(gram: Any, threshold_indices: Iterable[int]) -> tuple[StructuralResult, ...]:
    """Derive thresholds from one validated in-memory matrix, without reloads."""
    matrix = _validate_gram(gram)
    return tuple(derive_temporal_global_from_gram(matrix, index) for index in threshold_indices)


def _candidate_indices(gram: np.ndarray, source_indices: Iterable[int]) -> list[int]:
    """Return sorted finite, nonzero-diagonal source rows for Gram centrality."""
    ordered = sorted(int(index) for index in source_indices)
    if len(set(ordered)) != len(ordered):
        raise GramRefusalError("medoid source indices must be unique")
    if any(index < 0 or index >= gram.shape[0] for index in ordered):
        raise GramRefusalError("medoid source index is outside the Gram matrix")
    if not ordered:
        return []
    diagonal = gram[np.asarray(ordered, dtype=int), np.asarray(ordered, dtype=int)]
    if not np.isfinite(diagonal).all():
        raise GramRefusalError("medoid diagonal is non-finite")
    return [index for index, value in zip(ordered, diagonal, strict=True) if value > np.float32(0.0)]


def select_observed_medoid_from_gram(gram: Any, source_indices: Iterable[int]) -> tuple[int | None, float | None]:
    """Select an observed source row by mean Gram centrality.

    Candidate rows with a zero diagonal are excluded.  Centrality is the mean
    of the candidate-by-candidate Gram row, including the candidate's self
    value; sorted source order makes exact ties deterministic.
    """
    matrix = _validate_gram(gram)
    candidates = _candidate_indices(matrix, source_indices)
    if not candidates:
        return None, None
    positions = np.asarray(candidates, dtype=int)
    centralities = np.asarray(matrix[np.ix_(positions, positions)].mean(axis=1), dtype=np.float64)
    if not np.isfinite(centralities).all():
        raise GramRefusalError("medoid centrality is non-finite")
    best = int(np.argmax(centralities))
    return candidates[best], float(centralities[best])


def observed_global_medoid_from_gram(gram: Any, mask: Any) -> tuple[int | None, float | None]:
    """Select the observed whole-song medoid from the committed searchable mask."""
    matrix = _validate_gram(gram)
    validated = require_exact_binary_mask(mask, matrix.shape[0])
    return select_observed_medoid_from_gram(matrix, np.flatnonzero(validated == 1))


def require_exact_binary_mask(mask: Any, patch_count: int) -> np.ndarray:
    """Validate an exact one-dimensional binary ``uint8`` search mask."""
    if mask is None:
        raise GramRefusalError("committed silence mask is required")
    array = np.asarray(mask)
    if array.dtype != np.dtype("uint8") or array.ndim != 1 or array.shape[0] != int(patch_count):
        raise GramRefusalError("mask must be exactly uint8[patch_count]")
    if not np.isin(array, np.asarray((0, 1), dtype=np.uint8)).all():
        raise GramRefusalError("mask values must be exactly 0 or 1")
    return array


def search_projection_from_gram(structural: StructuralResult, gram: Any, mask: Any) -> GramSearchResult:
    """Attach searchable membership, medoids, counts, and normalized weights."""
    matrix = _validate_gram(gram)
    validated = require_exact_binary_mask(mask, matrix.shape[0])
    projections: list[tuple[StructuralSegment, tuple[int, ...], int, int | None, float | None]] = []
    for segment in structural.segments:
        start, end = int(segment.start_idx), int(segment.end_idx)
        if start < 0 or end < start or end > matrix.shape[0]:
            raise GramRefusalError("structural range is outside the Gram matrix")
        absorbed = tuple(int(index) for index in segment.absorbed_indices)
        if len(set(absorbed)) != len(absorbed) or any(index < start or index >= end for index in absorbed):
            raise GramRefusalError("absorbed source indices must be unique and in-range")
        absorbed_set = set(absorbed)
        searchable = tuple(index for index in range(start, end) if validated[index] == 1 and index not in absorbed_set)
        medoid, centrality = select_observed_medoid_from_gram(matrix, searchable)
        projections.append((segment, searchable, len(searchable), medoid, centrality))
    total = sum(item[2] for item in projections)
    if total == 0:
        weights = [0.0] * len(projections)
    else:
        weights = [item[2] / total for item in projections]
    result = tuple(
        GramSearchSegment(item[0], item[1], item[2], float(weight), item[3], item[4])
        for item, weight in zip(projections, weights, strict=True)
    )
    return GramSearchResult(result, total)


@dataclass(frozen=True)
class GramSearchSegment:
    """Search projection of one structural segment.

    Structural boundaries and absorbed rows are retained independently from the
    mask-derived searchable membership.  A missing medoid is represented by
    ``None``; no vector is synthesized here.
    """

    structural: StructuralSegment
    searchable_indices: tuple[int, ...]
    searchable_count: int
    searchable_weight: float
    medoid_source_index: int | None
    medoid_centrality: float | None


@dataclass(frozen=True)
class GramSearchResult:
    """Structural segments plus their mask-derived searchable projections."""

    segments: tuple[GramSearchSegment, ...]
    total_searchable: int

    @property
    def zero_total(self) -> bool:
        return self.total_searchable == 0


__all__ = [
    "GramRefusalError",
    "GramSearchResult",
    "GramSearchSegment",
    "StructuralResult",
    "StructuralSegment",
    "derive_all_temporal_global",
    "derive_temporal_global_from_gram",
    "gram_from_stream",
    "normalize_float32",
    "observed_global_medoid_from_gram",
    "require_exact_binary_mask",
    "search_projection_from_gram",
    "select_observed_medoid_from_gram",
]
