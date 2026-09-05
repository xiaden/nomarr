"""Durable compact-catalog storage seam (Plan C P1-S3).

This module is the SOLE DDL / connection / column-order home for the durable
FILESYSTEM compact-catalog snapshot tables:

    catalog_metadata, seg_config, catalog_song, seg_meta, run_provenance

These tables live only inside a clean catalog snapshot (``catalogs/<catalog-id>/``
``catalog.duckdb``), written by the producer and durably published by
:func:`publish_catalog_snapshot` (atomic directory rename + ``catalogs/current.json``)
and reopened read-only by :func:`open_current_catalog`.  They are deliberately NOT part of
``research.duckdb``: that disposable database keeps only rebuildable registry/index
rows, corpus metadata/state, research run provenance, and the E-owned dead
copied-vector/CTP/calibration/optimizer/truncation DDL through Plan E (see
``db/_schema.py``).  The old research ``seg_config``/``seg_meta``/``seg_membership``
tables were removed in the corrective pass (P1-S12); nothing here is a second source of
truth for ``research.duckdb``.

Schema posture (DD "Compact snapshot schema" + the corrective parts CONTRACTS.md § C):
scalar columns only; NO DuckDB ``PRIMARY KEY``/``UNIQUE`` constraint anywhere (DuckDB
ART/WAL policy) — application-level duplicate checks and post-build verification
enforce identity.  Timestamps are INTEGER milliseconds (project convention).

``seg_config`` / ``catalog_song`` / ``seg_meta`` column sets EXACTLY match the
P1-S2-pinned constants (``SEG_CONFIG_COLS`` / ``CATALOG_SONG_COLS`` / ``SEG_META_COLS``
in ``tests/test_compact_catalog_scale_weights.py``).  ``catalog_metadata`` and
``run_provenance`` column semantics follow DD L209 / L213 and parts CONTRACTS § C.

This module fully implements the durable compact-catalog session: the five-table
DDL/connection/column-order vocabulary, the :class:`CatalogHandle` boundary, the compact-row
/ manifest canonical-serialization primitives, and the completed snapshot lifecycle
(``catalog_metadata`` singleton + duplicate-check hook points the ``catalog.py`` producer
calls, ``publish_catalog_snapshot``, ``open_current_catalog``, and the manifest derive/verify
helpers).  The producer itself lives in ``catalog.py::build_segmentation_catalog``; readers
are the ``compact_*`` helpers there, and ``catalog_report.py`` consumes this seam.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from scripts.embedding_research.helpers import thresholds

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence

    import duckdb

__all__ = [
    "CATALOGS_DIRNAME",
    "CATALOG_CURRENT_FILE",
    "CATALOG_DB_FILE",
    "CATALOG_KIND",
    "CATALOG_MANIFEST_FILE",
    "CATALOG_METADATA_COLS",
    "CATALOG_METADATA_TABLE",
    "CATALOG_SONG_COLS",
    "CATALOG_SONG_TABLE",
    "CATALOG_TABLES",
    "RUN_PROVENANCE_COLS",
    "RUN_PROVENANCE_TABLE",
    "SEG_CONFIG_COLS",
    "SEG_CONFIG_TABLE",
    "SEG_META_COLS",
    "SEG_META_TABLE",
    "CatalogCorruptionError",
    "CatalogHandle",
    "CatalogIncompleteError",
    "CatalogManifest",
    "CatalogMetadataCorruptionError",
    "CatalogMismatchError",
    "CatalogMissingError",
    "CatalogStorageError",
    "CatalogWalError",
    "DuplicateConfigError",
    "DuplicateRunProvenanceError",
    "DuplicateSegmentError",
    "DuplicateSongError",
    "canonical_absorbed_indices",
    "canonical_field_value",
    "canonical_row_text",
    "canonical_rows_text",
    "canonical_sorted_table_rows",
    "catalog_song_row_exists",
    "config_id_exists",
    "connect",
    "derive_catalog_manifest",
    "ensure_catalog_metadata_singleton",
    "ensure_schema",
    "now_ms",
    "open_current_catalog",
    "open_snapshot_file",
    "publish_catalog_snapshot",
    "raise_if_duplicate_canonical_config",
    "raise_if_duplicate_catalog_song",
    "raise_if_duplicate_config",
    "raise_if_duplicate_run_provenance",
    "raise_if_duplicate_seg_meta",
    "seg_meta_row_exists",
    "snapshot_leaf_hashes",
]

#: The intended compact snapshot table set, in canonical creation order.  Mirrors the
#: P1-S2 ``COMPACT_TABLES`` guard: a durable catalog with NO per-patch membership table.
CATALOG_TABLES: Final[tuple[str, ...]] = (
    "catalog_metadata",
    "seg_config",
    "catalog_song",
    "seg_meta",
    "run_provenance",
)

CATALOG_METADATA_TABLE: Final[str] = "catalog_metadata"
SEG_CONFIG_TABLE: Final[str] = "seg_config"
CATALOG_SONG_TABLE: Final[str] = "catalog_song"
SEG_META_TABLE: Final[str] = "seg_meta"
RUN_PROVENANCE_TABLE: Final[str] = "run_provenance"


# --------------------------------------------------------------------------- #
# Column-order vocabulary (the "column-order home" for these tables)           #
# --------------------------------------------------------------------------- #
# seg_config / catalog_song / seg_meta EXACTLY match the P1-S2-pinned constants.
# catalog_metadata / run_provenance column semantics follow DD L209 / L213.

SEG_CONFIG_COLS: Final[tuple[str, ...]] = (
    "config_id",
    "backbone",
    "bin_mode",
    "threshold_configured",
    "threshold_effective",
    "threshold_semantics",
    "outlier_window",
    "strategy_version",
    "canonical_config_hash",
    "run_id",
)

CATALOG_SONG_COLS: Final[tuple[str, ...]] = (
    "config_id",
    "song_id",
    "stream_digest",
    "mask_digest",
    "patch_count",
    "total_searchable_count",
    "exact_leaf",
    "search_leaf",
    "encoder_version",
    "params_id",
    "status",
)

SEG_META_COLS: Final[tuple[str, ...]] = (
    "config_id",
    "song_id",
    "seg_id",
    "start_idx",
    "end_idx",
    "absorbed_indices",
    "absorbed_count",
    "searchable_count",
    "search_medoid_source_patch_idx",
    "searchable_weight",
    "structural_identity",
    "provenance",
)

#: ``catalog_metadata`` (DD L209): a metadata-only SINGLETON (zero-or-one row per
#: snapshot) carrying the format/schema/manifest/serialization and the segmentation,
#: mask, and scoring semantics versions, the building DuckDB/Python/NumPy versions,
#: the catalog ID and resolved input digests, the owning run, and an integer-ms build
#: timestamp.  It never stores a catalog fingerprint (that is manifest-only and
#: non-self-referential).
CATALOG_METADATA_COLS: Final[tuple[str, ...]] = (
    "catalog_id",
    "format_version",
    "schema_version",
    "manifest_version",
    "serialization_version",
    "segmentation_semantics_version",
    "mask_semantics_version",
    "scoring_semantics_version",
    "build_duckdb_version",
    "build_python_version",
    "build_numpy_version",
    "resolved_input_digests",
    "run_id",
    "created_at_ms",
)

#: ``run_provenance`` (DD L213): one or more rows per catalog build recording the phase,
#: status, command, resolved inputs/outputs, content hashes, software versions, warnings,
#: the refusal/reuse decision, and report/run references, with integer-ms lifecycle
#: timestamps.  ``warnings`` is a canonical serialized list; ``resolved_inputs`` /
#: ``resolved_outputs`` / ``content_hashes`` / ``report_run_refs`` are canonical texts.
RUN_PROVENANCE_COLS: Final[tuple[str, ...]] = (
    "run_id",
    "phase",
    "status",
    "command",
    "resolved_inputs",
    "resolved_outputs",
    "content_hashes",
    "software_versions",
    "warning_count",
    "warnings",
    "refusal_reuse_decision",
    "report_run_refs",
    "started_at_ms",
    "finished_at_ms",
)


#: Per-table column specs: table -> (column, DuckDB type incl. nullability).  DDL is
#: generated from this map so the emitted DDL always matches the public column tuples.
_TABLE_COLUMN_SPECS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    CATALOG_METADATA_TABLE: (
        ("catalog_id", "VARCHAR NOT NULL"),
        ("format_version", "INTEGER NOT NULL"),
        ("schema_version", "INTEGER NOT NULL"),
        ("manifest_version", "INTEGER NOT NULL"),
        ("serialization_version", "INTEGER NOT NULL"),
        ("segmentation_semantics_version", "INTEGER NOT NULL"),
        ("mask_semantics_version", "VARCHAR NOT NULL"),
        ("scoring_semantics_version", "INTEGER NOT NULL"),
        ("build_duckdb_version", "VARCHAR NOT NULL"),
        ("build_python_version", "VARCHAR NOT NULL"),
        ("build_numpy_version", "VARCHAR NOT NULL"),
        ("resolved_input_digests", "VARCHAR"),
        ("run_id", "VARCHAR NOT NULL"),
        ("created_at_ms", "BIGINT NOT NULL"),
    ),
    SEG_CONFIG_TABLE: (
        ("config_id", "INTEGER NOT NULL"),
        ("backbone", "VARCHAR NOT NULL"),
        ("bin_mode", "VARCHAR NOT NULL"),
        ("threshold_configured", "DOUBLE NOT NULL"),
        ("threshold_effective", "DOUBLE NOT NULL"),
        ("threshold_semantics", "VARCHAR NOT NULL"),
        ("outlier_window", "INTEGER NOT NULL"),
        ("strategy_version", "INTEGER NOT NULL"),
        ("canonical_config_hash", "VARCHAR NOT NULL"),
        ("run_id", "VARCHAR NOT NULL"),
    ),
    CATALOG_SONG_TABLE: (
        ("config_id", "INTEGER NOT NULL"),
        ("song_id", "VARCHAR NOT NULL"),
        ("stream_digest", "VARCHAR NOT NULL"),
        ("mask_digest", "VARCHAR NOT NULL"),
        ("patch_count", "INTEGER NOT NULL"),
        ("total_searchable_count", "INTEGER NOT NULL"),
        ("exact_leaf", "VARCHAR NOT NULL"),
        ("search_leaf", "VARCHAR NOT NULL"),
        ("encoder_version", "VARCHAR NOT NULL"),
        ("params_id", "VARCHAR NOT NULL"),
        ("status", "VARCHAR NOT NULL"),
    ),
    SEG_META_TABLE: (
        ("config_id", "INTEGER NOT NULL"),
        ("song_id", "VARCHAR NOT NULL"),
        ("seg_id", "INTEGER NOT NULL"),
        ("start_idx", "INTEGER NOT NULL"),
        ("end_idx", "INTEGER NOT NULL"),
        ("absorbed_indices", "VARCHAR NOT NULL"),
        ("absorbed_count", "INTEGER NOT NULL"),
        ("searchable_count", "INTEGER NOT NULL"),
        ("search_medoid_source_patch_idx", "INTEGER"),
        ("searchable_weight", "DOUBLE NOT NULL"),
        ("structural_identity", "VARCHAR NOT NULL"),
        ("provenance", "VARCHAR"),
    ),
    RUN_PROVENANCE_TABLE: (
        ("run_id", "VARCHAR NOT NULL"),
        ("phase", "VARCHAR NOT NULL"),
        ("status", "VARCHAR NOT NULL"),
        ("command", "VARCHAR NOT NULL"),
        ("resolved_inputs", "VARCHAR"),
        ("resolved_outputs", "VARCHAR"),
        ("content_hashes", "VARCHAR"),
        ("software_versions", "VARCHAR"),
        ("warning_count", "INTEGER NOT NULL"),
        ("warnings", "VARCHAR"),
        ("refusal_reuse_decision", "VARCHAR"),
        ("report_run_refs", "VARCHAR"),
        ("started_at_ms", "BIGINT NOT NULL"),
        ("finished_at_ms", "BIGINT"),
    ),
}


def _require_duckdb() -> None:
    """Fail loudly when duckdb is unavailable (imported lazily so the module imports clean)."""
    import importlib

    try:
        importlib.import_module("duckdb")
    except ImportError as exc:  # pragma: no cover - exercised only without duckdb installed
        raise ImportError(
            "duckdb is not installed; run:\n  pip install -r scripts/embedding_research/requirements.txt"
        ) from exc


# --------------------------------------------------------------------------- #
# DDL / connection home                                                         #
# --------------------------------------------------------------------------- #


def _create_statements() -> tuple[str, ...]:
    """Return one ``CREATE TABLE IF NOT EXISTS`` statement per compact snapshot table.

    The emitted DDL is generated from :data:`_TABLE_COLUMN_SPECS`, so the on-disk column
    set always matches the public column-order tuples.  No ``PRIMARY KEY`` / ``UNIQUE`` /
    index clause is emitted anywhere (DuckDB ART/WAL policy).
    """
    statements: list[str] = []
    for table in CATALOG_TABLES:
        cols = ",\n    ".join(f"{col} {coltype}" for col, coltype in _TABLE_COLUMN_SPECS[table])
        statements.append(f"CREATE TABLE IF NOT EXISTS {table} (\n    {cols}\n);")
    return tuple(statements)


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the five compact snapshot tables on an open connection.

    Safe to call multiple times.  This is the ONLY place the filesystem compact snapshot
    DDL is created; it is intentionally never added to ``research.duckdb``'s schema.
    """
    _require_duckdb()
    for statement in _create_statements():
        con.execute(statement)


