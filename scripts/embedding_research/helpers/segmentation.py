"""Compact-catalog structural segmentation and observed-medoid computation (Plan C, P1-S4).

This is the *pure*, deterministic, CPU-only (numpy) canonical home for the compact
catalog's structural surface.  The durable compact catalog stores only structural
``seg_meta`` rows plus sparse canonical absorbed exceptions (no per-patch
``seg_membership`` relation), so exact searchable membership ``M_g`` is never stored
or read from an inclusive range: it is reconstructed here as
``[start, end) - absorbed_indices - {mask[i] == 0}`` via
:func:`reconstruct_searchable_indices`.

Surface (``§C`` / DD "Membership, segmentation, medoids, and weights"):

* :func:`run_spherical_segmentation` — finite unit-vector spherical segmentation with
  strict ``>`` boundary, ``OUTLIER_WINDOW=3`` absorption, hard searchable splits and
  renormalized spherical running centroid; returns duck-typed
  :class:`StructuralSegment` views exposing ``seg_id`` / ``start_idx`` / ``end_idx``
  (exclusive) / ``absorbed_indices``.
* :func:`reconstruct_searchable_indices` — exact ``M_g`` from a structural view,
  the song silence mask, and the patch count.  Structural ranges are NEVER treated as
  authoritative membership.
* :func:`select_observed_medoid_source_index` — finite nonzero observed medoid with
  maximal mean-cosine centrality and smallest-source-index ties (``(None, None)`` for
  empty / zero-norm candidates; NaN/Infinity raises ``ValueError``).

The old per-member segmentation model (``MembershipSegment`` /
``authoritative_segmentation`` / membership-era ``segment_signature`` / flat medoid
helpers) and the research ``seg_meta``/``seg_membership`` relations were retired in
P1-S12; db/segmentation.py's application-integrity guards were deleted with them.

This module never imports DuckDB, audio, ONNX, or CUDA; it consumes frozen stream
arrays (unit-normalised) exactly as ``StreamStore``/``HeadStreamStore`` deliver them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research.helpers.binning import OUTLIER_WINDOW

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "StructuralSegment",
    "reconstruct_searchable_indices",
    "run_spherical_segmentation",
    "select_observed_medoid_source_index",
]


# --------------------------------------------------------------------------- #
# Compact-catalog structural surface (Plan C P1-S4)                           #
# --------------------------------------------------------------------------- #
# The durable compact catalog stores only structural rows + sparse absorbed
# exceptions; exact searchable membership is reconstructed via
# reconstruct_searchable_indices.  These functions are the single canonical home
# (§C / DD "Membership, segmentation, medoids, and weights").
@dataclass(frozen=True)
class StructuralSegment:
    """One duck-typed structural segment exposing the compact reconstruction fields.

    Carries ``seg_id`` (zero-based), the structural ``start_idx``/``end_idx``
    (``end_idx`` EXCLUSIVE) report range, and the canonical sparse
    ``absorbed_indices`` (ascending, deduped).  It is a STRUCTURAL row: exact
    searchable membership is NEVER read from the inclusive range — callers run
    ``reconstruct_searchable_indices`` against the song mask.  Absorbed outliers
    retain their structural position but contribute no searchable mass.
    """

    seg_id: int
    start_idx: int
    end_idx: int
    absorbed_indices: tuple[int, ...]


def run_spherical_segmentation(
    unit_patches: np.ndarray,
    threshold: float,
    *,
    outlier_window: int = OUTLIER_WINDOW,
) -> list[StructuralSegment]:
    """Segment a patch matrix with the finite unit-vector spherical running centroid.

    Reproduces the PTC running-centroid contract exactly: finite-only input
    (NaN/Infinity raise :class:`ValueError`), strict ``>`` direct-L2 boundary (a
    patch exactly at the threshold is NOT a split), ``outlier_window`` absorption
    with return, and hard splitting (an excursion exceeding the window is an
    ordinary *searchable* structural segment, never absorbed).  Nonzero rows are
    normalized to unit vectors; the running centroid is the renormalized spherical
    sum of in-range members.

    Returns a list of :class:`StructuralSegment` (one per segment, ascending),
    each with an EXCLUSIVE ``end_idx`` and ascending ``absorbed_indices``.  An
    empty matrix returns ``[]``.
    """
    patches = np.asarray(unit_patches)
    if patches.ndim != 2:
        raise ValueError(f"unit_patches must be a 2-D [n, D] matrix; got shape {patches.shape}")
    if not np.all(np.isfinite(patches)):
        raise ValueError("run_spherical_segmentation rejects non-finite (NaN/Inf) input patches")
    n = len(patches)
    if n == 0:
        return []
    threshold = float(threshold)

    # Row L2-normalize finite nonzero patches; keep zero-norm rows as-is (they are
    # never medoid candidates downstream, handled by select_observed_medoid_source_index).
    norms = np.linalg.norm(patches, axis=1)
    normed = patches.copy()
    nz = norms > 0
    normed[nz] = patches[nz] / norms[nz, None]

    def is_boundary(idx: int, centroid: np.ndarray) -> bool:
        return float(np.linalg.norm(normed[idx] - centroid)) > threshold

    def renorm(vec: np.ndarray) -> np.ndarray:
        mag = float(np.linalg.norm(vec))
        return vec / mag if mag > 1e-9 else vec

    out: list[StructuralSegment] = []
    seg_in_range: list[int] = [0]
    seg_absorbed: list[int] = []
    centroid_sum: np.ndarray = normed[0].copy()
    centroid = renorm(centroid_sum)

    def flush(start_member: list[int], absorbed: list[int]) -> None:
        all_idx = sorted(set(start_member) | set(absorbed))
        out.append(
            StructuralSegment(
                seg_id=len(out),
                start_idx=int(all_idx[0]),
                end_idx=int(all_idx[-1]) + 1,
                absorbed_indices=tuple(sorted({int(i) for i in absorbed})),
            )
        )

    i = 1
    while i < n:
        if not is_boundary(i, centroid):
            seg_in_range.append(i)
            centroid_sum = centroid_sum + normed[i]
            centroid = renorm(centroid_sum)
            i += 1
            continue

        run: list[int] = [i]
        j = i + 1
        returned = False
        while j < n and len(run) <= outlier_window:
            if not is_boundary(j, centroid):
                seg_absorbed.extend(run)
                seg_in_range.append(j)
                centroid_sum = centroid_sum + normed[j]
                centroid = renorm(centroid_sum)
                i = j + 1
                returned = True
                break
            run.append(j)
            j += 1

        if not returned:
            flush(seg_in_range, seg_absorbed)
            seg_absorbed = []
            seg_in_range = list(run)
            centroid_sum = normed[np.asarray(run, dtype=int)].sum(axis=0)
            centroid = renorm(centroid_sum)
            i = j

    if seg_in_range:
        flush(seg_in_range, seg_absorbed)

    return out


def reconstruct_searchable_indices(
    meta: object,
    mask: np.ndarray | None,
    patch_count: int,
) -> np.ndarray:
    """Exactly reconstruct a segment's searchable membership ``M_g`` (sorted source indices).

    ``meta`` is a duck-typed :class:`SegMetaRecord`/structural view exposing
    ``start_idx`` (inclusive), ``end_idx`` (EXCLUSIVE), and ``absorbed_indices``
    (sparse canonical absorbed source indices).  Membership is exactly::

        {start <= i < end} - absorbed_indices - {mask[i] == 0}

    The structural range is NEVER treated as authoritative membership.  Returns a
    sorted integer array of the searchable source indices; an absorbed index outside
    ``[start, end)`` is a no-op.  ``mask`` is the whole-song ``uint8`` silence mask
    (``1`` = searchable, ``0`` = silent); rows beyond a shorter mask are searchable.
    """
    start = int(meta.start_idx)
    end = int(meta.end_idx)
    absorbed = tuple(int(i) for i in (meta.absorbed_indices or ()))
    patch_count = int(patch_count)
    excluded = np.zeros(patch_count, dtype=bool)
    if mask is not None:
        arr = np.asarray(mask)
        limit = min(arr.shape[0], patch_count)
        if limit > 0:
            excluded[:limit] = np.asarray(arr[:limit] == 0, dtype=bool)
    for idx in absorbed:
        if start <= idx < end and 0 <= idx < patch_count:
            excluded[idx] = True
    indices = np.arange(patch_count, dtype=int)
    selected = (indices >= start) & (indices < end) & (~excluded)
    return indices[selected]


def select_observed_medoid_source_index(
    unit_patches: np.ndarray,
    source_indices: Sequence[int],
) -> tuple[int | None, float | None]:
    """Select the observed medoid source index among finite nonzero searchable rows.

    Returns ``(index | None, centrality | None)``.  Only finite NONZERO searchable
    candidate rows are considered (``source_indices`` taken in ascending order);
    ``centrality`` is the mean cosine INCLUDING self over those candidate rows; the
    exact tie resolves to the SMALLEST SOURCE index.  Returns ``(None, None)`` when
    there are no finite nonzero candidates.  NaN/Infinity among the candidate rows
    raise :class:`ValueError` (never a silent medoid).
    """
    ordered = sorted(int(i) for i in source_indices)
    arr = np.asarray(unit_patches)
    if not ordered:
        return None, None
    rows = np.asarray(arr[np.asarray(ordered, dtype=int)], dtype=np.float32)
    if not np.all(np.isfinite(rows)):
        raise ValueError("select_observed_medoid_source_index rejects non-finite candidate rows")
    norms = np.linalg.norm(rows, axis=1)
    nonzero = norms > 0
    if not np.any(nonzero):
        return None, None
    sub = rows[nonzero]
    sims = sub @ sub.T  # unit rows => dot product == cosine
    means = sims.mean(axis=1)
    best_local = int(np.argmax(means))  # first max over ascending candidates
    cand_sources = [s for s, ok in zip(ordered, nonzero, strict=True) if ok]
    best_source = int(cand_sources[best_local])
    return best_source, float(means[best_local])
