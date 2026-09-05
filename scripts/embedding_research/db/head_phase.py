"""DuckDB persistence for canonical catalog-scoped head-analysis provenance.

This module is the **canonical** persistence surface for the active CPU head analysis
(``common.head_analysis.run_shared_catalog_head_analysis``).  It owns the
``head_phase_provenance`` table and enforces the exact canonical-row predicate for every
reader/report/fixture/coverage calculation.  Legacy archival machinery and the
``run_id='legacy'`` concept are removed (corrective pass P1-S2): the surface only ever
writes and reads canonical current rows.

Table contract
--------------
``head_phase_provenance`` has exactly these named columns and **no** PRIMARY KEY /
UNIQUE / index (DuckDB ART/WAL policy — application identity and uniqueness are asserted
before commit):

``run_id TEXT NOT NULL``, ``config_id INTEGER``, ``backbone TEXT NOT NULL``, ``head TEXT
NOT NULL``, ``bin_mode TEXT NOT NULL``, ``threshold_configured DOUBLE``,
``threshold_effective DOUBLE``, ``semantics TEXT``, ``boundary_source TEXT NOT NULL``,
``head_pool_variant TEXT NOT NULL``, ``status TEXT NOT NULL``, ``reason TEXT``,
``n_songs INTEGER NOT NULL``, ``n_pooled INTEGER NOT NULL``, ``finite INTEGER NOT NULL``,
``scoring_semantics_version INTEGER NOT NULL``, ``reference_corpus_hash TEXT``, and
``threshold DOUBLE``.

The legacy ``threshold`` column is retained only as a null-for-canonical column (all
canonical rows carry ``threshold IS NULL``); no code reads or writes it anymore.  The
``run_id`` of every row is the integer-millisecond-timestamped run identity produced by
the CLI caller (e.g. ``head-analysis-{started_at_ms}``).

Canonical predicate
-------------------
A canonical current row satisfies: ``config_id IS NOT NULL AND backbone = 'effnet' AND
bin_mode IN TEMPORAL_BIN_MODES AND threshold_configured IS NOT NULL AND threshold_effective IS
NOT NULL AND semantics IN PTC_SEMANTICS (direct_l2) AND boundary_source = 'catalog'
AND head_pool_variant = 'shared_catalog_boundary'``.  Any row outside it is excluded
from coverage reads (and, being read-only historical data, is unread at runtime).

Application identity is ``(config_id, backbone, head, bin_mode, threshold_configured,
threshold_effective, semantics, boundary_source, head_pool_variant)`` — ``run_id``
excluded.  Incoming duplicate canonical identities are rejected; a rerun transactionally
replaces only the prior canonical row for that identity.

The surface writes only to its own ``head_phase_provenance`` table and never modifies
primary ``analyze_metrics`` rows, corpus hashes, catalog/membership, or any CTP storage.
Named-column writes mean DTO/DDL column order can differ.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from scripts.embedding_research.common.head_analysis import (
    BOUNDARY_SOURCE_CATALOG,
    HEAD_POOL_VARIANT,
    PTC_SEMANTICS,
    SCORING_SEMANTICS_VERSION,
    TEMPORAL_BIN_MODES,
)
from scripts.embedding_research.helpers.thresholds import (
    canonical_float as _canonical_float,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "CANONICAL_HEAD_PHASE_WHERE",
    "HEAD_PHASE_PROVENANCE_COLUMNS",
    "HeadPhaseProvenanceRow",
    "build_head_phase_provenance_rows",
    "head_phase_config_key",
    "load_head_phase_provenance",
    "write_head_phase_provenance",
]

#: The single table this surface owns.
HEAD_PHASE_TABLE = "head_phase_provenance"

#: Allowed per-configuration head-phase status values.
_HEAD_PHASE_STATUSES: frozenset[str] = frozenset({"done", "skipped", "error"})

#: Exact column set — DDL order.  ``finite``/counts are INTEGER.
HEAD_PHASE_PROVENANCE_COLUMNS: tuple[str, ...] = (
    "run_id",
    "config_id",
    "backbone",
    "head",
    "bin_mode",
    "threshold_configured",
    "threshold_effective",
    "semantics",
    "boundary_source",
    "head_pool_variant",
    "status",
    "reason",
    "n_songs",
    "n_pooled",
    "finite",
    "scoring_semantics_version",
    "reference_corpus_hash",
    "threshold",
)

_SEMANTICS_SQL = ", ".join(repr(s) for s in sorted(PTC_SEMANTICS))
_BIN_MODES_SQL = ", ".join(repr(b) for b in sorted(TEMPORAL_BIN_MODES))

#: The exact canonical-row WHERE clause.  Readers, reports, fixtures and coverage
#: calculations use it; any row outside it is historical/unclassified and excluded.
CANONICAL_HEAD_PHASE_WHERE = (
    "config_id IS NOT NULL"
    " AND backbone = 'effnet'"
    f" AND bin_mode IN ({_BIN_MODES_SQL})"
    " AND threshold_configured IS NOT NULL"
    " AND threshold_effective IS NOT NULL"
    f" AND semantics IN ({_SEMANTICS_SQL})"
    " AND boundary_source = 'catalog'"
    " AND head_pool_variant = 'shared_catalog_boundary'"
    " AND threshold IS NULL"
)

_COLUMNS_SQL = ", ".join(HEAD_PHASE_PROVENANCE_COLUMNS)


def head_phase_config_key(
    *,
    config_id: int,
    backbone: str,
    head: str,
    bin_mode: str,
    threshold_configured: float,
    threshold_effective: float,
    semantics: str,
    boundary_source: str = BOUNDARY_SOURCE_CATALOG,
    head_pool_variant: str = HEAD_POOL_VARIANT,
) -> str:
    """Application identity for one canonical head-phase tuple (``run_id`` excluded).

    The identity is ``(config_id, backbone, head, bin_mode, threshold_configured,
    threshold_effective, semantics, boundary_source, head_pool_variant)``.  A rerun of the
    same identity replaces the existing canonical row rather than creating a second one.
    """
    cfg = "none" if config_id is None else str(int(config_id))
    tc = "none" if threshold_configured is None else repr(float(_canonical_float(threshold_configured)))
    te = "none" if threshold_effective is None else repr(float(_canonical_float(threshold_effective)))
    sem = "none" if semantics is None else str(semantics)
    return f"head:{cfg}:{backbone}:{head}:{bin_mode}:{tc}:{te}:{sem}:{boundary_source}:{head_pool_variant}"


@dataclass(frozen=True)
class HeadPhaseProvenanceRow:
    """One persisted canonical ``head_phase_provenance`` row.

    ``finite`` is persisted as an INTEGER (1/0).  Canonical rows carry a non-NULL
    ``config_id`` and current threshold/semantics and a NULL legacy ``threshold``.  This is
    a plain frozen container — shape validation lives in
    :func:`write_head_phase_provenance`.
    """

    run_id: str
    config_id: int | None = None
    backbone: str = "effnet"
    head: str = ""
    bin_mode: str = ""
    threshold_configured: float | None = None
    threshold_effective: float | None = None
    semantics: str | None = None
    boundary_source: str = BOUNDARY_SOURCE_CATALOG
    head_pool_variant: str = HEAD_POOL_VARIANT
    status: str = "done"
    reason: str | None = None
    n_songs: int = 0
    n_pooled: int = 0
    finite: bool = True
    scoring_semantics_version: int = SCORING_SEMANTICS_VERSION
    reference_corpus_hash: str | None = None
    threshold: float | None = None

    @property
    def config_key(self) -> str:
        """Application identity (``run_id`` excluded). Canonical rows only."""
        return head_phase_config_key(
            config_id=self.config_id,
            backbone=self.backbone,
            head=self.head,
            bin_mode=self.bin_mode,
            threshold_configured=self.threshold_configured,
            threshold_effective=self.threshold_effective,
            semantics=self.semantics,
            boundary_source=self.boundary_source,
            head_pool_variant=self.head_pool_variant,
        )

    def to_tuple(self) -> tuple[Any, ...]:
        """Column-order tuple matching :data:`HEAD_PHASE_PROVENANCE_COLUMNS`."""
        return (
            self.run_id,
            self.config_id,
            self.backbone,
            self.head,
            self.bin_mode,
            self.threshold_configured,
            self.threshold_effective,
            self.semantics,
            self.boundary_source,
            self.head_pool_variant,
            self.status,
            self.reason,
            int(self.n_songs),
            int(self.n_pooled),
            (1 if self.finite else 0),
            int(self.scoring_semantics_version),
            self.reference_corpus_hash,
            self.threshold,
        )


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"head-phase row {name} must be a non-empty string; got {value!r}")
    return value


def _is_canonical_fields(row: HeadPhaseProvenanceRow) -> bool:
    return (
        row.config_id is not None
        and row.backbone == "effnet"
        and row.bin_mode in TEMPORAL_BIN_MODES
        and row.threshold_configured is not None
        and row.threshold_effective is not None
        and row.semantics in PTC_SEMANTICS
        and row.boundary_source == BOUNDARY_SOURCE_CATALOG
        and row.head_pool_variant == HEAD_POOL_VARIANT
        and row.threshold is None
    )


def _validate_canonical_row(row: HeadPhaseProvenanceRow) -> None:
    """Raise unless ``row`` is a valid canonical current row."""
    _require_text(row.run_id, "run_id")
    if not _is_canonical_fields(row):
        raise ValueError(
            "canonical current row must satisfy the exact canonical predicate "
            "(effnet, canonical bin_mode/direct-L2 semantics, non-NULL config_id + "
            "configured/effective thresholds, catalog/shared_catalog_boundary, "
            "NULL legacy threshold); "
            f"got run_id={row.run_id!r} config_id={row.config_id!r} backbone={row.backbone!r} "
            f"bin_mode={row.bin_mode!r} semantics={row.semantics!r} threshold={row.threshold!r}"
        )
    _validate_row_fields(row)


def _validate_row_fields(row: HeadPhaseProvenanceRow) -> None:
    if row.boundary_source != BOUNDARY_SOURCE_CATALOG:
        raise ValueError(
            f"head-phase row boundary_source must be {BOUNDARY_SOURCE_CATALOG!r}; "
            f"got {row.boundary_source!r} (CTP cache paths must never be repurposed)"
        )
    if row.head_pool_variant != HEAD_POOL_VARIANT:
        raise ValueError(
            f"head-phase row head_pool_variant must be {HEAD_POOL_VARIANT!r}; got "
            f"{row.head_pool_variant!r} (head-specific segmentation is not a shared-boundary row)"
        )
    if row.status not in _HEAD_PHASE_STATUSES:
        raise ValueError(f"head-phase row status must be one of {sorted(_HEAD_PHASE_STATUSES)}; got {row.status!r}")
    if int(row.n_songs) < 0 or int(row.n_pooled) < 0:
        raise ValueError("head-phase row n_songs/n_pooled must be non-negative")
    if int(row.n_pooled) > int(row.n_songs):
        raise ValueError(f"head-phase row n_pooled ({row.n_pooled}) cannot exceed n_songs ({row.n_songs})")
    if int(row.scoring_semantics_version) < 0:
        raise ValueError("head-phase row scoring_semantics_version must be non-negative")


def _transaction(con):
    """Small context manager around an explicit DuckDB transaction."""

    class _Ctx:
        def __enter__(self):
            con.execute("BEGIN TRANSACTION")
            return con

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                con.execute("COMMIT")
            else:
                with contextlib.suppress(Exception):
                    con.execute("ROLLBACK")
            return False

    return _Ctx()


def write_head_phase_provenance(con, rows: Iterable[HeadPhaseProvenanceRow]) -> None:
    """Persist **canonical current** rows (transactional, replace-same-identity).

    Re-validates every row (canonical shape, fixed boundary/variant labels,
    finite/range counts).  Incoming duplicate canonical identities are rejected with
    ``ValueError``.  For each identity the prior canonical row is replaced inside the SAME
    transaction as the insert.  A missing/non-shaped table or any DB error rolls back
    atomically.
    """
    materialized = [r if isinstance(r, HeadPhaseProvenanceRow) else HeadPhaseProvenanceRow(**dict(r)) for r in rows]
    if not materialized:
        return
    for r in materialized:
        _validate_canonical_row(r)
    seen: dict[str, HeadPhaseProvenanceRow] = {}
    for r in materialized:
        key = r.config_key
        if key in seen:
            raise ValueError(
                f"duplicate canonical head-phase identity {key!r} among incoming rows "
                "(run_id excluded from identity); a rerun must replace, not duplicate"
            )
        seen[key] = r
    cols = ", ".join(HEAD_PHASE_PROVENANCE_COLUMNS)
    placeholders = ", ".join("?" for _ in HEAD_PHASE_PROVENANCE_COLUMNS)
    with _transaction(con):
        for r in seen.values():
            con.execute(
                "DELETE FROM head_phase_provenance WHERE "
                "config_id = ? AND backbone = ? AND head = ? AND bin_mode = ? "
                "AND threshold_configured = ? AND threshold_effective = ? AND semantics = ? "
                "AND boundary_source = ? AND head_pool_variant = ?",
                (
                    r.config_id,
                    r.backbone,
                    r.head,
                    r.bin_mode,
                    r.threshold_configured,
                    r.threshold_effective,
                    r.semantics,
                    r.boundary_source,
                    r.head_pool_variant,
                ),
            )
        con.executemany(
            f"INSERT INTO head_phase_provenance ({cols}) VALUES ({placeholders})",
            [r.to_tuple() for r in seen.values()],
        )


def build_head_phase_provenance_rows(
    manifest: Any,
    reference_corpus_hash: str | None = None,
) -> list[HeadPhaseProvenanceRow]:
    """Convert a canonical :class:`HeadAnalysisManifest` to canonical current rows.

    Each ``manifest.results`` record (a ``common.head_analysis.HeadAnalysisConfigRecord``)
    becomes one canonical row keyed by its config identity, with the manifest's ``run_id``
    and scoring-semantics version.
    """
    return [
        HeadPhaseProvenanceRow(
            run_id=manifest.run_id,
            config_id=rec.config_id,
            backbone=rec.backbone,
            head=rec.head,
            bin_mode=rec.bin_mode,
            threshold_configured=rec.threshold_configured,
            threshold_effective=rec.threshold_effective,
            semantics=rec.semantics,
            boundary_source=rec.boundary_source,
            head_pool_variant=rec.head_pool_variant,
            status=rec.status,
            reason=rec.reason or None,
            n_songs=rec.n_songs,
            n_pooled=rec.n_pooled,
            finite=bool(rec.finite),
            scoring_semantics_version=manifest.scoring_semantics_version,
            reference_corpus_hash=reference_corpus_hash,
            threshold=None,
        )
        for rec in manifest.results
    ]


def _from_row_tuple(values: tuple[Any, ...]) -> HeadPhaseProvenanceRow:
    return HeadPhaseProvenanceRow(
        run_id=str(values[0]),
        config_id=(int(values[1]) if values[1] is not None else None),
        backbone=str(values[2]),
        head=str(values[3]),
        bin_mode=str(values[4]),
        threshold_configured=(float(values[5]) if values[5] is not None else None),
        threshold_effective=(float(values[6]) if values[6] is not None else None),
        semantics=(str(values[7]) if values[7] is not None else None),
        boundary_source=str(values[8]),
        head_pool_variant=str(values[9]),
        status=str(values[10]),
        reason=(str(values[11]) if values[11] is not None else None),
        n_songs=int(values[12]),
        n_pooled=int(values[13]),
        finite=bool(values[14]),
        scoring_semantics_version=int(values[15]),
        reference_corpus_hash=(str(values[16]) if values[16] is not None else None),
        threshold=(float(values[17]) if values[17] is not None else None),
    )


def load_head_phase_provenance(con) -> list[HeadPhaseProvenanceRow]:
    """Load the **canonical current** rows (exact canonical predicate), ordered.

    Any historical/unclassified row is preserved in the table but excluded here.  Used by
    the coverage report / readers / fixtures.
    """
    rows = con.execute(
        f"SELECT {_COLUMNS_SQL} FROM {HEAD_PHASE_TABLE} "
        f"WHERE {CANONICAL_HEAD_PHASE_WHERE} "
        "ORDER BY config_id, backbone, head, bin_mode"
    ).fetchall()
    return [_from_row_tuple(tuple(r)) for r in rows]
