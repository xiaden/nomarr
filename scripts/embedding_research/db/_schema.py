"""
DuckDB schema, connection management, and DDL for the embedding research DB.

Tables (10 total)
-----------------
The obsolete copied-vector / threshold / stratification tables that earlier corrective
passes (P1-S5 Wave 1 / Wave 2a) stripped their writers and readers from are now PHYSICALLY
REMOVED (Plan E P1-S5 Wave 2b): ``pooled_vecs``, ``head_results``, ``head_agreement_rows``,
``patch_features``, ``binned_pair_sims``, ``binned_classify_ctp``, ``binned_song_stats``,
``truncation_robustness_rows``, ``binned_ctp_vecs``, ``binned_ptc_ctp_metrics``,
``head_sim_corr_rows``, ``binned_calibration``, and ``stratified_corpus`` (the sole
``db/stratify.py`` writer/reader was deleted with a zero-caller proof).  No replacement or
compatibility DDL is introduced; their canary/schema expectations were dropped.

The DURABLE compact catalog SEGMENTATION tables (``seg_config`` / ``catalog_song`` /
``seg_meta``) live ONLY in the compact filesystem snapshots (``catalog_storage.py``,
``catalogs/<catalog-id>/catalog.duckdb``), never in this ``research.duckdb`` DDL.  The
``run_provenance`` / ``catalog_metadata`` tables DO exist in this DDL (see the ACTIVE list
below) as rebuildable registry/provenance copies; the authoritative catalog payload is the
filesystem snapshot.

ACTIVE — frozen-stream / catalog / provenance + core live-writer tables (primary):
  stream_registry           (song_id, backbone, artifact_ref, patch_count, dim, dtype,
                             format_version, fingerprint_sha256, preprocess_fn,
                             preprocess_version, backbone_model_hash, audio_params,
                             embed_semantics_version, provenance_source,
                             provenance_assumption, status, run_id, created_at, updated_at)
                             -- no PK/UNIQUE
  head_stream_registry      (song_id, backbone, artifact_ref, patch_count, head_ids,
                             dim_by_head, format_version, fingerprint_sha256, preprocess_fn,
                             preprocess_version, backbone_model_hash, alignment_version,
                             status, run_id, created_at, updated_at)  -- no PK/UNIQUE
  run_provenance            (run_id, phase, status, started_at, finished_at,
                             input_artifact_hashes, output_artifact_hashes, config_hash,
                             song_count, warning_count, software_versions, command_line,
                             structural_change_summary, retained, view_refs)  -- no PK/UNIQUE
  corpus_state              (state_version, registered_song_count, eligible_song_count,
                             complete_flag, latest_catalog_run_id,
                             reconciled_at, reconciliation_status)  -- singleton, no PK/UNIQUE
  catalog_metadata          (catalog_semantics_version, serialization_version, manifest_version,
                             backbone_set, latest_catalog_run_id, latest_config_ids,
                             reconciled_at)  -- metadata-only singleton, no PK/UNIQUE
  songs                     (song_id PK, path, artist, album, title, genre)
  analyze_metrics           (run_id, strategy_key, strategy_type, sim_metric, k, metric,
                             value)  -- run-scoped; no PK/UNIQUE
  song_retrieval_metrics    (strategy_key, sim_metric, k, song_id, ap_k, mrr, recall_k,
                             disc_artist_contrib, disc_genre_contrib, disc_head_contrib)
  head_phase_provenance     (run_id, config_id, backbone, head, bin_mode,
                             threshold_configured, threshold_effective, semantics,
                             boundary_source, head_pool_variant, status, reason,
                             n_songs, n_pooled, finite, scoring_semantics_version,
                             reference_corpus_hash, threshold)  -- 18-col, no PK/UNIQUE;
                             canonical current rows only
  phase_timings             (run_ts, phase, elapsed_s)  -- active efficiency source
"""

from __future__ import annotations

from contextlib import contextmanager