@contextmanager
def connect(path: str | Path, *, read_only: bool = False) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Open a connection to a compact catalog snapshot DuckDB file.

    When ``read_only`` is False the snapshot schema is created (``ensure_schema``).  The
    catalog snapshot may live at an arbitrary path; this seam never binds to the
    disposable ``research.duckdb`` (``config.DB_PATH``).
    """
    _require_duckdb()
    import duckdb

    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(Path(path).expanduser().resolve()), read_only=read_only)
    if not read_only:
        ensure_schema(con)
    try:
        yield con
    finally:
        con.close()


def now_ms() -> int:
    """Current wall-clock time as INTEGER milliseconds (project convention)."""
    return int(time.time() * 1000)


# --------------------------------------------------------------------------- #
# CatalogHandle boundary (returned by open_current_catalog & open_snapshot_file) #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, eq=False)
class CatalogHandle:
    """Boundary object for an opened, verified clean compact catalog snapshot.

    ``open_current_catalog`` returns this handle for the current published snapshot; the
    lower-level :func:`open_snapshot_file` returns the same handle type for an arbitrary
    snapshot file.  It carries the catalog's identity (``catalog_id``), the catalog
    directory ``root`` (containing the opened ``catalog.duckdb`` and its published
    ``catalog.manifest.json``), and a read-only connection ``con`` to the snapshot DuckDB
    whose schema is this module's five tables.

    The open/verify lifecycle for a *current* catalog is implemented in
    :func:`open_current_catalog`; row readers over the compact tables live with the
    ``compact_*`` helpers in ``catalog.py``.  Callers must :meth:`close` the handle to
    release the snapshot connection.

    .. note::
        Equality is deliberately disabled (``eq=False``) because the handle wraps a live
        DuckDB connection object, which has no meaningful value equality.
    """

    catalog_id: str
    root: Path
    con: object

    def __post_init__(self) -> None:
        if not isinstance(self.catalog_id, str) or not self.catalog_id.strip():
            raise ValueError("catalog_id must be non-empty text")
        object.__setattr__(self, "catalog_id", self.catalog_id.strip())
        object.__setattr__(self, "root", Path(self.root))

    def close(self) -> None:
        """Close the underlying snapshot connection (idempotent-safe for callers)."""
        con = self.con
        close = getattr(con, "close", None)
        if close is not None:
            close()


# --------------------------------------------------------------------------- #
# CatalogHandle construction seams                                           #
# --------------------------------------------------------------------------- #
# The compact-backed readers (catalog_identity / search_views /
# common/catalog_analysis / catalog_report) and their fixtures open a built compact
# snapshot and read it back through the rewired modules.  ``open_current_catalog(root, *,
# verify=True)`` owns the full clean-current-catalog lifecycle (refusal of
# missing/incomplete/mismatched/corrupt/WAL-bearing snapshots, ``catalogs/current.json``
# selection, manifest verification).  The lower-level seam below,
# :func:`open_snapshot_file`, opens one catalog.duckdb-style compact snapshot file directly
# into a :class:`CatalogHandle`.  It deliberately does NOT build the verify / current.json
# machinery (``open_current_catalog`` owns that); it only fails loudly when the file is
# absent or lacks the compact ``catalog_metadata`` singleton so a reader cannot silently
# query a non-catalog.


def open_snapshot_file(path: str | Path, *, read_only: bool = False) -> CatalogHandle:
    """Open a built compact snapshot file as a :class:`CatalogHandle` (reader seam).

    ``path`` is the ``catalog.duckdb`` file of a compact snapshot (e.g. a stage built at
    ``output_root/catalogs/.staging-<run_id>/catalog.duckdb`` or a published
    ``catalogs/<catalog-id>/catalog.duckdb``).  The returned handle's ``con`` is a live
    DuckDB connection to that snapshot whose schema is this module's five compact tables;
    callers must :meth:`CatalogHandle.close` it.  ``read_only`` defaults to False
    (matching :func:`connect`) so fixtures that simulate logical drift (``UPDATE`` /
    ``FORCE CHECKPOINT`` / ``EXPORT DATABASE`` for export-import round-trips) may open a
    write connection; reader-only callers may pass ``read_only=True``.

    For the full current-catalog open/verify lifecycle (refusal of unclean state,
    ``current.json`` selection, manifest verification) use ``open_current_catalog(root,
    *, verify=True)`` instead; this seam intentionally bypasses that machinery.
    """
    _require_duckdb()
    import duckdb

    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise CatalogStorageError(f"compact catalog snapshot file not found: {resolved}")
    con = duckdb.connect(str(resolved), read_only=bool(read_only))
    # Derive the handle identity from the snapshot's catalog_metadata singleton when
    # present (the producer records run_id there as a placeholder until
    # publish_catalog_snapshot replaces it with the manifest-derived id); fall back
    # to the parent directory name for an arbitrary opened file.
    try:
        row = con.execute(f"SELECT catalog_id FROM {CATALOG_METADATA_TABLE} ORDER BY catalog_id LIMIT 1").fetchone()
        catalog_id = str(row[0]) if row is not None else resolved.parent.name
    except Exception:  # pragma: no cover - defensive (no catalog_metadata singleton)
        catalog_id = resolved.parent.name
    return CatalogHandle(catalog_id=catalog_id, root=resolved.parent, con=con)


# --------------------------------------------------------------------------- #
# Canonical compact row / manifest serialization primitives                     #
# --------------------------------------------------------------------------- #
# These helpers produce deterministic, unambiguous canonical text that the producer
# (hash preimages: exact/search leaves, config hashes) and publish_catalog_snapshot
# (manifest leaf hashes) build on.
# Encoding is explicit about type tags and numeric/text representation; rows are sorted
# canonically before serialization.  Numeric text reuses helpers.thresholds encoders.


def canonical_field_value(value: object) -> str:
    """Deterministic, self-delimiting canonical text for one scalar DB field value.

    Type-tagged and unambiguous across concatenation:

    * ``None``        -> ``n``
    * ``bool``        -> ``b0`` / ``b1``
    * ``int``         -> ``i<digits>``  (rejects bool and non-int)
    * ``float``       -> ``f<canonical_float>``  (finite only, ``-0.0`` normalized)
    * ``str``         -> ``s<byte_len>:<text>``  (length-prefixed so embedding is safe)

    Anything else raises :class:`TypeError`.  NaN / Infinity are rejected via the
    finite float encoder.
    """
    if value is None:
        return "n"
    if isinstance(value, bool):
        return "b1" if value else "b0"
    if isinstance(value, int):
        return "i" + thresholds.canonical_int(value)
    if isinstance(value, float):
        return "f" + thresholds.canonical_float(value)
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return f"s{len(encoded)}:{value}"
    raise TypeError(f"cannot canonically encode value of type {type(value).__name__}")


def canonical_row_text(row: Mapping[str, object], *, columns: Sequence[str]) -> str:
    """Canonical tagged text for ONE row in ``columns`` order (``col=<encoded>``, ``|``-joined).

    ``row`` must supply every key in ``columns``; unknown keys are ignored so callers can
    pass a superset mapping.  The result is deterministic for a fixed column order and row
    content — the building block the producer uses for canonical structural-row preimages.
    """
    parts: list[str] = []
    for col in columns:
        if col not in row:
            raise KeyError(f"row is missing column {col!r} required for canonical serialization")
        parts.append(f"{col}={canonical_field_value(row[col])}")
    return "|".join(parts)


def canonical_rows_text(
    rows: Sequence[Mapping[str, object]],
    *,
    columns: Sequence[str],
    order_by: Sequence[str] | None = None,
) -> str:
    """Canonical, deterministically SORTED serialization of many rows.

    Rows are sorted by ``order_by`` column values (ascending, using a stable canonical
    key) and then by their full canonical text, so equal-content row sets always serialize
    identically regardless of input order.  Each row renders via :func:`canonical_row_text`;
    rows are joined with ``\\n``.
    """
    ordered = list(rows)
    if order_by:
        keys = list(order_by)
        ordered.sort(key=lambda r: tuple(canonical_field_value(r[k]) for k in keys))
    return "\n".join(canonical_row_text(r, columns=columns) for r in ordered)


def canonical_sorted_table_rows(
    con: duckdb.DuckDBPyConnection,
    table: str,
    *,
    columns: Sequence[str],
    order_by: Sequence[str],
) -> str:
    """Canonical serialization of an entire table, sorted by ``order_by`` (a hash/portability primitive).

    SELECTs the given ``columns`` in order, sorts by ``order_by``, and canonicalizes each
    row.  This is the durable, order-independent text primitive the producer (leaf
    preimages) and publish_catalog_snapshot (manifest hashing) build on; it never depends
    on physical row order.
    """
    col_csv = ", ".join(columns)
    order_csv = ", ".join(order_by)
    rows = con.execute(f"SELECT {col_csv} FROM {table} ORDER BY {order_csv}").fetchall()
    as_maps = [dict(zip(columns, row, strict=True)) for row in rows]
    return canonical_rows_text(as_maps, columns=columns)


def canonical_absorbed_indices(values: Sequence[int]) -> str:
    """Canonical sparse text for a segment's absorbed exception indices (sorted, deduped).

    Renders ``[1,4,7]`` for the exception set ``{7,1,4}``.  Rejects bool / non-int /
    negative entries.  This is the canonical text form used for ``seg_meta.absorbed_indices``
    (the builder writes it; readers parse it back to an ascending int tuple).
    """
    cleaned: list[int] = []
    seen: set[int] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"absorbed indices must be ints; got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"absorbed indices must be non-negative; got {value}")
        if value not in seen:
            seen.add(value)
            cleaned.append(value)
    cleaned.sort()
    return "[" + ",".join(str(v) for v in cleaned) + "]"


# --------------------------------------------------------------------------- #
# Application duplicate-check hooks (no DB PK/UNIQUE per DuckDB ART/WAL policy) #
# --------------------------------------------------------------------------- #
# The compact builder (catalog.py::build_segmentation_catalog) calls these before commit
# to enforce application identity; they are the application-integrity guards (formerly split
# across db/segmentation.py) that this seam owns under the DuckDB ART/WAL no-constraint policy.


class CatalogStorageError(RuntimeError):
    """Base for all compact-catalog application-integrity failures."""


class DuplicateConfigError(CatalogStorageError):
    """Two ``seg_config`` rows collide on an application-unique identity."""


class DuplicateSongError(CatalogStorageError):
    """Two ``catalog_song`` rows collide on ``(config_id, song_id)``."""


class DuplicateSegmentError(CatalogStorageError):
    """Two ``seg_meta`` rows collide on ``(config_id, song_id, seg_id)``."""


class DuplicateRunProvenanceError(CatalogStorageError):
    """Two ``run_provenance`` rows collide on ``(run_id, phase)``."""


class CatalogMetadataCorruptionError(CatalogStorageError):
    """``catalog_metadata`` holds more than one row — the singleton invariant is broken."""


def _exists(con: duckdb.DuckDBPyConnection, table: str, where: str, params: Sequence[object]) -> bool:
    row = con.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", list(params)).fetchone()
    return row is not None


def config_id_exists(con: duckdb.DuckDBPyConnection, config_id: int) -> bool:
    """True when a ``seg_config`` row already carries ``config_id``."""
    return _exists(con, SEG_CONFIG_TABLE, "config_id = ?", [config_id])


def raise_if_duplicate_config(con: duckdb.DuckDBPyConnection, config_id: int) -> None:
    """Reject a duplicate application ``config_id`` (seg_config identity)."""
    if config_id_exists(con, config_id):
        raise DuplicateConfigError(
            f"seg_config already holds config_id={config_id!r}; config ids are application-unique "
            "(no DB PK/UNIQUE per DuckDB ART/WAL policy)"
        )


def canonical_config_hash_in_use(
    con: duckdb.DuckDBPyConnection, canonical_config_hash: str, *, exclude_config_id: int | None = None
) -> bool:
    """True when a distinct ``seg_config`` row carries ``canonical_config_hash``.

    ``exclude_config_id`` permits a full rebuild of the SAME config (delete-then-insert)
    without tripping over its own pending row.
    """
    if exclude_config_id is None:
        return _exists(con, SEG_CONFIG_TABLE, "canonical_config_hash = ?", [canonical_config_hash])
    return _exists(
        con,
        SEG_CONFIG_TABLE,
        "canonical_config_hash = ? AND config_id != ?",
        [canonical_config_hash, exclude_config_id],
    )


def raise_if_duplicate_canonical_config(
    con: duckdb.DuckDBPyConnection, canonical_config_hash: str, *, exclude_config_id: int | None = None
) -> None:
    """Reject a DISTINCT config carrying the same canonical identity.

    Two configs with an equal ``canonical_config_hash`` are the same logical configuration
    and must collapse to one ``config_id`` — never multiply as a second row.
    """
    if canonical_config_hash_in_use(con, canonical_config_hash, exclude_config_id=exclude_config_id):
        raise DuplicateConfigError(
            f"seg_config already holds a DIFFERENT config_id with canonical hash "
            f"{canonical_config_hash!r}; equal canonical identity must collapse to one config_id"
        )


def catalog_song_row_exists(con: duckdb.DuckDBPyConnection, config_id: int, song_id: str) -> bool:
    """True when a ``catalog_song`` row exists for ``(config_id, song_id)``."""
    return _exists(con, CATALOG_SONG_TABLE, "config_id = ? AND song_id = ?", [config_id, song_id])


def raise_if_duplicate_catalog_song(con: duckdb.DuckDBPyConnection, config_id: int, song_id: str) -> None:
    """Reject a duplicate ``catalog_song`` ``(config_id, song_id)`` leaf."""
    if catalog_song_row_exists(con, config_id, song_id):
        raise DuplicateSongError(
            f"catalog_song already holds (config_id={config_id}, song_id={song_id!r}); "
            "the per-config/song leaf is application-unique"
        )


def seg_meta_row_exists(con: duckdb.DuckDBPyConnection, config_id: int, song_id: str, seg_id: int) -> bool:
    """True when a ``seg_meta`` row exists for ``(config_id, song_id, seg_id)``."""
    return _exists(con, SEG_META_TABLE, "config_id = ? AND song_id = ? AND seg_id = ?", [config_id, song_id, seg_id])


def raise_if_duplicate_seg_meta(con: duckdb.DuckDBPyConnection, config_id: int, song_id: str, seg_id: int) -> None:
    """Reject a duplicate segment identity in ``seg_meta``."""
    if seg_meta_row_exists(con, config_id, song_id, seg_id):
        raise DuplicateSegmentError(
            f"seg_meta already holds (config_id={config_id}, song_id={song_id!r}, seg_id={seg_id}); "
            "segment identities are application-unique within a config/song"
        )


def raise_if_duplicate_run_provenance(con: duckdb.DuckDBPyConnection, run_id: str, phase: str) -> None:
    """Reject a duplicate ``run_provenance`` ``(run_id, phase)`` build row."""
    if _exists(con, RUN_PROVENANCE_TABLE, "run_id = ? AND phase = ?", [run_id, phase]):
        raise DuplicateRunProvenanceError(
            f"run_provenance already holds (run_id={run_id!r}, phase={phase!r}); "
            "a snapshot records one provenance row per run/phase"
        )


def ensure_catalog_metadata_singleton(con: duckdb.DuckDBPyConnection) -> None:
    """Assert ``catalog_metadata`` holds zero or one row (never more).

    More than one row is corruption (like ``corpus_state`` in ``research.duckdb``); the
    check raises :class:`CatalogMetadataCorruptionError` rather than silently proceeding.
    """
    count = int(con.execute(f"SELECT count(*) FROM {CATALOG_METADATA_TABLE}").fetchone()[0])
    if count > 1:
        raise CatalogMetadataCorruptionError(
            f"catalog_metadata singleton corrupted: {count} rows present (expected 0 or 1)"
        )


# --------------------------------------------------------------------------- #
# Snapshot publication + current-catalog verification (Plan C P1-S13)          #
# --------------------------------------------------------------------------- #
# The DD durability contract (DD L268-288): a build writes the compact snapshot to
# ``<root>/catalogs/.staging-<run-id>/catalog.duckdb``; publication then CHECKPOINTs and
# clean-closes that file, writes ``catalog.manifest.json`` through a durable write, computes
# the ``catalog_id`` from the canonical manifest content EXCLUDING its own id, atomically
# renames the staging directory to ``catalogs/<catalog_id>/``, and updates
# ``catalogs/current.json`` LAST.  A snapshot with a nonempty sibling WAL is a crash-left /
# still-open catalog and is NEVER published or opened (it is refused, never rebuilt).

CATALOGS_DIRNAME: Final[str] = "catalogs"
CATALOG_DB_FILE: Final[str] = "catalog.duckdb"
CATALOG_MANIFEST_FILE: Final[str] = "catalog.manifest.json"
CATALOG_CURRENT_FILE: Final[str] = "current.json"
CATALOG_KIND: Final[str] = "catalog"


class CatalogMissingError(CatalogStorageError):
    """No ``current.json`` selects a current catalog (nothing has been published)."""


class CatalogIncompleteError(CatalogStorageError):
    """A published catalog is missing required files (``catalog.duckdb`` / manifest / rows)."""


class CatalogWalError(CatalogStorageError):
    """A nonempty sibling ``catalog.duckdb.wal`` makes a snapshot unclean and unavailable."""


class CatalogMismatchError(CatalogStorageError):
    """A snapshot's recorded manifest content disagrees with its live logical state."""


