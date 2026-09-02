"""Authoritative segmentation membership and observed-medoid computation (Plan C, Phase 2).

This is the *pure*, deterministic, CPU-only (numpy) computation that a later
``build_segmentation_catalog`` (Phase 3) fans out into ``seg_meta`` +
``seg_membership`` rows.  It intentionally lives in ``helpers/`` (alongside
``helpers/binning.py``) rather than in ``db/segmentation.py``: ``db/segmentation.py``
owns the DuckDB schema vocabulary and the *application-integrity guards* (duplicate /
range / orphan rejection); it must not be conflated with pure number crunching.

Guarantees this module owns (R6 / R7 / the "range-vs-membership" and "medoid"
decisions):

* Every assigned source patch index of a segment is recorded once, with an exact
  ``is_absorbed_outlier`` flag.  The inclusive ``start_idx``/``end_idx`` are
  STRUCTURAL REPORT RANGES ONLY — membership is produced by running the
  running-centroid algorithm and recording each patch, never by expanding a range.
* The segmentation reproduces the PTC running-centroid algorithm exactly
  (strict ``>`` boundary, ``OUTLIER_WINDOW=3`` absorption, renormalized spherical
  running centroid) so the per-segment in-range membership equals
  ``helpers.binning.temporal_segment`` output, while additionally exposing WHICH
  absorbed outlier source indices belong to each segment (which ``temporal_segment``
  only counts, never identifies).
* Medoids are OBSERVED source patch indices chosen with deterministic smallest-index
  tie-breaking.  Only ``medoid_source_patch_idx`` is produced — never a copied vector,
  never ``pool_medoid_raw``/``pool_medoid_norm``, never a synthetic coordinate-wise
  median.  The segment medoid is chosen over the segment's *in-range* member source
  patches (the set historical PTC pooling used), so the catalog medoid preserves the
  existing medoid-to-medoid primary scoring semantics exactly.
* Invariant relationships (row count == member_count, absorbed-outlier rows ==
  absorbed-outlier count, patch-count weight == member_count incl. absorbed outliers,
  medoid is an observed member, membership partitions the stream once) are testable
  and enforced by :func:`validate_segment_invariants` /
  :func:`validate_full_partition`.
* ``segment_signature`` is defined over the membership + medoid as a deterministic
  sha256 of a canonical serialization.  Phase 3's catalog build persists it as the
  authoritative ``seg_meta.segment_signature`` value; this phase defines and tests
  the contract.
* The external flat baseline identity ``global_pool:{backbone}:medoid`` is preserved
  by delegating to the existing observed-medoid selector
  (``pooling.select_global_medoid_index``) per backbone.  Nothing here reintroduces
  ``agg_method=medoid`` into primary scoring (that vocabulary is rejected at the
  ``strategy_binned._constants.validate_score_variant`` boundary and never used here).

This module never imports DuckDB, audio, ONNX, or CUDA; it consumes frozen stream
arrays (unit-normalised) exactly as ``StreamStore``/``HeadStreamStore`` deliver them.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass

import numpy as np

from scripts.embedding_research.helpers.binning import OUTLIER_WINDOW
from scripts.embedding_research.pooling import select_global_medoid_index

__all__ = [
    "MembershipSegment",
    "authoritative_segmentation",
    "global_flat_medoid_source_index",
    "segment_signature",
    "select_medoid_source_index",
    "validate_full_partition",
    "validate_segment_invariants",
]


def select_medoid_source_index(unit_patches: np.ndarray, candidate_indices: list[int] | tuple[int, ...]) -> int:
    """Return the observed segment-medoid source index among *candidate_indices*.

    *unit_patches* is the ``[n, D]`` unit-normalised source matrix.  The medoid is
    the observed row in *candidate_indices* with the maximum mean cosine centrality
    to the other candidates (mean INCLUDING self-similarity — exactly the historical
    PTC ``strategy_binned._pool.select_medoid_index`` metric).  Ties resolve to the
    smallest source index via ``np.argmax`` first-max semantics over the ascending
    candidate list.  *candidate_indices* must be non-empty and every index in range.
    Returns an OBSERVED source index — never a synthetic/median vector.
    """
    idx_arr = np.asarray(candidate_indices, dtype=int)
    if idx_arr.ndim != 1 or idx_arr.size == 0:
        raise ValueError("select_medoid_source_index requires a non-empty candidate index list")
    rows = np.asarray(unit_patches)[idx_arr].astype(np.float32, copy=False)
    if len(rows) <= 1:
        return int(idx_arr[0])
    sims = rows @ rows.T
    centrality = sims.mean(axis=1)
    local_idx = int(np.argmax(centrality))  # first-max => smallest source index on ties
    return int(idx_arr[local_idx])


def segment_signature(
    member_indices: tuple[int, ...],
    is_absorbed_outlier: tuple[bool, ...],
    medoid_source_patch_idx: int,
) -> str:
    """Deterministic sha256 over the segment's exact membership + observed medoid.

    The canonical pre-image is a fixed ordering of ``member_patch_idx:is_outlier``
    pairs (ascending by member index) terminated by the observed medoid source index,
    so two segments are signature-equal exactly when their membership (incl. outlier
    flags) and medoid source index are equal, and differ when any differ.  Phase 3's
    catalog build persists this as the authoritative ``seg_meta.segment_signature``
    value; this module defines and tests the contract.
    """
    if len(member_indices) != len(is_absorbed_outlier):
        raise ValueError("segment_signature requires parallel member/flag tuples")
    pairs = sorted(zip(member_indices, is_absorbed_outlier, strict=True), key=lambda pair: pair[0])
    body = ";".join(f"{int(i)}:{int(bool(flag))}" for i, flag in pairs)
    canonical = f"membership={body}|medoid_source_patch_idx={int(medoid_source_patch_idx)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MembershipSegment:
    """One segment's authoritative membership and structural/metadata summary.

    This is the pure object Phase 3 fans out into one ``seg_meta`` row and one
    ``seg_membership`` row per ``member_indices`` entry.

    Attributes
    ----------
    seg_id:
        Zero-based segment index within its song/config (Phase 3 persists it as the
        application segment identity within ``(config_id, song_id)``).
    member_indices:
        EVERY assigned source patch index of this segment, ascending, exactly once.
    is_absorbed_outlier:
        Parallel to ``member_indices`` — True for absorbed-outlier patches (present in
        membership/scoring/head-pooling but never a medoid candidate).
    start_idx / end_idx:
        Structural REPORT ranges only (first/last member index).  Membership is never
        reconstructed from them.
    medoid_source_patch_idx:
        Observed in-range member source index (never a copied/synthetic vector).
    segment_signature:
        Deterministic hash over membership + medoid (see :func:`segment_signature`).
    membership_version:
        Integer membership contract version (Phase 3 persists into seg_membership).
    """

    seg_id: int
    member_indices: tuple[int, ...]
    is_absorbed_outlier: tuple[bool, ...]
    start_idx: int
    end_idx: int
    medoid_source_patch_idx: int
    segment_signature: str
    membership_version: int

    @property
    def member_count(self) -> int:
        """Number of ``seg_membership`` rows (including absorbed outliers)."""
        return len(self.member_indices)

    @property
    def absorbed_outlier_count(self) -> int:
        """Number of absorbed-outlier member rows."""
        return sum(1 for flag in self.is_absorbed_outlier if flag)

    @property
    def weight(self) -> int:
        """Patch-count weight == member_count (including absorbed outliers)."""
        return self.member_count


def _build_segment(
    seg_id: int,
    in_range: list[int],
    absorbed: list[int],
    norm_patches: np.ndarray,
    membership_version: int,
) -> MembershipSegment:
    """Assemble one :class:`MembershipSegment` from its in-range + absorbed lists."""
    if not in_range:
        raise ValueError("internal error: an authoritative segment must have at least one in-range member")
    flags_by_idx: dict[int, bool] = {}
    for idx in in_range:
        flags_by_idx[int(idx)] = False
    for idx in absorbed:
        flags_by_idx[int(idx)] = True
    member_indices = tuple(sorted(flags_by_idx))
    is_absorbed_outlier = tuple(flags_by_idx[idx] for idx in member_indices)
    start_idx = int(member_indices[0])
    end_idx = int(member_indices[-1])
    in_range_idx = tuple(idx for idx in member_indices if not flags_by_idx[idx])
    medoid_source_patch_idx = select_medoid_source_index(norm_patches, list(in_range_idx))
    sig = segment_signature(member_indices, is_absorbed_outlier, medoid_source_patch_idx)
    return MembershipSegment(
        seg_id=seg_id,
        member_indices=member_indices,
        is_absorbed_outlier=is_absorbed_outlier,
        start_idx=start_idx,
        end_idx=end_idx,
        medoid_source_patch_idx=medoid_source_patch_idx,
        segment_signature=sig,
        membership_version=membership_version,
    )


def _run_running_centroid(
    norm_patches: np.ndarray,
    threshold: float,
    dist_fn,
    outlier_window: int,
) -> list[dict[str, list[int]]]:
    """Run the PTC running-centroid algorithm, tracking per-segment absorbed outliers.

    This mirrors :func:`helpers.binning.temporal_segment` EXACTLY (strict ``>``
    boundary, renormalized spherical running centroid, at most *outlier_window*
    consecutive boundary patches absorbed on a return, otherwise a hard split) but
    additionally records, per emitted segment, the source indices absorbed as
    outliers of that segment — information ``temporal_segment`` only counts.
    """
    n = len(norm_patches)
    if n == 0:
        return []

    def is_boundary(idx: int, centroid: np.ndarray) -> bool:
        return dist_fn(norm_patches[idx], centroid) > threshold

    def renorm(vec: np.ndarray) -> np.ndarray:
        mag = float(np.linalg.norm(vec))
        return vec / mag if mag > 1e-9 else vec

    out: list[dict[str, list[int]]] = []
    seg_in_range: list[int] = [0]
    seg_absorbed: list[int] = []
    centroid_sum: np.ndarray = norm_patches[0].copy()
    centroid = renorm(centroid_sum)

    i = 1
    while i < n:
        if not is_boundary(i, centroid):
            seg_in_range.append(i)
            centroid_sum = centroid_sum + norm_patches[i]
            centroid = renorm(centroid_sum)
            i += 1
            continue

        run: list[int] = [i]
        j = i + 1
        returned = False
        while j < n and len(run) <= outlier_window:
            if not is_boundary(j, centroid):
                seg_absorbed.extend(run)  # absorbed outliers belong to the OPEN segment
                seg_in_range.append(j)
                centroid_sum = centroid_sum + norm_patches[j]
                centroid = renorm(centroid_sum)
                i = j + 1
                returned = True
                break
            run.append(j)
            j += 1

        if not returned:
            out.append({"in_range": seg_in_range, "absorbed": seg_absorbed})
            seg_absorbed = []
            seg_in_range = run
            centroid_sum = norm_patches[run].sum(axis=0)
            centroid = renorm(centroid_sum)
            i = j

    if seg_in_range:
        out.append({"in_range": seg_in_range, "absorbed": seg_absorbed})

    return out


def authoritative_segmentation(
    norm_patches: np.ndarray,
    threshold: float,
    dist_fn,
    *,
    outlier_window: int = OUTLIER_WINDOW,
    membership_version: int = 1,
) -> tuple[MembershipSegment, ...]:
    """Segment a unit-normalised patch matrix into authoritative membership segments.

    Parameters mirror :func:`helpers.binning.temporal_segment` (``norm_patches`` must
    already be row L2-normalised; ``dist_fn`` is ``global_dist`` for ``temporal_global``
    or ``perdim_dist`` for ``temporal_perdim``).  Every source patch index is assigned
    to exactly one returned segment, either as an in-range member or (flagged) as an
    absorbed outlier, so membership is never reconstructed from the inclusive ranges.

    Returns an empty tuple for an empty matrix.  Deterministic and vector-free.
    """
    patches = np.asarray(norm_patches)
    if patches.ndim != 2:
        raise ValueError(f"norm_patches must be a 2-D [n, D] matrix; got shape {patches.shape}")
    raw_segments = _run_running_centroid(patches, float(threshold), dist_fn, int(outlier_window))
    return tuple(
        _build_segment(seg_id, seg["in_range"], seg["absorbed"], patches, int(membership_version))
        for seg_id, seg in enumerate(raw_segments)
    )


def validate_segment_invariants(segment: MembershipSegment) -> None:
    """Assert the exact seg_meta/seg_membership relationships for one segment.

    Raises :class:`ValueError` when: membership is empty / unsorted / has duplicates;
    flag list is not parallel; ``absorbed_outlier_count`` != flagged rows; ``weight``
    or ``member_count`` disagrees with the number of member rows; the medoid is not an
    observed member; the medoid is an absorbed outlier; or the structural range does
    not match the membership extent.
    """
    indices = segment.member_indices
    flags = segment.is_absorbed_outlier
    if len(indices) != len(flags):
        raise ValueError("member_indices and is_absorbed_outlier must be parallel")
    if not indices:
        raise ValueError("an authoritative segment cannot have empty membership")
    if any(int(a) >= int(b) for a, b in itertools.pairwise(indices)):
        raise ValueError("member_indices must be strictly ascending with no duplicates")
    absorbed_rows = sum(1 for flag in flags if flag)
    if absorbed_rows != segment.absorbed_outlier_count:
        raise ValueError("absorbed_outlier_count must equal the number of flagged absorbed-outlier rows")
    if len(indices) != segment.member_count:
        raise ValueError("member_count must equal the number of membership rows")
    if segment.weight != segment.member_count:
        raise ValueError("weight (patch-count) must equal member_count including absorbed outliers")
    if segment.member_count != absorbed_rows + sum(1 for flag in flags if not flag):
        raise ValueError("member_count must equal in-range members + absorbed outliers")
    if segment.medoid_source_patch_idx not in indices:
        raise ValueError("medoid_source_patch_idx must be an observed member source index")
    medoid_flag = dict(zip(indices, flags, strict=True))[segment.medoid_source_patch_idx]
    if medoid_flag:
        raise ValueError("an absorbed-outlier patch must never be the segment medoid")
    if segment.start_idx != indices[0] or segment.end_idx != indices[-1]:
        raise ValueError("structural start_idx/end_idx must equal the membership extent (report metadata only)")


def validate_full_partition(segments: tuple[MembershipSegment, ...], patch_count: int) -> None:
    """Assert every source patch index in ``[0, patch_count)`` is a member exactly once.

    Confirms the authoritative membership partitions the frozen stream, so no patch is
    dropped and none is double-assigned (the property scoring/head pooling rely on).
    """
    seen: list[int] = []
    for segment in segments:
        validate_segment_invariants(segment)
        seen.extend(int(i) for i in segment.member_indices)
    if len(seen) != patch_count or sorted(seen) != list(range(patch_count)):
        raise ValueError(
            f"authoritative membership must partition source indices [0, {patch_count}); "
            f"got {len(seen)} members across {len(segments)} segments"
        )


def global_flat_medoid_source_index(unit_patches: np.ndarray) -> int:
    """Observed global flat-baseline medoid source index for one backbone's song.

    Delegates to the existing observed-medoid selector (``pooling.select_global_medoid_index``)
    so the external identity ``global_pool:{backbone}:medoid`` is preserved exactly
    (observed row, off-diagonal mean-cosine centrality, smallest-index ties).  Returns an
    index only — no vector artifact.  Computed independently per backbone because each
    call receives one backbone's patch matrix.  This baseline is never produced through
    ``agg_method=medoid`` (that vocabulary is rejected at the score-variant boundary).
    """
    idx, _ = select_global_medoid_index(np.asarray(unit_patches))
    return int(idx)
