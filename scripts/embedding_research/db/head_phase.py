"""DuckDB persistence for shared-boundary head-phase provenance (Plan B, Phase 2).

This is the SMALLEST research-only persistence/report surface needed to record
head-boundary preparation status and per-configuration provenance for the
shared EffNet PTC boundary head phase
(``classify.run_shared_ptc_head_pooling`` -> :class:`HeadPhaseManifest`).

The surface is ADDITIVE: it writes only to its own ``head_phase_provenance``
table and never modifies primary ``analyze_metrics`` rows, corpus hashes, or any
CTP storage.  It uses named-column writes (DTO/DDL column order can differ) and
validates every finite numeric value so no NaN/Infinity is persisted or emitted.

Configuration identity (P2-S3)
------------------------------
Each row carries an explicit identity for the ``(effnet, head, bin_mode,
threshold, boundary_source, head_pool_variant)`` tuple via
:func:`head_phase_config_key`.  The ``head:`` key namespace is disjoint from the
primary/CTP ``global_pool:``/``ptc:``/``ctp:`` strategy-key namespaces, and the
fixed ``boundary_source="effnet_ptc"`` + ``head_pool_variant`` values mean
neither a CTP strategy key nor any head-specific-segmentation threshold can
masquerade as a shared-boundary row (head-specific segmentation is forbidden).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from scripts.embedding_research.cache_identity import SCORING_SEMANTICS_VERSION
from scripts.embedding_research.head_pooling import (
    BOUNDARY_SOURCE_EFFNET_PTC,
    HEAD_POOL_VARIANT,
    HeadPhaseManifest,
)
from scripts.embedding_research.helpers.binning import canonical_threshold as _canonical_threshold
from scripts.embedding_research.helpers.binning import threshold_key as _threshold_key

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "HeadPhaseProvenanceRow",
    "build_head_phase_provenance_rows",
    "head_phase_config_key",
    "load_head_phase_provenance",
    "query_head_phase_done",
    "write_head_phase_provenance",
]

#: Allowed per-configuration preparation status values (mirrors
#: ``HeadPhaseConfigRecord.status``).
_HEAD_PHASE_STATUSES: frozenset[str] = frozenset({"done", "skipped", "error"})


def head_phase_config_key(
    *,
    backbone: str,
    head: str,
    bin_mode: str,
    threshold: float,
    boundary_source: str = BOUNDARY_SOURCE_EFFNET_PTC,
    head_pool_variant: str = HEAD_POOL_VARIANT,
) -> str:
    """Canonical configuration identity for one shared-boundary head-phase tuple.

    The ``head:`` prefix places the identity in a namespace disjoint from the
    primary/CTP strategy keys (``global_pool:``, ``ptc:``, ``ctp:``), and the
    fixed ``boundary_source`` + ``head_pool_variant`` values make it impossible
    for a CTP key or a hypothetical head-specific-segmentation threshold to
    masquerade as a shared-boundary row.
    """
    return f"head:{backbone}:{head}:{bin_mode}:{_threshold_key(threshold)}:{boundary_source}:{head_pool_variant}"


@dataclass(frozen=True)
class HeadPhaseProvenanceRow:
    """One persisted per-configuration provenance row for the head phase.

    ``reference_corpus_hash`` is the primary EffNet matching-corpus hash this
    head phase derived from (or ``None`` when run without a declared reference
    corpus, i.e. a head-availability-only subset).  Every numeric value is
    validated finite and in-range so no NaN/Infinity reaches the DB.
    """

    backbone: str
    head: str
    bin_mode: str
    threshold: float
    boundary_source: str = BOUNDARY_SOURCE_EFFNET_PTC
    head_pool_variant: str = HEAD_POOL_VARIANT
    status: str = "done"
    reason: str | None = None
    n_songs: int = 0
    n_pooled: int = 0
    finite: bool = True
    scoring_semantics_version: int = SCORING_SEMANTICS_VERSION
    reference_corpus_hash: str | None = None

    def __post_init__(self) -> None:
        if self.boundary_source != BOUNDARY_SOURCE_EFFNET_PTC:
            raise ValueError(
                f"head-phase row boundary_source must be {BOUNDARY_SOURCE_EFFNET_PTC!r}; "
                f"got {self.boundary_source!r} (CTP cache paths must never be repurposed)"
            )
        if self.head_pool_variant != HEAD_POOL_VARIANT:
            raise ValueError(
                f"head-phase row head_pool_variant must be {HEAD_POOL_VARIANT!r}; got "
                f"{self.head_pool_variant!r} (head-specific segmentation is not a shared-boundary row)"
            )
        if self.status not in _HEAD_PHASE_STATUSES:
            raise ValueError(
                f"head-phase row status must be one of {sorted(_HEAD_PHASE_STATUSES)}; got {self.status!r}"
            )
        th = float(self.threshold)
        if not math.isfinite(th):
            raise ValueError(f"head-phase row threshold must be finite; got {self.threshold!r}")
        object.__setattr__(self, "threshold", _canonical_threshold(th))
        if int(self.n_songs) < 0 or int(self.n_pooled) < 0:
            raise ValueError("head-phase row n_songs/n_pooled must be non-negative")
        if int(self.n_pooled) > int(self.n_songs):
            raise ValueError(f"head-phase row n_pooled ({self.n_pooled}) cannot exceed n_songs ({self.n_songs})")
        if int(self.scoring_semantics_version) < 0:
            raise ValueError("head-phase row scoring_semantics_version must be non-negative")

    @property
    def config_key(self) -> str:
        """The explicit configuration identity for this row."""
        return head_phase_config_key(
            backbone=self.backbone,
            head=self.head,
            bin_mode=self.bin_mode,
            threshold=self.threshold,
            boundary_source=self.boundary_source,
            head_pool_variant=self.head_pool_variant,
        )

    def to_tuple(self) -> tuple[Any, ...]:
        """Column-order tuple for the named-column write (matches the DDL)."""
        return (
            self.backbone,
            self.head,
            self.bin_mode,
            float(self.threshold),
            self.boundary_source,
            self.head_pool_variant,
            self.status,
            self.reason,
            int(self.n_songs),
            int(self.n_pooled),
            (1 if self.finite else 0),
            int(self.scoring_semantics_version),
            self.reference_corpus_hash,
        )


def build_head_phase_provenance_rows(
    manifest: HeadPhaseManifest,
    reference_corpus_hash: str | None = None,
) -> list[HeadPhaseProvenanceRow]:
    """Convert a :class:`HeadPhaseManifest` into one provenance row per config record.

    ``reference_corpus_hash`` optionally declares the primary EffNet corpus hash
    the head phase derived its song set from, so persisted rows carry the same
    primary EffNet corpus identity (or a clearly declared derived subset).
    """
    rows: list[HeadPhaseProvenanceRow] = [
        HeadPhaseProvenanceRow(
            backbone=rec.backbone,
            head=rec.head,
            bin_mode=rec.bin_mode,
            threshold=rec.threshold,
            boundary_source=rec.boundary_source,
            head_pool_variant=HEAD_POOL_VARIANT,
            status=rec.status,
            reason=rec.reason,
            n_songs=rec.n_songs,
            n_pooled=rec.n_pooled,
            finite=rec.finite,
            scoring_semantics_version=manifest.scoring_semantics_version,
            reference_corpus_hash=reference_corpus_hash,
        )
        for rec in manifest.results
    ]
    return rows


def write_head_phase_provenance(con, rows: Iterable[HeadPhaseProvenanceRow]) -> None:
    """Persist head-phase provenance rows using a named-column insert-or-replace.

    Re-validates every row (finite values, allowed status, canonical identity)
    before writing so no malformed or non-finite row reaches the DB.
    """
    materialized = [HeadPhaseProvenanceRow(**r.__dict__) for r in rows]
    if not materialized:
        return
    con.executemany(
        "INSERT INTO head_phase_provenance "
        "(backbone, head, bin_mode, threshold, boundary_source, head_pool_variant, "
        "status, reason, n_songs, n_pooled, finite, scoring_semantics_version, "
        "reference_corpus_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT (backbone, head, bin_mode, threshold, boundary_source, head_pool_variant) "
        "DO UPDATE SET status=excluded.status, reason=excluded.reason, "
        "n_songs=excluded.n_songs, n_pooled=excluded.n_pooled, finite=excluded.finite, "
        "scoring_semantics_version=excluded.scoring_semantics_version, "
        "reference_corpus_hash=excluded.reference_corpus_hash",
        [r.to_tuple() for r in materialized],
    )


def load_head_phase_provenance(con) -> list[HeadPhaseProvenanceRow]:
    """Load every persisted head-phase provenance row, ordered by config identity."""
    rows = con.execute(
        "SELECT backbone, head, bin_mode, threshold, boundary_source, head_pool_variant, "
        "status, reason, n_songs, n_pooled, finite, scoring_semantics_version, "
        "reference_corpus_hash FROM head_phase_provenance ORDER BY backbone, head, "
        "bin_mode, threshold, boundary_source, head_pool_variant"
    ).fetchall()
    return [
        HeadPhaseProvenanceRow(
            backbone=str(r[0]),
            head=str(r[1]),
            bin_mode=str(r[2]),
            threshold=float(r[3]),
            boundary_source=str(r[4]),
            head_pool_variant=str(r[5]),
            status=str(r[6]),
            reason=r[7],
            n_songs=int(r[8]),
            n_pooled=int(r[9]),
            finite=bool(r[10]),
            scoring_semantics_version=int(r[11]),
            reference_corpus_hash=r[12],
        )
        for r in rows
    ]


def query_head_phase_done(con) -> set[str]:
    """Return the config keys of persisted head-phase rows with status ``done``.

    Used as a phase-done check (mirrors ``query_analysis_done`` semantics).  A
    missing table yields an empty set.
    """
    try:
        rows = con.execute(
            "SELECT backbone, head, bin_mode, threshold, boundary_source, head_pool_variant, status "
            "FROM head_phase_provenance WHERE status = 'done'"
        ).fetchall()
    except Exception:
        return set()
    return {
        head_phase_config_key(
            backbone=str(r[0]),
            head=str(r[1]),
            bin_mode=str(r[2]),
            threshold=float(r[3]),
            boundary_source=str(r[4]),
            head_pool_variant=str(r[5]),
        )
        for r in rows
    }
