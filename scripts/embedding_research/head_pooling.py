"""LEGACY INTERIM inclusive-range shared-boundary head pooling (retirement pending).

.. warning::
   LEGACY INTERIM (Plan E, Phase 1 D1).  The ACTIVE head-analysis surface now
   lives in ``common/head_analysis.py`` with exact ``seg_membership`` semantics;
   this module is retained ONLY as an inclusive-range compatibility surface so the
   legacy live-ONNX runner (``classify.run_shared_ptc_head_pooling``) and legacy
   ``run.py`` glue stay callable through Phase 4.  It is read-only w.r.t. canonical
   persistence: it never calls the canonical CPU runner/persistence and never
   writes a canonical current row.  Plan E Phase 4 retires this surface.

Legacy contract (superseded)
-----------------------------
The legacy runner pools classifier head outputs over the *already-produced* EffNet
PTC inclusive bin boundaries (``bin_start_idx`` / ``bin_end_idx`` plus per-bin
patch-count ``weights``) without ever running head-specific segmentation and
without consuming CTP boundaries.  These inclusive ranges do NOT define canonical
head membership (exact membership comes from ``seg_membership``).

Legacy data models
------------------
* :class:`HeadBoundaryPoolResult` — per-bin pooled head-output vectors,
  class-1 values (always from ``act[1]``, never ``act[0]``), preserved
  per-bin patch-count weights, validated inclusive boundary arrays, and
  finite boundary provenance (``boundary_source="effnet_ptc"``).
* :class:`HeadPhaseConfigRecord` / :class:`HeadPhaseManifest` — the
  non-blocking legacy orchestration manifest produced by
  ``classify.run_shared_ptc_head_pooling`` (which imports them from here).

The pooling helper never runs segmentation and never creates head-specific
bins: the boundaries are consumed exactly as produced by EffNet PTC.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "BOUNDARY_SOURCE_EFFNET_PTC",
    "HEAD_POOL_VARIANT",
    "HeadBoundaryPoolResult",
    "HeadPhaseConfigRecord",
    "HeadPhaseManifest",
    "pool_head_outputs_over_ptc_boundaries",
]

#: The only boundary source this phase may consume.  CTP boundaries are never
#: accepted or produced.
BOUNDARY_SOURCE_EFFNET_PTC = "effnet_ptc"

#: The single explicit label for the shared-boundary head pooling variant.  It is
#: part of the head-phase configuration identity (see ``db.head_phase``) and is
#: deliberately disjoint from any hypothetical head-specific segmentation variant:
#: this phase pools over the *already-produced* EffNet PTC boundaries and never
#: creates head-specific bins.
HEAD_POOL_VARIANT = "shared_effnet_ptc_boundary"

#: Class-1 lives at index 1 of the head-activation vector; ``act[0]`` is never
#: the class-1 value.
_CLASS1_INDEX = 1


@dataclass(frozen=True)
class HeadBoundaryPoolResult:
    """Pooled head outputs over inclusive EffNet PTC bin boundaries.

    ``acts[i]`` is the mean head-activation vector over the inclusive patch
    range ``[bin_start_idx[i], bin_end_idx[i]]``.  ``class1[i]`` is the class-1
    value taken from ``acts[i][_CLASS1_INDEX]`` (the mean of ``act[1]`` over
    the bin) — never ``act[0]``.  ``weights`` preserves the per-bin patch
    counts exactly.  ``finite`` is True only when every emitted numeric value
    is finite.
    """

    acts: np.ndarray
    class1: np.ndarray
    weights: np.ndarray
    bin_start_idx: np.ndarray
    bin_end_idx: np.ndarray
    finite: bool
    boundary_source: str = BOUNDARY_SOURCE_EFFNET_PTC

    def to_dict(self) -> dict[str, Any]:
        return {
            "acts": self.acts.tolist(),
            "class1": [float(v) for v in self.class1],
            "weights": [int(w) for w in self.weights],
            "bin_start_idx": [int(s) for s in self.bin_start_idx],
            "bin_end_idx": [int(e) for e in self.bin_end_idx],
            "finite": bool(self.finite),
            "boundary_source": self.boundary_source,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


def pool_head_outputs_over_ptc_boundaries(
    acts: np.ndarray,
    bin_start_idx: np.ndarray,
    bin_end_idx: np.ndarray,
    weights: np.ndarray,
) -> HeadBoundaryPoolResult:
    """Pool head outputs over inclusive EffNet PTC bin boundaries (pure).

    Parameters
    ----------
    acts:
        ``[n_patches, C] float32`` — per-patch head activations for one song.
    bin_start_idx, bin_end_idx:
        ``[n_bins] int32`` — inclusive first/last patch index of each bin, as
        produced by EffNet PTC segmentation.  Both arrays must be co-indexed
        (same length) and every range must be valid: ``0 <= start <= end <
        n_patches``.
    weights:
        ``[n_bins] int32`` — per-bin temporal patch counts, co-indexed with
        the boundary arrays and strictly positive (patch counts are never
        zero).

    Returns
    -------
    :class:`HeadBoundaryPoolResult` with, per bin, the mean head-output vector
    over the inclusive range, the class-1 value from ``act[1]`` (the mean of
    column 1; never ``act[0]``), the preserved weights, the validated boundary
    arrays, and ``finite`` boundary provenance.

    Raises
    ------
    ValueError
        On malformed input: wrong dimensions, non-finite activations, non
        co-indexed or non-1-D boundary/weight arrays, negative or inverted or
        out-of-range boundaries, or non-positive weights.

    This helper never runs segmentation and never creates head-specific bins:
    the boundaries are used exactly as given.
    """
    acts_f = np.asarray(acts, dtype=np.float32)
    start = np.asarray(bin_start_idx, dtype=np.int32)
    end = np.asarray(bin_end_idx, dtype=np.int32)
    wts = np.asarray(weights, dtype=np.int32)

    if acts_f.ndim != 2:
        raise ValueError(f"acts must be 2-D [n_patches, n_classes], got ndim={acts_f.ndim}")
    if acts_f.shape[0] == 0:
        raise ValueError("acts must have at least one patch row")
    n_patches = int(acts_f.shape[0])

    if start.ndim != 1 or end.ndim != 1 or wts.ndim != 1:
        raise ValueError("bin_start_idx, bin_end_idx, and weights must all be 1-D")
    n_bins = int(start.shape[0])
    if end.shape[0] != n_bins:
        raise ValueError(
            f"bin_start_idx and bin_end_idx must be co-indexed: start has {n_bins} entries, end has {end.shape[0]}"
        )
    if wts.shape[0] != n_bins:
        raise ValueError(
            f"weights must be co-indexed with the boundary arrays: {wts.shape[0]} weights for {n_bins} bins"
        )
    if not np.all(np.isfinite(acts_f)):
        raise ValueError("acts must be finite (no NaN/Inf)")

    for i in range(n_bins):
        s, e = int(start[i]), int(end[i])
        if s < 0 or e < 0:
            raise ValueError(f"bin {i}: negative boundary index start={s} end={e}")
        if s > e:
            raise ValueError(f"bin {i}: start index {s} exceeds end index {e}")
        if e >= n_patches:
            raise ValueError(f"bin {i}: end index {e} out of range (n_patches={n_patches})")
        if int(wts[i]) <= 0:
            raise ValueError(f"bin {i}: patch-count weight must be strictly positive, got {int(wts[i])}")

    # Per-bin mean head-output vector over the inclusive range (no segmentation,
    # no head-specific bins — boundaries used exactly as produced).
    pooled = np.zeros((n_bins, acts_f.shape[1]), dtype=np.float32)
    for i in range(n_bins):
        s, e = int(start[i]), int(end[i])
        pooled[i] = acts_f[s : e + 1].mean(axis=0)

    # Class-1 values from act[1] (index 1) — never act[0].
    class1 = pooled[:, _CLASS1_INDEX].astype(np.float32)
    finite = bool(np.all(np.isfinite(pooled)) and np.all(np.isfinite(class1)))

    return HeadBoundaryPoolResult(
        acts=pooled,
        class1=class1,
        weights=wts.copy(),
        bin_start_idx=start.copy(),
        bin_end_idx=end.copy(),
        finite=finite,
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
    )


@dataclass(frozen=True)
class HeadPhaseConfigRecord:
    """One auditable per-configuration outcome of the shared-boundary phase.

    ``status`` is one of ``"done"`` (at least one song pooled and saved),
    ``"skipped"`` (attempted but nothing pooled — already cached, missing
    patches/boundaries, or head model/session unavailable), or ``"error"``
    (boundary validation failed for a song).  ``reason`` records the skip /
    error explanation for the report/manifest.
    """

    backbone: str
    head: str
    bin_mode: str
    threshold: float
    status: str
    reason: str
    n_songs: int
    n_pooled: int
    finite: bool
    boundary_source: str = BOUNDARY_SOURCE_EFFNET_PTC

    def to_dict(self) -> dict[str, Any]:
        return {
            "backbone": self.backbone,
            "head": self.head,
            "bin_mode": self.bin_mode,
            "threshold": float(self.threshold),
            "status": self.status,
            "reason": self.reason,
            "n_songs": int(self.n_songs),
            "n_pooled": int(self.n_pooled),
            "finite": bool(self.finite),
            "boundary_source": self.boundary_source,
        }


@dataclass(frozen=True)
class HeadPhaseManifest:
    """JSON-safe, deterministic manifest of a shared-boundary head phase run.

    Records the requested dimensions (sorted), the per-configuration
    outcomes, and every skip/error reason.  ``primary_analysis_succeeded`` is
    always True: this optional phase is non-blocking and never mutates the
    primary corpus or primary winner grid, so primary EffNet PTC-vs-medoid
    analysis completes regardless of whether head models or head caches are
    present.
    """

    boundary_source: str
    backbones: tuple[str, ...]
    heads: tuple[str, ...]
    bin_modes: tuple[str, ...]
    thresholds: tuple[float, ...]
    song_ids: tuple[str, ...]
    scoring_semantics_version: int
    results: tuple[HeadPhaseConfigRecord, ...]
    skip_reasons: tuple[tuple[str, str], ...]
    done: int
    skipped: int
    errors: int
    finite: bool
    primary_analysis_succeeded: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary_source": self.boundary_source,
            "backbones": list(self.backbones),
            "heads": list(self.heads),
            "bin_modes": list(self.bin_modes),
            "thresholds": [float(t) for t in self.thresholds],
            "song_ids": list(self.song_ids),
            "scoring_semantics_version": int(self.scoring_semantics_version),
            "results": [r.to_dict() for r in self.results],
            "skip_reasons": [[str(scope), str(reason)] for scope, reason in self.skip_reasons],
            "done": int(self.done),
            "skipped": int(self.skipped),
            "errors": int(self.errors),
            "finite": bool(self.finite),
            "primary_analysis_succeeded": bool(self.primary_analysis_succeeded),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)
