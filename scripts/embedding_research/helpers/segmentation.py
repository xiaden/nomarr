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

from scripts.embedding_research.helpers.binning import DIST_FNS, OUTLIER_WINDOW

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ObservedMedoid",
    "StructuralSegment",
    "observed_global_medoid",
    "reconstruct_searchable_indices",
    "require_exact_whole_song_mask",
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
    bin_mode: str = "temporal_global",
    outlier_window: int = OUTLIER_WINDOW,
) -> list[StructuralSegment]:
    """Segment a patch matrix with the finite unit-vector spherical running centroid.

    Reproduces the PTC running-centroid contract exactly: finite-only input
    (NaN/Infinity raise :class:`ValueError`), strict ``>`` boundary (a patch
    exactly at the threshold is NOT a split), ``outlier_window`` absorption with
    return, and hard splitting (an excursion exceeding the window is an ordinary
    *searchable* structural segment, never absorbed).  The boundary metric is
    dispatched through the canonical distance map :data:`DIST_FNS`: ``bin_mode``
    ``"temporal_global"`` uses direct L2 (:func:`global_dist`) and
    ``"temporal_perdim"`` uses per-dimension Chebyshev (:func:`perdim_dist`);
    any other mode fails closed with :class:`ValueError`.  Nonzero rows are
    normalized to unit vectors; the running centroid is the renormalized spherical
    sum of in-range members.

    Returns a list of :class:`StructuralSegment` (one per segment, ascending),
    each with an EXCLUSIVE ``end_idx`` and ascending ``absorbed_indices``.  An
    empty matrix returns ``[]``.
    """
    if bin_mode not in DIST_FNS:
        raise ValueError(f"unknown bin_mode {bin_mode!r}; supported: {sorted(DIST_FNS)}")
    dist_fn = DIST_FNS[bin_mode]
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
        return dist_fn(normed[idx], centroid) > threshold

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


def require_exact_whole_song_mask(mask: object, patch_count: int) -> np.ndarray:
    """Validate an exact ``uint8[patch_count]`` 1-D whole-song silence mask or refuse.

    ``mask`` must be a 1-D ``uint8`` array whose length EXACTLY equals *patch_count* (the
    committed stream's patch count for the exact ``(song_id, backbone)`` group).  The
    committed silence mask is REQUIRED and never optional.  A ``None`` (missing), short,
    long, wrong-dtype, or non-1D mask raises a typed ``ValueError`` refusal — a shorter
    mask is NEVER interpreted with trailing patches searchable (no short-mask truncation
    or all-searchable fail-open), and absence is never interpreted as no silence.

    Returns the validated mask as a ``uint8[patch_count]`` array.
    """
    if mask is None:
        raise ValueError(
            "a whole-song committed silence mask is required for the exact (song_id, "
            "backbone) observation group; None is never interpreted as no silence (a "
            "missing mask must fail closed)"
        )
    patch_count = int(patch_count)
    arr = np.asarray(mask)
    if arr.dtype != np.dtype("uint8"):
        raise ValueError(
            f"whole-song committed silence mask must be uint8; got dtype {arr.dtype} (wrong-dtype masks fail closed)"
        )
    if arr.ndim != 1 or arr.shape[0] != patch_count:
        raise ValueError(
            f"whole-song committed silence mask must be a 1-D uint8[{patch_count}] array; "
            f"got shape {arr.shape} — short/long/non-1D masks fail closed, never truncated "
            "or treated as trailing-searchable"
        )
    return arr