class CatalogCorruptionError(CatalogStorageError):
    """A snapshot is structurally corrupt (malformed ``current.json`` / duplicate metadata)."""


#: The manifest fields whose JSON value is written verbatim (int / text / None).  All are
#: drawn from the compact ``catalog_metadata`` singleton or the manifest header itself.
_MANIFEST_STRING_KEYS: Final[tuple[str, ...]] = (
    "kind",
    "catalog_id",
    "build_duckdb_version",
    "build_python_version",
    "build_numpy_version",
    "mask_semantics_version",
    "resolved_input_digests",
    "run_id",
)
_MANIFEST_INT_KEYS: Final[tuple[str, ...]] = (
    "format_version",
    "schema_version",
    "manifest_version",
    "serialization_version",
    "segmentation_semantics_version",
    "scoring_semantics_version",
    "created_at_ms",
    "catalog_song_rows",
    "seg_config_rows",
    "seg_meta_rows",
    "catalog_metadata_rows",
    "run_provenance_rows",
)

#: The catalog ID is deliberately EXCLUDED from its own preimage (DD L272).  All other
#: canonical manifest content feeds the ``catalog_id``.
_CATALOG_ID_PREIMAGE_EXCLUDE: Final[set[str]] = {"catalog_id"}


@dataclass(frozen=True)
class CatalogManifest:
    """The durable ``catalog.manifest.json`` content for a published catalog snapshot.

    Publication (:func:`publish_catalog_snapshot`) derives the authoritative manifest from the
    staged ``catalog.duckdb`` (its ``catalog_metadata`` singleton, computed logical
    fingerprint / leaf hashes / row counts) and records the derived ``catalog_id``.  The
    manifest is root-relative and portable: it stores NO absolute filesystem path and NO
    DuckDB fingerprint (logical identity is the oracle — WAL/checkpoint rewrites can change
    bytes without changing logical rows).  ``catalog_id`` is the SHA-256 of the canonical
    manifest content excluding its own id, so it is a pure function of the catalog's logical
    content (independent of where the output root lives).
    """

    kind: str = CATALOG_KIND
    catalog_id: str = ""
    format_version: int = 1
    schema_version: int = 1
    manifest_version: int = 1
    serialization_version: int = 1
    segmentation_semantics_version: int = 1
    mask_semantics_version: str = "uint8-searchable-ones"
    scoring_semantics_version: int = 1
    build_duckdb_version: str = ""
    build_python_version: str = ""
    build_numpy_version: str = ""
    resolved_input_digests: str | None = None
    run_id: str = ""
    created_at_ms: int = 0
    catalog_fingerprint: str = ""
    exact_hash: str = ""
    search_hash: str = ""
    catalog_song_rows: int = 0
    seg_config_rows: int = 0
    seg_meta_rows: int = 0
    catalog_metadata_rows: int = 0
    run_provenance_rows: int = 0

    @classmethod
    def from_metadata_row(cls, con, *, fingerprint: str, exact_hash: str, search_hash: str) -> CatalogManifest:
        """Build the manifest from the snapshot's ``catalog_metadata`` singleton + hashes."""
        rows = con.execute(
            f"SELECT {', '.join(CATALOG_METADATA_COLS)} FROM {CATALOG_METADATA_TABLE} ORDER BY created_at_ms"
        ).fetchall()
        if len(rows) != 1:
            raise CatalogMetadataCorruptionError(
                f"catalog_metadata singleton corrupted: {len(rows)} rows (expected exactly 1 to publish)"
            )
        meta = dict(zip(CATALOG_METADATA_COLS, rows[0], strict=True))
        return cls(
            catalog_id=str(meta["catalog_id"]),
            format_version=int(meta["format_version"]),
            schema_version=int(meta["schema_version"]),
            manifest_version=int(meta["manifest_version"]),
            serialization_version=int(meta["serialization_version"]),
            segmentation_semantics_version=int(meta["segmentation_semantics_version"]),
            mask_semantics_version=str(meta["mask_semantics_version"]),
            scoring_semantics_version=int(meta["scoring_semantics_version"]),
            build_duckdb_version=str(meta["build_duckdb_version"]),
            build_python_version=str(meta["build_python_version"]),
            build_numpy_version=str(meta["build_numpy_version"]),
            resolved_input_digests=meta["resolved_input_digests"],
            run_id=str(meta["run_id"]),
            created_at_ms=int(meta["created_at_ms"]),
            catalog_fingerprint=fingerprint,
            exact_hash=exact_hash,
            search_hash=search_hash,
        )

    def to_dict(self) -> dict:
        """The ordered manifest JSON dict (a portable, root-relative content record)."""
        return {
            "kind": self.kind,
            "catalog_id": self.catalog_id,
            "format_version": int(self.format_version),
            "schema_version": int(self.schema_version),
            "manifest_version": int(self.manifest_version),
            "serialization_version": int(self.serialization_version),
            "segmentation_semantics_version": int(self.segmentation_semantics_version),
            "mask_semantics_version": str(self.mask_semantics_version),
            "scoring_semantics_version": int(self.scoring_semantics_version),
            "build_duckdb_version": str(self.build_duckdb_version),
            "build_python_version": str(self.build_python_version),
            "build_numpy_version": str(self.build_numpy_version),
            "resolved_input_digests": self.resolved_input_digests,
            "run_id": self.run_id,
            "created_at_ms": int(self.created_at_ms),
            "catalog_fingerprint": self.catalog_fingerprint,
            "exact_hash": self.exact_hash,
            "search_hash": self.search_hash,
            "catalog_song_rows": int(self.catalog_song_rows),
            "seg_config_rows": int(self.seg_config_rows),
            "seg_meta_rows": int(self.seg_meta_rows),
            "catalog_metadata_rows": int(self.catalog_metadata_rows),
            "run_provenance_rows": int(self.run_provenance_rows),
        }

    def catalog_id_preimage(self) -> str:
        """Canonical manifest content EXCLUDING the manifest's own ``catalog_id``."""
        return json.dumps(
            {k: v for k, v in self.to_dict().items() if k not in _CATALOG_ID_PREIMAGE_EXCLUDE},
            sort_keys=True,
            separators=(",", ":"),
        )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_leaf_hashes(con) -> tuple[str, str]:
    """Deterministic report-level exact/search hashes over the persisted song leaves.

    Independent of physical row order (leaf sets are sorted before hashing) and distinct
    because the exact/search leaves are distinct preimages.  Mirrors the compact producer's
    report hashes (``catalog.py._snapshot_hashes``) so the published manifest agrees with the
    build report.
    """
    rows = con.execute(
        f"SELECT exact_leaf, search_leaf FROM {CATALOG_SONG_TABLE} ORDER BY exact_leaf, search_leaf"
    ).fetchall()
    exact = "\n".join(sorted(str(r[0]) for r in rows))
    search = "\n".join(sorted(str(r[1]) for r in rows))
    return _sha256_text("exact-snapshot\n" + exact), _sha256_text("search-snapshot\n" + search)