# Lazy import so the module can be imported without duckdb installed
# (the caller gets an ImportError only when they call connect()).
try:
    import duckdb

    _HAS_DUCKDB = True
except ImportError:
    _HAS_DUCKDB = False

from typing import TYPE_CHECKING

from scripts.embedding_research.config import DB_PATH

if TYPE_CHECKING:
    from collections.abc import Generator

_DDL = """
CREATE TABLE IF NOT EXISTS songs (
    song_id TEXT PRIMARY KEY,
    path    TEXT NOT NULL,
    artist  TEXT,
    album   TEXT,
    title   TEXT,
    genre   TEXT
);

-- Elapsed wall-clock time for each pipeline phase.
-- run_ts = ISO-8601 timestamp of the run start; one row per (run, phase).
CREATE TABLE IF NOT EXISTS phase_timings (
    run_ts    TEXT NOT NULL,
    phase     TEXT NOT NULL,
    elapsed_s DOUBLE NOT NULL,
    PRIMARY KEY (run_ts, phase)
);

CREATE TABLE IF NOT EXISTS song_retrieval_metrics (
    strategy_key          TEXT    NOT NULL,
    sim_metric            TEXT    NOT NULL,
    k                     INTEGER NOT NULL,
    song_id               TEXT    NOT NULL,
    ap_k                  DOUBLE,
    mrr                   DOUBLE,
    recall_k              DOUBLE,
    disc_artist_contrib   DOUBLE,
    disc_genre_contrib    DOUBLE,
    disc_head_contrib     DOUBLE,
    PRIMARY KEY (strategy_key, sim_metric, k, song_id)
);

-- Frozen observation stream registries (Plan B, Phase 1). A' float32 sidecar
-- payloads + scalar metadata; NO PRIMARY KEY / UNIQUE constraint (deliberate
-- DuckDB ART/WAL policy — application uniqueness is asserted before commit).
-- Logical identity (song_id, backbone) is application-level; artifact_ref is
-- opaque + root-relative (resolved only inside the StreamStore, never a path
-- identity / SQL key). Timestamps are INTEGER milliseconds (project convention).
CREATE TABLE IF NOT EXISTS stream_registry (
    song_id                 TEXT NOT NULL,
    backbone                TEXT NOT NULL,
    artifact_ref            TEXT NOT NULL,
    patch_count             INTEGER NOT NULL,
    dim                     INTEGER NOT NULL,
    dtype                   TEXT NOT NULL,
    format_version          TEXT NOT NULL,
    fingerprint_sha256      TEXT NOT NULL,
    preprocess_fn           TEXT,
    preprocess_version      TEXT,
    backbone_model_hash     TEXT,
    audio_params            TEXT,
    embed_semantics_version INTEGER NOT NULL,
    provenance_source       TEXT NOT NULL,
    provenance_assumption   TEXT,
    status                  TEXT NOT NULL,
    run_id                  TEXT NOT NULL,
    created_at              BIGINT NOT NULL,
    updated_at              BIGINT NOT NULL
);

-- Complete, patch-aligned per-song classifier-head stream registry.
-- Same no-PK/no-UNIQUE policy; identity (song_id, backbone). head_ids and
-- dim_by_head are canonical serialized scalar texts, not an opaque blob.
CREATE TABLE IF NOT EXISTS head_stream_registry (
    song_id                 TEXT NOT NULL,
    backbone                TEXT NOT NULL,
    artifact_ref            TEXT NOT NULL,
    patch_count             INTEGER NOT NULL,
    head_ids                TEXT NOT NULL,
    dim_by_head             TEXT NOT NULL,
    format_version          TEXT NOT NULL,
    fingerprint_sha256      TEXT NOT NULL,
    preprocess_fn           TEXT,
    preprocess_version      TEXT,
    backbone_model_hash     TEXT,
    alignment_version       TEXT NOT NULL,
    status                  TEXT NOT NULL,
    run_id                  TEXT NOT NULL,
    created_at              BIGINT NOT NULL,
    updated_at              BIGINT NOT NULL
);


-- Post-run phase provenance (Plan B Phase 2; Plan C extends usage on this same table).
-- One row per completed phase run.  NO PRIMARY KEY / UNIQUE constraint (application
-- string ``run_id`` + ``phase``; DuckDB ART/WAL policy).  ``retained`` protects a row
-- from manifest/view garbage collection; ``view_refs`` is a root-relative view-ref seed
-- (empty now; Plan D populates it).  Timestamps are INTEGER milliseconds.
CREATE TABLE IF NOT EXISTS run_provenance (
    run_id                      TEXT NOT NULL,
    phase                       TEXT NOT NULL,
    status                      TEXT NOT NULL,
    started_at                  BIGINT NOT NULL,
    finished_at                 BIGINT,
    input_artifact_hashes       TEXT,
    output_artifact_hashes      TEXT,
    config_hash                 TEXT,
    song_count                  INTEGER NOT NULL,
    warning_count               INTEGER NOT NULL,
    software_versions           TEXT,
    command_line                TEXT,
    structural_change_summary   TEXT,
    retained                    BOOLEAN NOT NULL DEFAULT FALSE,
    view_refs                   TEXT
);

-- Corpus-level post-run state (Plan B Phase 2 base; Plan C extends usage on this same
-- table).  SINGLETON: must hold zero-or-one rows; every update verifies that first and
-- raises if the invariant is violated (more than one row = corruption).  NO PK/UNIQUE.
-- Fields Plan C owns later (latest_catalog_run_id) are written
-- empty/NULL now.  ``reconciled_at`` is INTEGER milliseconds.  (The Plan D P1-S2 search-view
-- rework removed the ``latest_search_view_hash`` column: search views are disposable and
-- regenerated per run, so corpus state tracks no durable search-view hash.)
CREATE TABLE IF NOT EXISTS corpus_state (
    state_version            INTEGER NOT NULL,
    registered_song_count    INTEGER NOT NULL,
    eligible_song_count      INTEGER NOT NULL,
    complete_flag            BOOLEAN NOT NULL DEFAULT FALSE,
    latest_catalog_run_id    TEXT,
    reconciled_at            BIGINT NOT NULL,
    reconciliation_status    TEXT
);

-- Catalog-level metadata (Plan C, Phase 4).  A small metadata-only SINGLETON (zero or
-- one row, like corpus_state; more than one is corruption) carrying the identity-relevant
-- catalog semantics / canonical-serialization / manifest versions, the backbone set, and
-- the latest run/config identifiers.  Scalar columns only, NO PRIMARY KEY / UNIQUE
-- (DuckDB ART/WAL policy).  It is included in the manifest and in the logical-state /
-- schema-dump catalog_fingerprint check but is NOT duplicated into row identity.  This
-- table NEVER stores catalog_fingerprint (that value is manifest-only and non-
-- self-referential).  catalog_semantics_version / serialization_version / manifest_version
-- are INTEGER; backbone_set is the sorted, comma-joined canonical backbone text.
CREATE TABLE IF NOT EXISTS catalog_metadata (
    catalog_semantics_version INTEGER NOT NULL,
    serialization_version     INTEGER NOT NULL,
    manifest_version          INTEGER NOT NULL,
    backbone_set              TEXT,
    latest_catalog_run_id     TEXT,
    latest_config_ids         TEXT,
    reconciled_at             BIGINT NOT NULL
);
"""