def reconstruct_searchable_indices(
    meta: object,
    mask: np.ndarray,
    patch_count: int,
) -> np.ndarray:
    """Exactly reconstruct a segment's searchable membership ``M_g`` (sorted source indices).

    ``meta`` is a duck-typed :class:`SegMetaRecord`/structural view exposing
    ``start_idx`` (inclusive), ``end_idx`` (EXCLUSIVE), and ``absorbed_indices``
    (sparse canonical absorbed source indices).  Membership is exactly::

        {start <= i < end} - absorbed_indices - {mask[i] == 0}

    The structural range is NEVER treated as authoritative membership.  Returns a
    sorted integer array of the searchable source indices; an absorbed index outside
    ``[start, end)`` is a no-op.  ``mask`` is the whole-song committed
    ``uint8[patch_count]`` silence mask (``1`` = searchable, ``0`` = silent) for the
    exact ``(song_id, backbone)`` observation group; it is REQUIRED and never optional
    and must be EXACTLY ``uint8[patch_count]``.  A None/short/long/wrong-dtype/non-1D
    mask is refused (fail closed) — a shorter mask is never interpreted with trailing
    patches searchable and a missing committed mask is never interpreted as no silence.
    """
    patch_count = int(patch_count)
    # The mask is REQUIRED and must be an exact ``uint8[patch_count]`` 1-D whole-song silence
    # mask.  A None/short/long/wrong-dtype/non-1D mask is a typed refusal — a shorter mask is
    # NEVER interpreted with trailing patches searchable and a missing mask is never
    # interpreted as no silence.
    arr = require_exact_whole_song_mask(mask, patch_count)
    start = int(meta.start_idx)
    end = int(meta.end_idx)
    absorbed = tuple(int(i) for i in (meta.absorbed_indices or ()))
    excluded = np.zeros(patch_count, dtype=bool)
    excluded[:] = np.asarray(arr == 0, dtype=bool)
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


@dataclass(frozen=True)
class ObservedMedoid:
    """The observed global medoid result for one song / searchable population.

    ``source_index`` is the observed source patch index (an ORIGINAL committed-stream
    row, never a synthetic/coordinate-wise median vector) with maximal mean-cosine
    centrality over the provided searchable source population; ``centrality`` is that
    mean cosine (including self) over the finite nonzero candidate rows.  When there is
    no finite nonzero searchable candidate (an empty population or a whole song that is
    zero-searchable / all-zero-norm) both fields are ``None`` — there is NO baseline
    vector, so the song contributes nothing to a baseline corpus or candidate search.
    """

    source_index: int | None
    centrality: float | None


# --------------------------------------------------------------------------- #
# Global (whole-song) observed medoid (DD "Membership, segmentation, medoids,
# and weights" L238; Plan B §B).  Uses the SAME observed-source mean-cosine /
# smallest-source-index-tie rule as the segment medoid (select_observed_medoid_source_index)
# over the whole-song non-silent searchable population.  NEVER a synthetic median,
# never ``pool_medoid_raw`` / ``pool_medoid_norm``.  The caller supplies the already
# unit-normalised patch rows and the searchable source indices (non-silent patches,
# and any absorbed/otherwise-excluded positions the caller's population excludes).
# --------------------------------------------------------------------------- #
def observed_global_medoid(
    unit_patches: np.ndarray,
    searchable_source_indices: Sequence[int],
) -> ObservedMedoid:
    """Select the observed global medoid among finite nonzero searchable source rows.

    Silence/absorbed-aware: the population is whatever ``searchable_source_indices``
    the caller passes (e.g. all non-silent ``mask == 1`` source patches for the whole
    song, or a narrower set that also excludes absorbed positions).  Applies the exact
    segment-medoid rule (:func:`select_observed_medoid_source_index`) — maximal mean
    cosine over the finite NONZERO candidate rows, smallest source index wins an exact
    tie, zero-norm rows are never selected — and returns an :class:`ObservedMedoid`.

    ``unit_patches`` must already be row-unit-normalised finite patches (a zero-norm row
    is never a medoid candidate).  Zero-searchable (empty population) and all-zero-norm
    populations return ``ObservedMedoid(None, None)`` — no baseline vector.  Non-finite
    input among the candidate rows raises :class:`ValueError` (never a silent medoid).
    """
    source_index, centrality = select_observed_medoid_source_index(unit_patches, searchable_source_indices)
    return ObservedMedoid(source_index=source_index, centrality=centrality)
