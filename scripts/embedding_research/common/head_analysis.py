"""Canonical CPU catalog-scoped head analysis (Plan E P1-S1/P1-S2) — the ACTIVE home.

This module is the sole **active** home for the CPU head-analysis surface: the
boundary/variant constants, the per-configuration coverage record
(:class:`HeadAnalysisConfigRecord`), the orchestration manifest
(:class:`HeadAnalysisManifest`) and the CPU-only catalog runner
:func:`run_shared_catalog_head_analysis`.

Design rules (parts CONTRACTS §E + the corrective exact-``M_g`` rewire):
* Head membership is defined **only** by each compact segment's exact searchable
  set ``M_g = structural[start_idx, end_idx) - absorbed_indices - {mask[i] == 0}``
  reconstructed via ``helpers.segmentation.reconstruct_searchable_indices`` from the
  COMPACT ``seg_meta`` rows.  ``start_idx/end_idx`` are structural report ranges that
  only seed the reconstruction; they are never an inclusive membership authority.
  There is no ``seg_membership`` table and no inclusive/absorbed-inclusive range is
  ever pooled.
* The retained research path has **no committed silence-mask loader** and the §E
  signature deliberately provides no per-song mask seam, so the runner reconstructs
  the same membership the compact catalog itself encodes at build time
  (``mask=None`` => ``M_g = structural[start_idx, end_idx) - absorbed_indices``).
  Absorbed-outlier rows are always excluded; the "same silence/outlier exclusions"
  wording means the head gather uses exactly the catalog's searchable indices, never
  an inclusive range.
* Config eligibility is canonical/config-keyed: only COMPACT canonical configs with a
  non-empty ``canonical_config_hash`` and the direct-L2 PTC semantics / bin mode /
  strategy version are pooled over.  ``alias_of_config_id``/durable aliases/calibration
  columns are never read.
* The operation is **CPU-only and derived**: it consumes frozen ready head streams and
  compact catalog rows only.  It never discovers audio, loads models, runs
  ONNX/CUDA/sklearn, invokes segmentation or CTP, reads artifact paths, or infers
  membership.
* Pooled values are **transient** and never persisted as vectors/cache files or copied
  medoids.  The only durable head-analysis sink is canonical coverage/skip provenance
  in ``head_phase_provenance`` written by ``db/head_phase.py`` (the caller persists the
  returned manifest).
* The class-1 head value is taken from ``act[1]`` (never ``act[0]``) of each gathered
  head array; the concatenated ``HeadStreamStore.batch_gather`` columns are in canonical
  head order and sliced per head by ``dim_by_head``.  Every emitted numeric value is
  finite and JSON-safe.  No new PK/UNIQUE/index is introduced.

The legacy live-ONNX cache/range runner (``classify.run_shared_ptc_head_pooling``), the
top-level ``head_pooling.py`` legacy surface, and the retired
``pool_head_outputs_over_ptc_boundaries`` / ``run_shared_ptc_head_pooling`` symbols from
this module are deleted with the inclusive pooling paths (P1-S2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from scripts.embedding_research.helpers.thresholds import (
    canonical_float as _canonical_float,
)

__all__ = [
    "BOUNDARY_SOURCE_CATALOG",
    "HEAD_POOL_VARIANT",
    "PTC_SEMANTICS",
    "TEMPORAL_BIN_MODES",
    "HeadAnalysisConfigRecord",
    "HeadAnalysisManifest",
    "run_shared_catalog_head_analysis",
]

#: The only boundary source this phase may consume.  CTP boundaries are never accepted
#: or produced, and no head-specific-segmentation boundary exists.
BOUNDARY_SOURCE_CATALOG = "catalog"

#: The single explicit label for the shared-boundary head-pooling variant.  It is part of
#: the head-phase configuration identity and is deliberately disjoint from any
#: hypothetical head-specific-segmentation variant: this phase pools over the
#: *already-produced* compact-catalog boundaries (exact membership) and never creates
#: head-specific bins.
HEAD_POOL_VARIANT = "shared_catalog_boundary"

#: Canonical EffNet ``seg_config`` ``bin_mode`` values eligible for the shared CPU
#: head analysis.  Other bin modes are never selected.
TEMPORAL_BIN_MODES: frozenset[str] = frozenset({"temporal_global", "temporal_perdim"})

#: Canonical threshold-semantics labels eligible for the shared CPU head analysis.  The
#: corrective pass is direct-L2 only: ``std_scaled`` and calibration semantics are gone
#: (DD R3), so only ``direct_l2`` is admissible.
PTC_SEMANTICS: frozenset[str] = frozenset({"direct_l2"})

#: Scoring-input semantics contract version for the canonical CPU head-analysis manifest.
#: This module is the active owner (formerly ``cache_identity.SCORING_SEMANTICS_VERSION``,
#: deleted with the cache layer in the corrective-pass hard cut).  The value stays pinned
#: to the search-view / bounded-scoring semantics version (1).
SCORING_SEMANTICS_VERSION: int = 1

#: Class-1 lives at index 1 of the head-activation vector; ``act[0]`` is never the
#: class-1 value.
_CLASS1_INDEX = 1

#: Per-configuration head-phase status vocabulary (mirrors the persistence row).
_HEAD_PHASE_STATUSES: frozenset[str] = frozenset({"done", "skipped", "error"})


# --------------------------------------------------------------------------- #
# Transient per-segment pooling (internal)                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _SegmentPooledHead:
    """One transient pooled class-1 value for one exact segment membership.

    ``acts`` is the float32 ``[C]`` mean head-activation vector over the exact
    reconstructed searchable member rows (row ``i`` is the activation of source patch
    ``member_patch_indices[i]``).  ``class1`` is the scalar class-1 value taken from
    ``acts[_CLASS1_INDEX]`` (the mean of ``act[1]`` over the members) — never
    ``act[0]``.  ``weight`` is the searchable count ``|M_g|``.  ``finite`` is True only
    when every emitted numeric value is finite.  This object is transient: it is never
    persisted or returned in the orchestration manifest.
    """

    acts: np.ndarray
    class1: float
    weight: int
    member_patch_indices: tuple[int, ...]
    segment_id: int
    finite: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "acts": [float(v) for v in self.acts],
            "class1": float(self.class1),
            "weight": int(self.weight),
            "member_patch_indices": [int(i) for i in self.member_patch_indices],
            "segment_id": int(self.segment_id),
            "finite": bool(self.finite),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


def _pool_segment_heads(
    acts: np.ndarray,
    member_patch_indices: Any,
    *,
    segment_id: int,
) -> _SegmentPooledHead:
    """Pool the class-1 head value over one exact segment membership (pure, internal).

    ``acts`` must already be gathered **in the exact reconstructed ``M_g`` order**:
    finite float32 ``[N, C]`` where row ``i`` is the activation of source patch
    ``member_patch_indices[i]`` (the segment's searchable members only; absorbed and
    mask-silent rows are excluded upstream).  The mean is over exactly those rows and
    the class-1 value is ``acts.mean(axis=0)[_CLASS1_INDEX]`` — never ``act[0]``.  This
    performs no IO/audio/model/ONNX/CUDA/segmentation/CTP.

    Raises
    ------
    ValueError
        On malformed input: non-finite / wrong-rank / empty acts, non-co-indexed or
        non-unique or negative membership indices, or a negative segment id.
    """
    acts_f = np.asarray(acts, dtype=np.float32)
    if acts_f.ndim != 2:
        raise ValueError(f"gathered head rows must be 2-D [N, C]; got ndim={acts_f.ndim}")
    n_rows = int(acts_f.shape[0])
    if n_rows == 0:
        raise ValueError("gathered head rows must contain at least one exact member row")
    if acts_f.shape[1] < 1:
        raise ValueError("gathered head rows must have at least one class column")
    if not np.all(np.isfinite(acts_f)):
        raise ValueError("gathered head rows must be finite (no NaN/Inf)")
    if isinstance(segment_id, bool) or not isinstance(segment_id, int) or segment_id < 0:
        raise ValueError(f"segment_id must be a non-negative integer; got {segment_id!r}")

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

    # Mean over the exact gathered member rows -> one pooled vector per segment.
    pooled = acts_f.mean(axis=0).astype(np.float32)
    class1 = float(pooled[_CLASS1_INDEX])  # act[1], never act[0]
    finite = bool(np.all(np.isfinite(pooled)))

    return _SegmentPooledHead(
        acts=pooled,
        class1=class1,
        weight=n_rows,
        member_patch_indices=member_ids,
        segment_id=int(segment_id),
        finite=finite,
    )


# --------------------------------------------------------------------------- #
# Per-configuration outcome + orchestration manifest (P1-S1)                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HeadAnalysisConfigRecord:
    """One auditable per-(config, head) outcome of the catalog-scoped head phase.

    ``config_id`` is the application identity of the selected canonical ``seg_config``
    the head output was pooled over; ``threshold_configured`` / ``threshold_effective``
    / ``semantics`` carry that config's resolved direct-L2 threshold identity.
    ``status`` is one of ``"done"`` (at least one song pooled), ``"skipped"`` (attempted
    but nothing pooled), or ``"error"`` (a song's membership/pooling failed validation).
    ``reason`` records the skip/error explanation for the manifest.
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
    boundary_source: str = BOUNDARY_SOURCE_CATALOG
    head_pool_variant: str = HEAD_POOL_VARIANT

    def __post_init__(self) -> None:
        if self.boundary_source != BOUNDARY_SOURCE_CATALOG:
            raise ValueError(
                f"head-analysis config record boundary_source must be "
                f"{BOUNDARY_SOURCE_CATALOG!r}; got {self.boundary_source!r} (CTP never used)"
            )
        if self.head_pool_variant != HEAD_POOL_VARIANT:
            raise ValueError(
                f"head-analysis config record head_pool_variant must be {HEAD_POOL_VARIANT!r}; "
                f"got {self.head_pool_variant!r} (head-specific segmentation is not a shared-boundary row)"
            )
        if self.status not in _HEAD_PHASE_STATUSES:
            raise ValueError(
                f"head-analysis config record status must be one of {sorted(_HEAD_PHASE_STATUSES)}; got {self.status!r}"
            )
        if self.semantics not in PTC_SEMANTICS:
            raise ValueError(
                f"head-analysis config record semantics must be one of {sorted(PTC_SEMANTICS)}; got {self.semantics!r}"
            )
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
class HeadAnalysisManifest:
    """JSON-safe, deterministic manifest of a canonical catalog-scoped head run.

    Records the ``run_id``, the selected canonical ``config_ids``, the
    per-(config, head) coverage outcomes, and every deterministic skip/error reason.
    No pooled vector or medoid value is persisted in this manifest: pooled values are
    transient.
    """

    run_id: str
    config_ids: tuple[int, ...]
    boundary_source: str
    head_pool_variant: str
    backbones: tuple[str, ...]
    heads: tuple[str, ...]
    song_ids: tuple[str, ...]
    scoring_semantics_version: int
    results: tuple[HeadAnalysisConfigRecord, ...]
    skip_reasons: tuple[tuple[str, str], ...]
    done: int
    skipped: int
    errors: int
    finite: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_ids": [int(c) for c in self.config_ids],
            "boundary_source": self.boundary_source,
            "head_pool_variant": self.head_pool_variant,
            "backbones": list(self.backbones),
            "heads": list(self.heads),
            "song_ids": list(self.song_ids),
            "scoring_semantics_version": int(self.scoring_semantics_version),
            "results": [r.to_dict() for r in self.results],
            "skip_reasons": [[str(scope), str(reason)] for scope, reason in self.skip_reasons],
            "done": int(self.done),
            "skipped": int(self.skipped),
            "errors": int(self.errors),
            "finite": bool(self.finite),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


# --------------------------------------------------------------------------- #
# Canonical CPU catalog runner (P1-S1)                                         #
# --------------------------------------------------------------------------- #


def _collect_segment_membership(con, config_id: int, song_id: str, segments_fn, reconstruct_fn, patch_count):
    """Yield each compact segment's exact reconstructed searchable membership ``M_g``.

    Reconstructs ``M_g = {start <= i < end} - absorbed_indices - {mask[i] == 0}`` for
    every compact ``seg_meta`` row via ``reconstruct_fn`` (the canonical
    ``reconstruct_searchable_indices`` helper) with ``mask=None`` (the retained path has
    no committed silence-mask loader, matching the catalog's own build semantics).  Yields
    ``(seg_id, searchable_indices, weight)`` in ascending seg_id order.  Absorbed rows are
    excluded from pooling inputs; an empty-``M_g`` segment yields nothing.
    """
    segs = segments_fn(con, config_id, song_id)
    for seg in segs:
        mg = reconstruct_fn(seg, None, patch_count)
        if len(mg) == 0:
            continue
        indices = tuple(int(i) for i in mg)
        yield seg.seg_id, indices, len(indices)


def run_shared_catalog_head_analysis(
    catalog: Any,
    head_store: Any,
    *,
    config_ids: Any = None,
    song_ids: Any = None,
    heads: Any = None,
    run_id: str,
) -> HeadAnalysisManifest:
    """Canonical CPU catalog-scoped head analysis (ACTIVE — exact ``M_g`` semantics).

    Deterministic, CPU-only and non-blocking.  ``catalog`` is a compact
    :class:`CatalogHandle` (or its snapshot ``con`` — resolved duck-typed via
    ``getattr(catalog, "con", catalog)``, mirroring the D-phase analysis path): the runner
    reads only the compact ``seg_config``/``catalog_song``/``seg_meta`` tables and
    reconstructs each segment's exact searchable membership
    ``M_g = structural[start_idx,end_idx) - absorbed_indices`` via
    :func:`helpers.segmentation.reconstruct_searchable_indices`.  It never reads a
    per-patch membership relation, never treats ``start_idx/end_idx`` as an inclusive
    membership authority, and never reads ``alias_of_config_id``.  Because the retained
    path has no committed silence-mask loader (and the §E signature provides no mask
    seam), reconstruction passes ``mask=None`` — the exact membership the compact catalog
    itself encodes.

    Config eligibility is canonical/config-keyed: only COMPACT canonical configs with a
    non-empty ``canonical_config_hash`` and the direct-L2 PTC semantics / bin mode /
    strategy version are pooled over.  When ``config_ids`` is ``None`` the default is the
    canonical compact configs of the default primary backbone ``effnet``.

    Gathers each song's reconstructed searchable rows once per (config, song) through
    ``HeadStreamStore.batch_gather`` (all heads in canonical sorted-column order), slices
    per head using the registry ``dim_by_head``, and pools each non-empty segment over its
    exact ``M_g`` rows taking the class-1 value from ``act[1]`` (never ``act[0]``).  Empty
    ``M_g`` segments produce no pooled value.  Performs no audio/model/ONNX/CUDA/sklearn/CTP
    work and persists no pooled vector/cache/medoid artifact; the returned manifest carries
    deterministic coverage/skip/error outcomes and the caller persists canonical provenance.

    Parameters
    ----------
    catalog:
        A compact :class:`CatalogHandle` (or its snapshot ``con``).
    head_store:
        A :class:`HeadStreamStore` (or an interface-parity fake) exposing ``lookup`` and
        ``batch_gather`` over frozen aligned head rows.
    config_ids:
        Optional explicit canonical ``seg_config`` ids to analyze.
    song_ids:
        Optional explicit song selection (default: every compact ``catalog_song`` row of
        the selected configs).
    heads:
        Optional explicit head-name selection (default: all heads in the aligned record).
    run_id:
        Run identity recorded on the returned manifest.

    Returns
    -------
    :class:`HeadAnalysisManifest` with the selected ``config_ids``, per-(config, head)
    coverage, deterministic skip/error reasons, and a finite status.
    """
    from scripts.embedding_research.catalog import (
        compact_catalog_songs_by_config as _config_songs_fn,
    )
    from scripts.embedding_research.catalog import (
        compact_configs_by_backbone as _configs_by_backbone,
    )
    from scripts.embedding_research.catalog import (
        compact_segments_by_config_song as _segments_fn,
    )
    from scripts.embedding_research.helpers.segmentation import (
        reconstruct_searchable_indices as _reconstruct_mg,
    )
    from scripts.embedding_research.helpers.thresholds import PTC_STRATEGY_VERSION as _PTC_V
    from scripts.embedding_research.streams.records import (
        parse_dim_by_head as _parse_dim,
    )
    from scripts.embedding_research.streams.records import (
        parse_head_ids as _parse_head_ids,
    )

    # Lazy catalog attach: accept a CatalogHandle or its snapshot connection.
    con = getattr(catalog, "con", catalog)

    backbone = "effnet"  # default primary backbone for the shared-boundary head phase.
    backbone_configs = tuple(sorted(_configs_by_backbone(con, backbone), key=lambda c: c.config_id))

    def _eligible(cfg) -> bool:
        return (
            bool(cfg.canonical_config_hash)
            and cfg.threshold_semantics in PTC_SEMANTICS
            and cfg.bin_mode in TEMPORAL_BIN_MODES
            and cfg.strategy_version == _PTC_V
        )

    requested = {int(c) for c in config_ids} if config_ids is not None else None
    if requested is None:
        selected = [c for c in backbone_configs if _eligible(c)]
        skip_reasons: list[tuple[str, str]] = []
    else:
        by_id = {c.config_id: c for c in backbone_configs}
        selected = []
        skip_reasons = []
        for cid in sorted(requested):
            cfg = by_id.get(cid)
            if cfg is None:
                skip_reasons.append(
                    (f"config:{cid}", f"no seg_config row for requested config_id under backbone {backbone}")
                )
            elif not _eligible(cfg):
                skip_reasons.append((f"config:{cid}", "config not eligible for canonical catalog-scoped head analysis"))
            else:
                selected.append(cfg)

    explicit_heads: frozenset[str] | None = frozenset(str(h) for h in heads) if heads is not None else None

    # key -> [n_attempted_songs, n_pooled_songs, any_error, all_finite, reason]
    agg: dict[tuple[int, str], list] = {}
    processed_song_ids: set[str] = set()
    active_heads: set[str] = set()

    for cfg in selected:
        song_leaves = {r.song_id: r for r in _config_songs_fn(con, cfg.config_id)}
        if song_ids is not None:
            songs = sorted(str(s) for s in song_ids)
        else:
            songs = sorted(song_leaves)
        for song in songs:
            leaf = song_leaves.get(song)
            if leaf is None:
                continue
            patch_count = int(leaf.patch_count)
            segs = list(
                _collect_segment_membership(
                    con,
                    cfg.config_id,
                    song,
                    segments_fn=_segments_fn,
                    reconstruct_fn=_reconstruct_mg,
                    patch_count=patch_count,
                )
            )
            if not segs:
                continue
            record_scope = f"config:{cfg.config_id}:song:{song}"
            try:
                record = head_store.lookup(song, cfg.backbone)
            except Exception as exc:
                skip_reasons.append((record_scope, f"head stream lookup failed for backbone {cfg.backbone}: {exc!r}"))
                continue
            raw_head_ids = record.head_ids
            if not (raw_head_ids and str(raw_head_ids).strip()):
                skip_reasons.append(
                    (
                        record_scope,
                        f"no frozen head stream available for backbone {cfg.backbone} "
                        f"(empty head record {raw_head_ids!r})",
                    )
                )
                continue
            record_heads = _parse_head_ids(raw_head_ids)
            if explicit_heads is not None:
                record_heads = tuple(h for h in record_heads if h in explicit_heads)
            rec_heads = record_heads  # consumed by the offset/pool loops below
            if not record_heads:
                # An explicit ``heads=`` restriction may legitimately leave a song with
                # no matching requested head; that is intended filtering, not a partial
                # stream/catalog misalignment to report.
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
            for _seg_id, indices, _w in segs:
                union.extend(indices)
            try:
                gathered = head_store.batch_gather(song, cfg.backbone, union)
            except Exception as exc:
                skip_reasons.append(
                    (
                        record_scope,
                        f"head stream gather failed for backbone {cfg.backbone} "
                        f"over {len(union)} searchable rows: {exc!r}",
                    )
                )
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
                for _seg_id, indices, _weight in segs:
                    n_members = len(indices)
                    rows = gathered[row_cursor : row_cursor + n_members, start:end]
                    row_cursor += n_members
                    try:
                        pooled = _pool_segment_heads(
                            rows,
                            indices,
                            segment_id=_seg_id,
                        )
                    except ValueError as exc:
                        entry[2] = True
                        entry[4] = f"membership/pooling validation failed for song {song}: {exc}"
                        break
                    if pooled.finite:
                        head_pooled = True
                    else:
                        head_finite = False
                if not entry[2]:
                    if head_pooled:
                        entry[1] += 1
                    entry[3] = entry[3] and head_finite

    results: list[HeadAnalysisConfigRecord] = []
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
            HeadAnalysisConfigRecord(
                config_id=config_id,
                backbone=cfg.backbone,
                head=head,
                bin_mode=cfg.bin_mode,
                threshold_configured=float(cfg.threshold_configured),
                threshold_effective=float(cfg.threshold_effective),
                semantics=cfg.threshold_semantics,
                status=status,
                reason=reason,
                n_songs=int(n_songs),
                n_pooled=int(n_pooled),
                finite=bool(all_finite and not any_err),
                boundary_source=BOUNDARY_SOURCE_CATALOG,
                head_pool_variant=HEAD_POOL_VARIANT,
            )
        )

    config_ids_used = tuple(sorted({r.config_id for r in results}))
    song_tuple = tuple(sorted(processed_song_ids))
    active_head_tuple = tuple(sorted(active_heads))
    skip_reasons.extend(
        (f"config:{cfg.config_id}", "config has no pooled head output")
        for cfg in selected
        if cfg.config_id not in config_ids_used
    )
    return HeadAnalysisManifest(
        run_id=run_id,
        config_ids=config_ids_used,
        boundary_source=BOUNDARY_SOURCE_CATALOG,
        head_pool_variant=HEAD_POOL_VARIANT,
        backbones=(backbone,),
        heads=active_head_tuple,
        song_ids=song_tuple,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        results=tuple(results),
        skip_reasons=tuple(skip_reasons),
        done=done,
        skipped=skipped,
        errors=errors,
        finite=bool(finite_overall),
    )