# -- head_phase_provenance (Plan E, Phase 1 AMEND ROUND 2 — 18-col superset) -----
# Kept OUT of the monolithic ``_DDL`` so the 18-column definitions live here as the
# single source of truth (``_HPP_COLUMN_DEFS`` feeds ``_HPP_CREATE``).  It has
# NO PRIMARY KEY / UNIQUE / index (DuckDB ART/WAL policy — application identity and
# uniqueness are asserted before commit and rechecked after write).
_HPP_COLUMN_DEFS: tuple[str, ...] = (
    "run_id                    TEXT NOT NULL",
    "config_id                 INTEGER NULL",
    "backbone                  TEXT NOT NULL",
    "head                      TEXT NOT NULL",
    "bin_mode                  TEXT NOT NULL",
    "threshold_configured      DOUBLE NULL",
    "threshold_effective       DOUBLE NULL",
    "semantics                 TEXT NULL",
    "boundary_source           TEXT NOT NULL",
    "head_pool_variant         TEXT NOT NULL",
    "status                    TEXT NOT NULL",
    "reason                    TEXT NULL",
    "n_songs                   INTEGER NOT NULL",
    "n_pooled                  INTEGER NOT NULL",
    "finite                    INTEGER NOT NULL",
    "scoring_semantics_version INTEGER NOT NULL",
    "reference_corpus_hash     TEXT NULL",
    "threshold                 DOUBLE NULL",
)