def _table_row_counts(con) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in CATALOG_TABLES:
        counts[table] = int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    return counts


def _fsync_path(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _durable_write_bytes(path: Path, data: bytes) -> None:
    """Write *data* to *path* durably (write temp -> fsync -> atomic replace -> fsync dir)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(tmp), str(path))
    _fsync_path(path.parent)


def _durable_write_json(path: Path, obj: object) -> None:
    _durable_write_bytes(path, json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _open_read_only(db_path: Path):
    """Open a read-only DuckDB connection to an existing snapshot file (no schema mutation)."""
    _require_duckdb()
    import duckdb

    return duckdb.connect(str(db_path), read_only=True)


def _catalog_metadata_exists(con) -> bool:
    return con.execute(f"SELECT count(*) FROM {CATALOG_METADATA_TABLE}").fetchone()[0] > 0


def derive_catalog_manifest(con, run_id: str | None = None) -> CatalogManifest:
    """Authoritative manifest content for an OPEN clean snapshot connection."""
    from scripts.embedding_research.catalog_identity import catalog_fingerprint

    metadata_row = con.execute(
        f"SELECT {', '.join(CATALOG_METADATA_COLS)} FROM {CATALOG_METADATA_TABLE} ORDER BY created_at_ms"
    ).fetchone()
    if metadata_row is None:
        raise CatalogIncompleteError("snapshot has no catalog_metadata singleton; cannot derive a manifest")
    meta = dict(zip(CATALOG_METADATA_COLS, metadata_row, strict=True))
    schema_version = int(meta["schema_version"])
    fingerprint = catalog_fingerprint(con, schema_version=schema_version)
    exact_hash, search_hash = snapshot_leaf_hashes(con)
    manifest = CatalogManifest.from_metadata_row(
        con, fingerprint=fingerprint, exact_hash=exact_hash, search_hash=search_hash
    )
    if run_id is not None and run_id != manifest.run_id:
        raise CatalogMismatchError(
            f"requested run_id {run_id!r} does not match the snapshot's recorded run_id {manifest.run_id!r}"
        )
    counts = _table_row_counts(con)
    return CatalogManifest(
        **{
            **manifest.to_dict(),
            "catalog_id": "",
            "catalog_song_rows": counts["catalog_song"],
            "seg_config_rows": counts["seg_config"],
            "seg_meta_rows": counts["seg_meta"],
            "catalog_metadata_rows": counts["catalog_metadata"],
            "run_provenance_rows": counts["run_provenance"],
        }
    )


def publish_catalog_snapshot(staging_dir, *, manifest: CatalogManifest) -> CatalogHandle:
    """Durably publish a staged compact snapshot (DD L272 + L268-288).

    *staging_dir* is ``<root>/catalogs/.staging-<run-id>`` (built by the compact producer).
    Publication refuses a missing DB, a nonempty sibling WAL (crash-left / still-open
    catalog), and any mismatch between the caller-supplied *manifest* and the snapshot's live
    logical state.  A CHECKPOINT + clean close happens BEFORE ``catalog.manifest.json`` is
    written; ``catalog_id`` is derived from the canonical manifest content excluding its own
    id; the staging directory is atomically renamed to ``catalogs/<catalog_id>/``; and
    ``catalogs/current.json`` is updated LAST.  Returns a :class:`CatalogHandle` to the
    published (read-only) catalog — the caller closes it.
    """
    staging = Path(staging_dir)
    catalog_root = staging.parent
    db_path = staging / CATALOG_DB_FILE
    if not db_path.is_file():
        raise CatalogIncompleteError(f"staging snapshot has no {CATALOG_DB_FILE}: {staging}")

    wal_path = staging / f"{CATALOG_DB_FILE}.wal"
    if wal_path.exists() and wal_path.stat().st_size > 0:
        raise CatalogWalError(
            f"refusing to publish {staging}: nonempty sibling {wal_path.name} means the catalog "
            "is crash-left or still open — run a clean CHECKPOINT/close first (never republish)"
        )

    # CHECKPOINT + clean close BEFORE any manifest is written (DD L272).
    _require_duckdb()
    import duckdb

    write_con = duckdb.connect(str(db_path))
    try:
        write_con.execute("CHECKPOINT")
    finally:
        write_con.close()
    if wal_path.exists() and wal_path.stat().st_size > 0:
        raise CatalogWalError(f"staging snapshot {staging} still has a nonempty WAL after checkpoint")

    # Derive the authoritative manifest from the clean snapshot and refuse caller drift.
    read_con = _open_read_only(db_path)
    try:
        authoritative = derive_catalog_manifest(read_con)
    finally:
        read_con.close()

    if manifest.kind != CATALOG_KIND:
        raise CatalogMismatchError(f"manifest kind {manifest.kind!r} != {CATALOG_KIND!r}")
    for key in (
        "schema_version",
        "run_id",
        "catalog_fingerprint",
        "exact_hash",
        "search_hash",
        "seg_config_rows",
        "catalog_song_rows",
        "seg_meta_rows",
    ):
        if getattr(authoritative, key) != getattr(manifest, key):
            raise CatalogMismatchError(
                f"manifest {key} does not match the staged snapshot "
                f"(manifest={getattr(manifest, key)!r}, snapshot={getattr(authoritative, key)!r})"
            )

    catalog_id = _sha256_text(authoritative.catalog_id_preimage())
    if not catalog_id:
        raise CatalogStorageError("derived an empty catalog_id")

    final_manifest = CatalogManifest(**{**authoritative.to_dict(), "catalog_id": catalog_id})
    _durable_write_json(staging / CATALOG_MANIFEST_FILE, final_manifest.to_dict())

    published_dir = catalog_root / catalog_id
    if published_dir.exists():
        raise CatalogStorageError(f"refusing to overwrite existing published catalog directory {published_dir}")
    os.replace(str(staging), str(published_dir))
    _fsync_path(catalog_root)

    # Update current.json LAST: it selects the current catalog but is never the source of truth.
    _durable_write_json(catalog_root / CATALOG_CURRENT_FILE, {"catalog_id": catalog_id})

    con = _open_read_only(published_dir / CATALOG_DB_FILE)
    return CatalogHandle(catalog_id=catalog_id, root=published_dir, con=con)


def _parse_current_catalog(root: Path) -> str:
    """The current ``catalog_id`` selected by ``<root>/catalogs/current.json``."""
    catalogs_dir = Path(root) / CATALOGS_DIRNAME
    current_file = catalogs_dir / CATALOG_CURRENT_FILE
    if not current_file.is_file():
        raise CatalogMissingError(f"no current catalog: {current_file} is absent")
    try:
        payload = json.loads(current_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogCorruptionError(f"current.json is malformed: {exc}") from exc
    if not isinstance(payload, dict) or "catalog_id" not in payload:
        raise CatalogCorruptionError('current.json must hold {"catalog_id": "<id>"}')
    catalog_id = payload["catalog_id"]
    if not isinstance(catalog_id, str) or not catalog_id or catalog_id in (".", "..") or "/" in catalog_id:
        raise CatalogCorruptionError(f"current.json selects an invalid catalog_id {catalog_id!r}")
    return catalog_id


def _catalog_wal_is_nonempty(catalog_dir: Path) -> bool:
    wal = catalog_dir / f"{CATALOG_DB_FILE}.wal"
    return wal.exists() and wal.stat().st_size > 0


def _catalog_structure_errors(con) -> tuple[str, ...]:
    """Structural completeness checks over an open snapshot connection (never rebuilds)."""
    errors: list[str] = []
    try:
        present = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    except Exception as exc:  # pragma: no cover - defensive
        return (f"cannot read snapshot tables: {exc}",)
    missing = [t for t in CATALOG_TABLES if t not in present]
    if missing:
        errors.append("missing compact tables: " + ", ".join(missing))
    metadata_count = int(con.execute(f"SELECT count(*) FROM {CATALOG_METADATA_TABLE}").fetchone()[0])
    if metadata_count != 1:
        errors.append(f"catalog_metadata must hold exactly one row; found {metadata_count}")
    return tuple(errors)


def open_current_catalog(root, *, verify: bool = True) -> CatalogHandle:
    """Open the CURRENT published compact catalog under *root*, refusing any unclean snapshot.

    *root* is the directory that directly contains ``catalogs/`` (i.e. the output root).  The
    current catalog is selected by ``catalogs/current.json`` and lives at
    ``catalogs/<catalog_id>/``.  Opening NEVER rebuilds: a missing/incomplete/WAL-bearing/
    corrupt/mismatched snapshot raises a typed refusal (:class:`CatalogMissingError`,
    :class:`CatalogIncompleteError`, :class:`CatalogWalError`, :class:`CatalogCorruptionError`,
    :class:`CatalogMismatchError`).  When *verify* is true the recorded manifest content is
    cross-checked against the live logical state (fingerprint / leaf hashes / versions / row
    counts / catalog id).  Returns a :class:`CatalogHandle` to the published read-only catalog
    — the caller closes it.
    """
    catalogs_dir = Path(root) / CATALOGS_DIRNAME
    catalog_id = _parse_current_catalog(Path(root))
    catalog_dir = catalogs_dir / catalog_id
    if not catalog_dir.is_dir():
        raise CatalogIncompleteError(f"current catalog directory missing: {catalog_dir}")

    if _catalog_wal_is_nonempty(catalog_dir):
        raise CatalogWalError(
            f"refusing to open {catalog_dir}: nonempty sibling {CATALOG_DB_FILE}.wal means the "
            "catalog was not clean-closed (a read-only analysis never recovers it)"
        )

    db_path = catalog_dir / CATALOG_DB_FILE
    manifest_path = catalog_dir / CATALOG_MANIFEST_FILE
    if not db_path.is_file():
        raise CatalogIncompleteError(f"current catalog {catalog_id} is missing {CATALOG_DB_FILE}")
    if not manifest_path.is_file():
        raise CatalogIncompleteError(f"current catalog {catalog_id} is missing {CATALOG_MANIFEST_FILE}")

    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogCorruptionError(f"catalog.manifest.json is malformed: {exc}") from exc
    if not isinstance(recorded, dict) or recorded.get("kind") != CATALOG_KIND:
        raise CatalogCorruptionError("catalog.manifest.json must be a catalog manifest")
    recorded_id = recorded.get("catalog_id")
    if recorded_id != catalog_id:
        raise CatalogMismatchError(
            f"manifest catalog_id {recorded_id!r} does not match the published directory {catalog_id!r}"
        )

    con = _open_read_only(db_path)
    structure_errors = _catalog_structure_errors(con)
    if structure_errors:
        con.close()
        raise CatalogIncompleteError("current catalog is incomplete: " + "; ".join(structure_errors))

    if verify:
        try:
            authoritative = derive_catalog_manifest(con)
        except Exception as exc:
            con.close()
            raise CatalogCorruptionError(f"cannot derive manifest from current catalog: {exc}") from exc
        mismatch_fields: list[str] = []
        for key in (
            "schema_version",
            "run_id",
            "catalog_fingerprint",
            "exact_hash",
            "search_hash",
            "seg_config_rows",
            "catalog_song_rows",
            "seg_meta_rows",
        ):
            recorded_value = recorded.get(key)
            derived = getattr(authoritative, key)
            if recorded_value != derived:
                mismatch_fields.append(f"{key}: manifest={recorded_value!r} vs snapshot={derived!r}")
        if mismatch_fields:
            con.close()
            raise CatalogMismatchError(
                "current catalog content disagrees with its recorded manifest: " + "; ".join(mismatch_fields)
            )
    return CatalogHandle(catalog_id=catalog_id, root=catalog_dir, con=con)
