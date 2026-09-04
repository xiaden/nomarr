"""Canonical CPU shared-boundary head analysis (Plan E, Phase 1) — the ACTIVE home.

This module is the sole **active** home for the CPU head-analysis surface: the
boundary/variant constants, the per-segment/head value object
(:class:`HeadBoundaryPoolResult`), the pure exact-membership pooling helper
(:func:`pool_head_outputs_over_ptc_boundaries`), the per-configuration record
(:class:`HeadPhaseConfigRecord`) and the orchestration manifest
(:class:`HeadPhaseManifest`).

Design rules (DD R4/R5/R13 + the Plan E Phase 1 contract):
* Head membership is defined **only** by the authoritative ``seg_membership``
  relation (exact observed ``member_patch_idx`` rows, including absorbed
  outliers).  Inclusive ``seg_meta.start_idx/end_idx`` are structural report
  ranges only and are never accepted or inspected here.
* The operation is **CPU-only and derived**: it consumes frozen ready head
  streams and catalog scalar rows only.  It never discovers audio, loads models,
  runs ONNX/CUDA/sklearn, invokes segmentation or CTP, reads artifact paths, or
  infers membership.
* Pooled values are **transient** on-demand search-view values: they are never
  persisted as vectors/cache files or copied medoids.  The only durable
  head-analysis sink is non-blocking coverage/skip provenance in
  ``head_phase_provenance``.
* ``act[1]`` is the class-1 probability (never ``act[0]``).  Every emitted
  numeric value is finite and JSON-safe.  No new PK/UNIQUE/index is introduced.

The canonical CPU runner (``run_shared_ptc_head_pooling``) and the named-column
persistence migration live alongside this pure surface in the same active
change; the legacy live-ONNX cache/range runner (``classify.run_shared_ptc_head_pooling``)
and the top-level ``head_pooling.py`` legacy surface remain only as interim
migration infrastructure until the Plan E CLI rewrite (Phase 4).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from scripts.embedding_research.helpers.thresholds import (
    canonical_float as _canonical_float,
)
from scripts.embedding_research.helpers.thresholds import (
    canonical_semantics as _canonical_semantics,
)

__all__ = [
    "BOUNDARY_SOURCE_EFFNET_PTC",
    "HEAD_POOL_VARIANT",
    "PTC_BIN_MODES",
    "PTC_SEMANTICS",
    "HeadBoundaryPoolResult",
    "HeadPhaseConfigRecord",
    "HeadPhaseManifest",
    "pool_head_outputs_over_ptc_boundaries",
    "run_shared_ptc_head_pooling",
]

#: The only boundary source this phase may consume.  CTP boundaries are never
#: accepted or produced, and no head-specific-segmentation boundary exists.
BOUNDARY_SOURCE_EFFNET_PTC = "effnet_ptc"

#: The single explicit label for the shared-boundary head-pooling variant.  It is
#: part of the head-phase configuration identity and is deliberately disjoint from
#: any hypothetical head-specific-segmentation variant: this phase pools over the
#: *already-produced* EffNet PTC boundaries (exact membership) and never creates
#: head-specific bins.
HEAD_POOL_VARIANT = "shared_effnet_ptc_boundary"

#: Canonical EffNet PTC ``seg_config`` ``bin_mode`` values eligible for the shared
#: CPU head analysis (``temporal_global`` / ``temporal_perdim`` running-centroid
#: PTC tracks).  Other bin modes are never selected.
PTC_BIN_MODES: frozenset[str] = frozenset({"temporal_global", "temporal_perdim"})

#: Canonical threshold-semantics labels eligible for the shared CPU head analysis
#: (``direct_l2`` is the new default; ``std_scaled`` is explicit legacy-fidelity).
PTC_SEMANTICS: frozenset[str] = frozenset({"direct_l2", "std_scaled"})

#: Class-1 lives at index 1 of the head-activation vector; ``act[0]`` is never
#: the class-1 value.
_CLASS1_INDEX = 1

#: Per-configuration head-phase status vocabulary (mirrors the persistence row).
_HEAD_PHASE_STATUSES: frozenset[str] = frozenset({"done", "skipped", "error"})


# --------------------------------------------------------------------------- #
# Pure exact-membership value object + pooling helper (P1-S1)                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HeadBoundaryPoolResult:
    """One transient pooled head value for one exact segment/head membership.

    ``acts`` is the float32 ``[C]`` mean head-activation vector over the exact
    observed member rows (row ``i`` is the activation of source patch
    ``member_patch_indices[i]``).  ``class1`` is the scalar class-1 value taken
    from ``acts[_CLASS1_INDEX]`` (the mean of ``act[1]`` over the members) —
    never ``act[0]``.  ``weight`` is the integer patch weight (equal to the
    number of exact members, absorbed outliers included).  ``member_patch_indices``
    and ``is_absorbed_outlier`` are the co-indexed exact observed membership.
    ``finite`` is True only when every emitted numeric value is finite.
    ``boundary_source`` is fixed.
    """

    acts: np.ndarray
    class1: float
    weight: int
    member_patch_indices: tuple[int, ...]
    is_absorbed_outlier: tuple[bool, ...]
    segment_id: int
    finite: bool
    boundary_source: str = BOUNDARY_SOURCE_EFFNET_PTC

    def __post_init__(self) -> None:
        if self.boundary_source != BOUNDARY_SOURCE_EFFNET_PTC:
            raise ValueError(
                f"HeadBoundaryPoolResult boundary_source must be "
                f"{BOUNDARY_SOURCE_EFFNET_PTC!r}; got {self.boundary_source!r} (CTP never used)"
            )
        acts = np.asarray(self.acts, dtype=np.float32)
        if acts.ndim != 1:
            raise ValueError(f"pooled acts must be 1-D [C]; got ndim={acts.ndim}")
        object.__setattr__(self, "acts", acts)
        if len(acts) < 1:
            raise ValueError("pooled acts must have at least one class column")
        if not np.all(np.isfinite(acts)):
            raise ValueError("pooled acts must be finite (no NaN/Inf)")
        if not math.isfinite(float(self.class1)):
            raise ValueError("class1 must be finite")
        object.__setattr__(self, "class1", float(self.class1))
        if isinstance(self.weight, bool) or not isinstance(self.weight, int) or self.weight < 1:
            raise ValueError(f"weight must be a positive integer; got {self.weight!r}")
        if isinstance(self.segment_id, bool) or not isinstance(self.segment_id, int) or self.segment_id < 0:
            raise ValueError(f"segment_id must be a non-negative integer; got {self.segment_id!r}")
        member_len = len(self.member_patch_indices)
        if member_len == 0:
            raise ValueError("member_patch_indices must not be empty")
        if member_len != int(self.weight):
            raise ValueError(
                f"weight ({self.weight}) must equal the number of exact member rows "
                f"({member_len}) including absorbed outliers"
            )
        if len(self.is_absorbed_outlier) != member_len:
            raise ValueError(
                f"is_absorbed_outlier must be co-indexed with member_patch_indices: "
                f"{len(self.is_absorbed_outlier)} flags for {member_len} members"
            )
        if not all(isinstance(f, bool) for f in self.is_absorbed_outlier):
            raise ValueError("is_absorbed_outlier entries must be bool")
        if not all(isinstance(i, bool) or (isinstance(i, int) and i >= 0) for i in self.member_patch_indices):
            raise ValueError("member_patch_indices must be non-negative integers")
        if len(set(self.member_patch_indices)) != member_len:
            raise ValueError("member_patch_indices must be unique observed source indices")

    def to_dict(self) -> dict[str, Any]:
        return {
            "acts": [float(v) for v in self.acts],
            "class1": float(self.class1),
            "weight": int(self.weight),
            "member_patch_indices": [int(i) for i in self.member_patch_indices],
            "is_absorbed_outlier": [bool(f) for f in self.is_absorbed_outlier],
            "segment_id": int(self.segment_id),
            "finite": bool(self.finite),
            "boundary_source": self.boundary_source,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


def pool_head_outputs_over_ptc_boundaries(
    acts: np.ndarray,
    member_patch_indices: Any,
    *,
    segment_id: int,
    weight: int,
    is_absorbed_outlier: Any,
) -> HeadBoundaryPoolResult:
    """Pool head outputs over one exact PTC-boundary membership (pure).

    ``acts`` must already be gathered **in the exact ``seg_membership`` order**:
    finite float32 ``[N, C]`` where row ``i`` is the activation of source patch
    ``member_patch_indices[i]`` (absorbed outliers included).  The helper pools
    exactly those rows and never inspects ``start_idx/end_idx``, never infers
    membership, and performs no IO/audio/model/ONNX/CUDA/segmentation/CTP.

    Parameters
    ----------
    acts:
        ``[N, C] float32`` — the already-gathered exact member rows for one
        segment (finite, at least one row).
    member_patch_indices:
        Length-``N`` observed, non-negative, unique source patch indices,
        co-indexed with the rows of ``acts``.
    segment_id:
        Non-negative integer segment identity.
    weight:
        Positive integer patch weight; must equal ``N`` (including absorbed
        outliers).
    is_absorbed_outlier:
        Length-``N`` bool flags co-indexed with ``member_patch_indices``.

    Returns
    -------
    :class:`HeadBoundaryPoolResult` with the float32 ``[C]`` mean activation,
    scalar class-1 from ``act[1]`` (never ``act[0]``), the integer weight, the
    exact source-index and outlier-flag tuples, the segment id, and ``finite``
    provenance.

    Raises
    ------
    ValueError
        On malformed input: non-finite / wrong-rank / empty acts, non-co-indexed
        or non-unique or negative membership indices, flag/weight mismatch, or a
        non-integer segment id.
    """
    acts_f = np.asarray(acts, dtype=np.float32)
    if acts_f.ndim != 2:
        raise ValueError(f"acts must be 2-D [N, C]; got ndim={acts_f.ndim}")
    n_rows = int(acts_f.shape[0])
    if n_rows == 0:
        raise ValueError("acts must contain at least one exact member row")
    if acts_f.shape[1] < 1:
        raise ValueError("acts must have at least one class column")
    if not np.all(np.isfinite(acts_f)):
        raise ValueError("acts must be finite (no NaN/Inf)")

    member_ids = tuple(int(i) for i in member_patch_indices)
    if len(member_ids) != n_rows:
        raise ValueError(
            f"member_patch_indices must be co-indexed with the gathered rows: "
            f"{len(member_ids)} indices for {n_rows} rows"
        )
    if not all(i >= 0 for i in member_ids):
        raise ValueError("member_patch_indices must be non-negative observed source indices")
    if len(set(member_ids)) != n_rows:
        raise ValueError("member_patch_indices must be unique observed source indices")

    flags = tuple(bool(f) for f in is_absorbed_outlier)
    if len(flags) != n_rows:
        raise ValueError(
            f"is_absorbed_outlier must be co-indexed with member_patch_indices: {len(flags)} flags for {n_rows} members"
        )
    if isinstance(weight, bool) or not isinstance(weight, int) or weight != n_rows:
        raise ValueError(
            f"weight ({weight!r}) must equal the number of exact member rows ({n_rows}) including absorbed outliers"
        )
    if isinstance(segment_id, bool) or not isinstance(segment_id, int) or segment_id < 0:
        raise ValueError(f"segment_id must be a non-negative integer; got {segment_id!r}")

    # Mean over the exact gathered member rows -> one pooled vector per segment.
    pooled = acts_f.mean(axis=0).astype(np.float32)
    class1 = float(pooled[_CLASS1_INDEX])  # act[1], never act[0]
    finite = bool(np.all(np.isfinite(pooled)) and math.isfinite(class1))

    return HeadBoundaryPoolResult(
        acts=pooled,
        class1=class1,
        weight=int(weight),
        member_patch_indices=member_ids,
        is_absorbed_outlier=flags,
        segment_id=int(segment_id),
        finite=finite,
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
    )


# --------------------------------------------------------------------------- #
# Per-configuration outcome + orchestration manifest (P1-S3)                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HeadPhaseConfigRecord:
    """One auditable per-(config, head) outcome of the shared-boundary phase.

    ``config_id`` is the application identity of the selected canonical
    ``seg_config`` the head output was pooled over; ``threshold_configured`` /
    ``threshold_effective`` / ``semantics`` carry that config's resolved
    threshold identity.  ``status`` is one of ``"done"`` (at least one song
    pooled), ``"skipped"`` (attempted but nothing pooled), or ``"error"`` (a
    song's membership/pooling failed validation).  ``reason`` records the
    skip/error explanation for the report/manifest.
    """

    config_id: int
    backbone: str
    head: str
    bin_mode: str
    threshold_configured: float
    threshold_effective: float
    semantics: str
    status: str
    reason: str
    n_songs: int
    n_pooled: int
    finite: bool
    boundary_source: str = BOUNDARY_SOURCE_EFFNET_PTC
    head_pool_variant: str = HEAD_POOL_VARIANT

    def __post_init__(self) -> None:
        if self.boundary_source != BOUNDARY_SOURCE_EFFNET_PTC:
            raise ValueError(
                f"head-phase config record boundary_source must be "
                f"{BOUNDARY_SOURCE_EFFNET_PTC!r}; got {self.boundary_source!r} (CTP never used)"
            )
        if self.head_pool_variant != HEAD_POOL_VARIANT:
            raise ValueError(
                f"head-phase config record head_pool_variant must be {HEAD_POOL_VARIANT!r}; "
                f"got {self.head_pool_variant!r} (head-specific segmentation is not a shared-boundary row)"
            )
        if self.status not in _HEAD_PHASE_STATUSES:
            raise ValueError(
                f"head-phase config record status must be one of {sorted(_HEAD_PHASE_STATUSES)}; got {self.status!r}"
            )
        _canonical_semantics(self.semantics)
        object.__setattr__(self, "threshold_configured", float(_canonical_float(self.threshold_configured)))
        object.__setattr__(self, "threshold_effective", float(_canonical_float(self.threshold_effective)))
        if isinstance(self.config_id, bool) or not isinstance(self.config_id, int) or self.config_id < 0:
            raise ValueError(f"config_id must be a non-negative integer; got {self.config_id!r}")
        if isinstance(self.n_songs, bool) or not isinstance(self.n_songs, int) or self.n_songs < 0:
            raise ValueError("n_songs must be a non-negative integer")
        if isinstance(self.n_pooled, bool) or not isinstance(self.n_pooled, int) or self.n_pooled < 0:
            raise ValueError("n_pooled must be a non-negative integer")
        if self.n_pooled > self.n_songs:
            raise ValueError(f"n_pooled ({self.n_pooled}) cannot exceed n_songs ({self.n_songs})")

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": int(self.config_id),
            "backbone": self.backbone,
            "head": self.head,
            "bin_mode": self.bin_mode,
            "threshold_configured": float(self.threshold_configured),
            "threshold_effective": float(self.threshold_effective),
            "semantics": self.semantics,
            "status": self.status,
            "reason": self.reason,
            "n_songs": int(self.n_songs),
            "n_pooled": int(self.n_pooled),
            "finite": bool(self.finite),
            "boundary_source": self.boundary_source,
            "head_pool_variant": self.head_pool_variant,
        }


@dataclass(frozen=True)
class HeadPhaseManifest:
    """JSON-safe, deterministic manifest of a canonical shared-boundary head run.

    Records the ``run_id``, the selected canonical ``config_ids``, the sorted
    head dimensions observed, the per-(config, head) outcomes, and every
    skip/error reason.  ``primary_analysis_succeeded`` is always True: this
    optional phase is non-blocking and never mutates the primary corpus/winner
    rows.
    """

    run_id: str
    config_ids: tuple[int, ...]
    dimensions: tuple[int, ...]
    boundary_source: str
    head_pool_variant: str
    backbones: tuple[str, ...]
    heads: tuple[str, ...]
    bin_modes: tuple[str, ...]
    song_ids: tuple[str, ...]
    scoring_semantics_version: int
    results: tuple[HeadPhaseConfigRecord, ...]
    skip_reasons: tuple[tuple[str, str], ...]
    done: int
    skipped: int
    errors: int
    finite: bool
    reference_corpus_hash: str | None = None
    primary_analysis_succeeded: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_ids": [int(c) for c in self.config_ids],
            "dimensions": [int(d) for d in self.dimensions],
            "boundary_source": self.boundary_source,
            "head_pool_variant": self.head_pool_variant,
            "backbones": list(self.backbones),
            "heads": list(self.heads),
            "bin_modes": list(self.bin_modes),
            "song_ids": list(self.song_ids),
            "scoring_semantics_version": int(self.scoring_semantics_version),
            "results": [r.to_dict() for r in self.results],
            "skip_reasons": [[str(scope), str(reason)] for scope, reason in self.skip_reasons],
            "done": int(self.done),
            "skipped": int(self.skipped),
            "errors": int(self.errors),
            "finite": bool(self.finite),
            "reference_corpus_hash": self.reference_corpus_hash,
            "primary_analysis_succeeded": bool(self.primary_analysis_succeeded),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


# --------------------------------------------------------------------------- #
# Canonical CPU runner (P1-S2)                                                 #
# --------------------------------------------------------------------------- #


def _collect_segment_membership(con, config_id: int, song_id: str, membership_fn, segments_fn):
    """Yield exact per-segment membership for one (config, song).

    Yields ``(seg_id, member_indices, outlier_flags, weight)`` in ascending seg_id
    order, using the catalog ``seg_membership`` relation as the ONLY membership
    source (``seg_meta.start_idx/end_idx`` are never consulted).
    """
    segs = segments_fn(con, config_id, song_id)
    for seg in segs:
        members = membership_fn(con, config_id, song_id, seg.seg_id)
        if not members:
            continue
        indices = tuple(int(m.member_patch_idx) for m in members)
        flags = tuple(bool(m.is_absorbed_outlier) for m in members)
        yield seg.seg_id, indices, flags, len(indices)


def run_shared_ptc_head_pooling(
    con,
    head_store: Any,
    *,
    config_ids: Any = None,
    song_ids: Any = None,
    heads: Any = None,
    run_id: str,
    reference_corpus_hash: str | None = None,
    force: bool = False,  # noqa: ARG001 - interface-parity flag; this derived read is always recomputed
) -> HeadPhaseManifest:
    """Canonical CPU shared-boundary head analysis (ACTIVE — Plan E Phase 1).

    Deterministic, CPU-only and non-blocking.  Selects canonical EffNet PTC
    ``seg_config`` rows (or the caller-supplied ``config_ids``), gathers the exact
    observed ``seg_membership`` rows of each song once per (config, song) through
    ``HeadStreamStore.batch_gather`` (all heads in canonical sorted-column order),
    slices per head using the registry ``dim_by_head``, and pools each segment via
    :func:`pool_head_outputs_over_ptc_boundaries` (exact membership; never
    ``start_idx/end_idx``).  It performs no audio/model/ONNX/CUDA/sklearn/CTP work
    and persists no pooled vector/cache/medoid artifact.  The durable sink is
    non-blocking coverage/skip provenance (the caller writes canonical rows).

    ``force`` is accepted for interface parity; this derived read is always
    recomputed against the frozen streams/catalog (nothing is cached).
    """
    from scripts.embedding_research.cache_identity import SCORING_SEMANTICS_VERSION as _SCV
    from scripts.embedding_research.catalog import (
        configs_by_backbone as _configs_by_backbone,
    )
    from scripts.embedding_research.catalog import (
        membership_by_config_song_seg as _membership_fn,
    )
    from scripts.embedding_research.catalog import (
        segments_by_config_song as _segments_fn,
    )
    from scripts.embedding_research.helpers.thresholds import PTC_STRATEGY_VERSION as _PTC_V
    from scripts.embedding_research.streams.records import (
        parse_dim_by_head as _parse_dim,
    )
    from scripts.embedding_research.streams.records import (
        parse_head_ids as _parse_head_ids,
    )

    effnet_configs = tuple(sorted(_configs_by_backbone(con, "effnet"), key=lambda c: c.config_id))

    def _eligible(cfg) -> bool:
        return (
            cfg.alias_of_config_id is None
            and cfg.semantics in PTC_SEMANTICS
            and cfg.bin_mode in PTC_BIN_MODES
            and cfg.strategy_version == _PTC_V
        )

    requested = {int(c) for c in config_ids} if config_ids is not None else None
    if requested is None:
        selected = [c for c in effnet_configs if _eligible(c)]
        skip_reasons: list[tuple[str, str]] = []
    else:
        by_id = {c.config_id: c for c in effnet_configs}
        selected = []
        skip_reasons = []
        for cid in sorted(requested):
            cfg = by_id.get(cid)
            if cfg is None:
                skip_reasons.append((f"config:{cid}", "no seg_config row for requested config_id"))
            elif not _eligible(cfg):
                skip_reasons.append(
                    (f"config:{cid}", "config not eligible for canonical shared-boundary head analysis")
                )
            else:
                selected.append(cfg)

    explicit_heads: frozenset[str] | None = frozenset(str(h) for h in heads) if heads is not None else None

    # key -> [n_attempted_songs, n_pooled_songs, any_error, all_finite, reason]
    agg: dict[tuple[int, str], list] = {}
    processed_song_ids: set[str] = set()
    discovered_dimensions: set[int] = set()
    active_heads: set[str] = set()

    for cfg in selected:
        if song_ids is not None:
            songs = sorted(str(s) for s in song_ids)
        else:
            songs = sorted(
                str(r[0])
                for r in con.execute(
                    "SELECT DISTINCT song_id FROM seg_meta WHERE config_id = ?", [cfg.config_id]
                ).fetchall()
            )
        for song in songs:
            segs = list(
                _collect_segment_membership(
                    con, cfg.config_id, song, membership_fn=_membership_fn, segments_fn=_segments_fn
                )
            )
            if not segs:
                continue
            try:
                record = head_store.lookup(song, cfg.backbone)
            except Exception:
                continue
            rec_heads = _parse_head_ids(record.head_ids)
            if explicit_heads is not None:
                rec_heads = tuple(h for h in rec_heads if h in explicit_heads)
            if not rec_heads:
                continue
            dims = _parse_dim(record.dim_by_head)
            offsets: dict[str, tuple[int, int]] = {}
            col = 0
            for h in _parse_head_ids(record.head_ids):
                d = int(dims.get(h, 0))
                if d > 0 and h in rec_heads:
                    offsets[h] = (col, col + d)
                col += d
            union: list[int] = []
            for _seg_id, indices, _flags, _w in segs:
                union.extend(indices)
            try:
                gathered = head_store.batch_gather(song, cfg.backbone, union)
            except Exception:
                continue
            for head in rec_heads:
                if head not in offsets:
                    continue
                start, end = offsets[head]
                key = (cfg.config_id, head)
                entry = agg.setdefault(key, [0, 0, False, True, ""])
                entry[0] += 1
                processed_song_ids.add(song)
                active_heads.add(head)
                head_pooled = False
                head_finite = True
                row_cursor = 0
                for _seg_id, indices, flags, weight in segs:
                    n_members = len(indices)
                    rows = gathered[row_cursor : row_cursor + n_members, start:end]
                    row_cursor += n_members
                    try:
                        result = pool_head_outputs_over_ptc_boundaries(
                            rows,
                            indices,
                            segment_id=_seg_id,
                            weight=weight,
                            is_absorbed_outlier=flags,
                        )
                    except ValueError as exc:
                        entry[2] = True
                        entry[4] = f"membership/pooling validation failed for song {song}: {exc}"
                        break
                    if result.finite:
                        head_pooled = True
                    else:
                        head_finite = False
                    discovered_dimensions.add(len(result.acts))
                if not entry[2]:
                    if head_pooled:
                        entry[1] += 1
                    entry[3] = entry[3] and head_finite

    results: list[HeadPhaseConfigRecord] = []
    done = 0
    skipped = 0
    errors = 0
    finite_overall = True
    for (config_id, head), (n_songs, n_pooled, any_err, all_finite, reason) in sorted(agg.items()):
        cfg = next((c for c in selected if c.config_id == config_id), None)
        if cfg is None:
            continue
        if any_err:
            status = "error"
            errors += 1
        elif n_pooled > 0:
            status = "done"
            done += 1
        else:
            status = "skipped"
            skipped += 1
            if not reason:
                reason = "no song produced a finite pooled head value"
        finite_overall = finite_overall and bool(all_finite and not any_err)
        results.append(
            HeadPhaseConfigRecord(
                config_id=config_id,
                backbone=cfg.backbone,
                head=head,
                bin_mode=cfg.bin_mode,
                threshold_configured=float(cfg.threshold_configured),
                threshold_effective=float(cfg.threshold_effective),
                semantics=cfg.semantics,
                status=status,
                reason=reason,
                n_songs=int(n_songs),
                n_pooled=int(n_pooled),
                finite=bool(all_finite and not any_err),
                boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
                head_pool_variant=HEAD_POOL_VARIANT,
            )
        )

    config_ids_used = tuple(sorted({r.config_id for r in results}))
    dimensions = tuple(sorted(discovered_dimensions))
    song_tuple = tuple(sorted(processed_song_ids))
    active_head_tuple = tuple(sorted(active_heads))
    bin_modes = tuple(sorted({r.bin_mode for r in results}))
    skip_reasons.extend(
        (f"config:{cfg.config_id}", "config has no pooled head output")
        for cfg in selected
        if cfg.config_id not in config_ids_used
    )
    return HeadPhaseManifest(
        run_id=run_id,
        config_ids=config_ids_used,
        dimensions=dimensions,
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        head_pool_variant=HEAD_POOL_VARIANT,
        backbones=("effnet",),
        heads=active_head_tuple,
        bin_modes=bin_modes,
        song_ids=song_tuple,
        scoring_semantics_version=_SCV,
        results=tuple(results),
        skip_reasons=tuple(skip_reasons),
        done=done,
        skipped=skipped,
        errors=errors,
        finite=bool(finite_overall),
        reference_corpus_hash=reference_corpus_hash,
        primary_analysis_succeeded=True,
    )