#: ``CREATE TABLE IF NOT EXISTS`` statement for the canonical 18-column table.
_HPP_CREATE = "CREATE TABLE IF NOT EXISTS head_phase_provenance (\n    " + ",\n    ".join(_HPP_COLUMN_DEFS) + "\n);"


def _table_exists(con, table: str) -> bool:
    row = con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()
    return bool(row and row[0])


def _table_has_column(con, table: str, column: str) -> bool:
    row = con.execute(
        "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
        [table, column],
    ).fetchone()
    return bool(row and row[0])


def _column_default(con, table: str, column: str):
    """Return the ``column_default`` for one column, or None when the column is absent.

    DuckDB surfaces a column DEFAULT as its expression string via
    ``information_schema.columns.column_default`` (e.g. ``'legacy'`` for ``DEFAULT
    'legacy'``) and NULL for a column with no default.  Used by the stale-schema refusal
    guard to catch a HEAD-era pre-cut table whose ``run_id`` column still carries a
    ``DEFAULT 'legacy'`` but holds no ``'legacy'`` rows to trip the row-presence check.
    """
    row = con.execute(
        "SELECT column_default FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
        [table, column],
    ).fetchone()
    return row[0] if row else None


# ── analyze_metrics (one current run-scoped schema) ──────────────────────────

#: Column definitions for ``analyze_metrics``.  The ``run_id`` column is the row-level
#: realization of the analyze-scope bookkeeping and carries ONE current meaning: the run that
#: produced the row.  There is no pre-cut / legacy partition, no ``DEFAULT 'legacy'`` and no
#: reserved legacy run id — every row is written by a run-scoped caller that supplies the
#: current ``run_id``.  The old four-column PRIMARY KEY was dropped; DuckDB ART/WAL policy
#: (like ``head_phase_provenance``) allows no PK/UNIQUE/index on a maintained table —
#: application-level uniqueness is asserted on write within a run_id (see
#: ``db.flat.write_analyze_metrics``: it replaces only its own run scope).
_ANALYZE_METRICS_COLUMN_DEFS: tuple[str, ...] = (
    "run_id         TEXT NOT NULL",
    "strategy_key   TEXT NOT NULL",
    "strategy_type  TEXT NOT NULL",
    "sim_metric     TEXT NOT NULL",
    "k              INTEGER NOT NULL",
    "metric         TEXT NOT NULL",
    "value          DOUBLE NULL",
)

#: ``CREATE TABLE IF NOT EXISTS`` statement for the run_id-annotated table.
_ANALYZE_METRICS_CREATE = (
    "CREATE TABLE IF NOT EXISTS analyze_metrics (\n    " + ",\n    ".join(_ANALYZE_METRICS_COLUMN_DEFS) + "\n);"
)


class StaleSchemaError(RuntimeError):
    """A pre-cut (legacy-partitioned) ``analyze_metrics`` schema/table was detected.

    Raised by :func:`ensure_schema` when an existing ``analyze_metrics`` table cannot be
    treated as the ONE current run-scoped schema — either it predates the ``run_id`` column,
    or it carries ``run_id='legacy'`` rows copied by the removed pre-cut migration, or whose
    ``run_id`` column exposes a non-None DEFAULT (a HEAD-era pre-cut shape carrying
    ``DEFAULT 'legacy'`` with no rows to trip the row-presence check).  The corrective hard
    cut REFUSES such a table rather than relabeling/copying its rows into an executable
    legacy partition: the table must be explicitly reset/recreated (``run.py reset --scope
    analysis`` removes the disposable research DB + views; re-running the phase then
    recreates the current schema) before analysis proceeds.
    """


def _ensure_current_analyze_metrics(con) -> None:
    """Create the current ``analyze_metrics`` schema or refuse a stale pre-cut table.

    * absent table -> create the current run-scoped schema;
    * present CURRENT table (has ``run_id`` with no column default, no legacy-partition rows)
      -> no-op (``CREATE TABLE IF NOT EXISTS`` idempotency);
    * present table lacking ``run_id`` (pre-cut), OR containing ``run_id='legacy'`` rows (a
      legacy partition left by the removed pre-cut migration), OR exposing a NON-None
      ``run_id`` column default (a HEAD-era table that has the ``run_id`` column with
      ``DEFAULT 'legacy'`` but no ``'legacy'`` rows to trip the row-presence check) -> raise
      :class:`StaleSchemaError` so the operator explicitly resets/recreates the schema instead
      of silently relabeling stale rows as current or leaving a dormant ``DEFAULT 'legacy'``
      on the live column.
    """
    if not _table_exists(con, "analyze_metrics"):
        con.execute(_ANALYZE_METRICS_CREATE)
        return
    if not _table_has_column(con, "analyze_metrics", "run_id"):
        raise StaleSchemaError(
            "analyze_metrics exists WITHOUT the current run_id column (a pre-cut schema). "
            "Refusing to run on it: the hard cut makes analyze_metrics one current "
            "run-scoped schema with no legacy partition. Reset/recreate explicitly (e.g. "
            "`python run.py reset --scope analysis`, or drop + recreate the DB) and re-run "
            "the phase."
        )
    if _column_default(con, "analyze_metrics", "run_id") is not None:
        raise StaleSchemaError(
            "analyze_metrics has a run_id column with a DEFAULT ('legacy'); the current "
            "hard-cut schema pins run_id with NO default (every row is written by a "
            "run-scoped caller). Refusing to run on it rather than silently accept a dormant "
            "legacy default on the live column. Reset/recreate explicitly (e.g. `python "
            "run.py reset --scope analysis`) and re-run the phase."
        )
    legacy_rows = int(con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE run_id = 'legacy'").fetchone()[0])
    if legacy_rows:
        raise StaleSchemaError(
            "analyze_metrics carries run_id='legacy' rows (a legacy partition copied by the "
            "removed pre-cut migration). Refusing to run on them: old rows are never relabeled "
            "into an executable legacy partition. Reset/recreate explicitly (e.g. `python "
            "run.py reset --scope analysis`) and re-run the phase."
        )
    con.execute(_ANALYZE_METRICS_CREATE)


def _require_duckdb() -> None:
    if not _HAS_DUCKDB:
        raise ImportError(
            "duckdb is not installed. Run:\n  pip install -r /workspace/scripts/embedding_research/requirements.txt"
        )


# Supported duckdb LIBRARY version range (requirements.txt: ``duckdb>=1.5,<2.0``).
# Only the *library* version is gated. DuckDB's on-disk *storage-format* version
# is distinct provenance metadata and is treated as an opaque LABEL here (see
# ``storage_version_label``) — it is never parsed or numerically compared against
# a supported range. A future 2.x storage file is a separately approved follow-up,
# never silently assumed compatible/incompatible off a numeric comparison.
_SUPPORTED_DUCKDB_MIN: tuple[int, int] = (1, 5)
_SUPPORTED_DUCKDB_MAX_EXCLUSIVE: tuple[int, int] = (2, 0)


def _duckdb_version_tuple() -> tuple[int, int]:
    """Return ``(major, minor)`` of the installed duckdb library version.

    Raises RuntimeError if duckdb is absent or the version string is not
    ``<major>.<minor>...`` numeric (an unknown/unparseable release is not
    assumed safe).
    """
    _require_duckdb()
    raw = getattr(duckdb, "__version__", "")
    try:
        parts = [int(part) for part in str(raw).split(".")[:2]]
    except ValueError as exc:  # pragma: no cover - non-numeric duckdb version
        raise RuntimeError(f"Cannot parse duckdb version {raw!r}") from exc
    if len(parts) != 2:
        raise RuntimeError(f"Unexpected duckdb version format {raw!r}")
    return parts[0], parts[1]  # type: ignore[return-value]


def require_supported_duckdb() -> None:
    """Assert the installed duckdb LIBRARY version satisfies ``1.5 <= v < 2.0``.

    Called at the research CLI entry points (``run.py`` ``main()`` and
    ``generate_fixture_report.py`` ``main()``) before any DB work, not inside
    ``connect()``. Fails loudly (RuntimeError) for duckdb outside the supported
    range — e.g. the
    stale ``>=0.10.0`` era or a hypothetical future 2.x — so unsupported-version
    runs never silently proceed on an untested storage format.

    Note: this gates the *library* version only. DuckDB *storage-format* version
    metadata is recorded as a label (``storage_version_label``), never compared
    numerically here.
    """
    _require_duckdb()
    version = _duckdb_version_tuple()
    if not (_SUPPORTED_DUCKDB_MIN <= version < _SUPPORTED_DUCKDB_MAX_EXCLUSIVE):
        raise RuntimeError(
            f"Unsupported duckdb version {duckdb.__version__!r}: this research package requires "
            f"duckdb >=1.5,<2.0 (got {version[0]}.{version[1]}). Install a supported release:"
            "\n  pip install -r /workspace/scripts/embedding_research/requirements.txt"
        )


def storage_version_label(value: object) -> str:
    """Return a DuckDB storage-format version metadata value as an opaque LABEL.

    Storage-format version is provenance/audit metadata for the research DB file.
    It is intentionally never parsed or numerically compared against a supported
    range (a hypothetical future 2.x storage value passes through unchanged as a
    label; deciding whether it is compatible is a separately approved follow-up).
    """
    return str(value)


def ensure_schema(con) -> None:
    """Execute the DDL against an already-open connection. Safe to call multiple times.

    Ensures the current run-scoped ``analyze_metrics`` table (creating it when absent, or
    raising :class:`StaleSchemaError` when a stale pre-cut / legacy-partitioned table is
    present — never relabeling old rows), then the monolithic DDL and the canonical 18-column
    ``head_phase_provenance`` table (owned outside the monolithic ``_DDL``).
    """
    _require_duckdb()
    _ensure_current_analyze_metrics(con)
    con.execute(_DDL)
    con.execute(_HPP_CREATE)


def upsert_phase_timing(con, run_ts: str, phase: str, elapsed_s: float) -> None:
    """Record or update the elapsed wall-clock time for one pipeline phase."""
    _require_duckdb()
    con.execute(
        """INSERT INTO phase_timings (run_ts, phase, elapsed_s) VALUES (?, ?, ?)
           ON CONFLICT (run_ts, phase) DO UPDATE SET elapsed_s = excluded.elapsed_s""",
        [run_ts, phase, elapsed_s],
    )


@contextmanager
def connect(read_only: bool = False) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Open a connection to the research database.

    Args:
        read_only: When True, opens DuckDB in read-only mode and skips DDL.
            Useful while a long-running writer process is active.
    """
    _require_duckdb()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if not read_only:
        ensure_schema(con)
    try:
        yield con
    finally:
        con.close()
