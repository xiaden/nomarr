"""
DuckDB schema, connection management, and DDL for the embedding research DB.

Tables (13 total)
-----------------
The obsolete copied-vector / threshold / stratification tables that earlier corrective
passes (P1-S5 Wave 1 / Wave 2a) stripped their writers and readers from are now PHYSICALLY
REMOVED (Plan E P1-S5 Wave 2b): ``pooled_vecs``, ``head_results``, ``head_agreement_rows``,
``patch_features``, ``binned_pair_sims``, ``binned_classify_ctp``, ``binned_song_stats``,
``truncation_robustness_rows``, ``binned_ctp_vecs``, ``binned_ptc_ctp_metrics``,
``head_sim_corr_rows``, ``binned_calibration``, and ``stratified_corpus`` (the sole
``db/stratify.py`` writer/reader was deleted with a zero-caller proof).  No replacement or
compatibility DDL is introduced; their canary/schema expectations were dropped.

Committed stream payloads, masks, head payloads, observations, and the geometry
analysis/head evidence tables are the authoritative geometry-era artifacts; there is no
filesystem snapshot format in the geometry pipeline.

ACTIVE — frozen-stream / geometry / provenance + core live-writer tables (primary):
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
  song_patch_geometry       (exact committed geometry identity + BLOB digests; see
                             ``GEOMETRY_COLUMNS``)  -- authoritative geometry rows
  geometry_analysis_records (run_id + the eight geometry axes + metric, value, evidence_json)
                             -- exact semantic analysis evidence, no PK/UNIQUE
  geometry_head_evidence    (run_id + the eight geometry axes + head, segment_id, evidence_json)
                             -- exact head evidence, no PK/UNIQUE
  run_provenance            (run_id, phase, status, started_at, finished_at,
                             input_artifact_hashes, output_artifact_hashes, config_hash,
                             song_count, warning_count, software_versions, command_line,
                             structural_change_summary, retained)  -- no PK/UNIQUE
  corpus_state              (state_version, registered_song_count, eligible_song_count,
                             complete_flag, reconciled_at,
                             reconciliation_status)  -- singleton, no PK/UNIQUE
  songs                     (song_id PK, path, artist, album, title, genre)
  analyze_metrics           (run_id, strategy_key, strategy_type, sim_metric, k, metric,
                             value)  -- run-scoped; no PK/UNIQUE
  song_retrieval_metrics    (strategy_key, sim_metric, k, song_id, ap_k, mrr, recall_k,
                             disc_artist_contrib, disc_genre_contrib, disc_head_contrib)
  head_phase_provenance     (run_id + the eight geometry axes + geometry_semantics_version,
                             scoring_semantics_version, execution_id, head, segment_id,
                             finite, status, refusal)  -- no PK/UNIQUE
  analyze_incomplete_diagnostics (run_id + the eight geometry axes + sim_metric, k,
                             experiment, diagnostic_version, status, reason, metric,
                             missing_song_ids_json, missing_count, missing_digest,
                             evaluation_corpus_hash, evaluation_corpus_count,
                             evaluation_corpus_comparable, baseline_strategy_key,
                             baseline_evaluation_corpus_hash,
                             baseline_evaluation_corpus_count,
                             baseline_evaluation_corpus_comparable, created_at)
                             -- non-metric diagnostics, no PK/UNIQUE; app-scoped
                             replacement by (run_id, geometry_id, evaluation_id, sim_metric)
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

GEOMETRY_TABLE = "song_patch_geometry"
GEOMETRY_COLUMNS: tuple[str, ...] = (
    "geometry_id",
    "song_id",
    "backbone",
    "observation_group_sha256",
    "stream_ref",
    "stream_fingerprint_sha256",
    "stream_payload_sha256",
    "mask_ref",
    "mask_payload_sha256",
    "patch_count",
    "embedding_dim",
    "stream_dtype",
    "stream_format_version",
    "embed_semantics_version",
    "preprocess_fn",
    "preprocess_version",
    "backbone_model_hash",
    "audio_params",
    "provenance_source",
    "provenance_assumption",
    "alignment_token",
    "audio_content_sha256",
    "mask_semantics_version",
    "group_format_version",
    "provenance_identity",
    "geometry_semantics_version",
    "numerical_profile_digest",
    "geometry_blob_byte_length",
    "geometry_blob_sha256",
    "gram_blob",
    "status",
    "writer_run_id",
    "created_at_ms",
    "updated_at_ms",
)

_GEOMETRY_CREATE = """
CREATE TABLE IF NOT EXISTS song_patch_geometry (
    geometry_id TEXT NOT NULL, song_id TEXT NOT NULL, backbone TEXT NOT NULL,
    observation_group_sha256 TEXT NOT NULL, stream_ref TEXT NOT NULL,
    stream_fingerprint_sha256 TEXT NOT NULL, stream_payload_sha256 TEXT NOT NULL,
    mask_ref TEXT NOT NULL, mask_payload_sha256 TEXT NOT NULL, patch_count INTEGER NOT NULL,
    embedding_dim INTEGER NOT NULL, stream_dtype TEXT NOT NULL, stream_format_version TEXT NOT NULL,
    embed_semantics_version INTEGER NOT NULL, preprocess_fn TEXT NOT NULL, preprocess_version TEXT NOT NULL,
    backbone_model_hash TEXT NOT NULL, audio_params TEXT NOT NULL, provenance_source TEXT NOT NULL,
    provenance_assumption TEXT NOT NULL, alignment_token TEXT NOT NULL, audio_content_sha256 TEXT NOT NULL,
    mask_semantics_version TEXT NOT NULL, group_format_version TEXT NOT NULL, provenance_identity TEXT NOT NULL,
    geometry_semantics_version TEXT NOT NULL, numerical_profile_digest TEXT NOT NULL,
    geometry_blob_byte_length BIGINT NOT NULL, geometry_blob_sha256 TEXT NOT NULL, gram_blob BLOB NOT NULL,
    status TEXT NOT NULL, writer_run_id TEXT NOT NULL, created_at_ms BIGINT NOT NULL, updated_at_ms BIGINT NOT NULL
);
"""

_DDL = """
CREATE TABLE IF NOT EXISTS geometry_analysis_records (
    run_id TEXT NOT NULL,
    geometry_id TEXT NOT NULL,
    observation_group_sha256 TEXT NOT NULL,
    geometry_semantics_version TEXT NOT NULL,
    numerical_profile_digest TEXT NOT NULL,
    threshold_id TEXT NOT NULL,
    structural_identity TEXT NOT NULL,
    search_representation_id TEXT NOT NULL,
    evaluation_id TEXT NOT NULL,
    scoring_semantics_version INTEGER NOT NULL,
    execution_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value DOUBLE NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at_ms BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS geometry_head_evidence (
    run_id TEXT NOT NULL,
    geometry_id TEXT NOT NULL,
    observation_group_sha256 TEXT NOT NULL,
    geometry_semantics_version TEXT NOT NULL,
    numerical_profile_digest TEXT NOT NULL,
    threshold_id TEXT NOT NULL,
    structural_identity TEXT NOT NULL,
    search_representation_id TEXT NOT NULL,
    evaluation_id TEXT NOT NULL,
    scoring_semantics_version INTEGER NOT NULL,
    execution_id TEXT NOT NULL,
    head TEXT NOT NULL,
    segment_id INTEGER NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at_ms BIGINT NOT NULL
);

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
-- from garbage collection.  Timestamps are INTEGER milliseconds.
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
    retained                    BOOLEAN NOT NULL DEFAULT FALSE
);

-- Corpus-level post-run state (Plan B Phase 2 base).  SINGLETON: must hold zero-or-one
-- rows; every update verifies that first and raises if the invariant is violated (more
-- than one row = corruption).  NO PK/UNIQUE.  ``reconciled_at`` is INTEGER milliseconds.
CREATE TABLE IF NOT EXISTS corpus_state (
    state_version            INTEGER NOT NULL,
    registered_song_count    INTEGER NOT NULL,
    eligible_song_count      INTEGER NOT NULL,
    complete_flag            BOOLEAN NOT NULL DEFAULT FALSE,
    reconciled_at            BIGINT NOT NULL,
    reconciliation_status    TEXT
);
"""

# -- head_phase_provenance (Plan E, Phase 1 geometry-era sink) ---------------------
# Kept OUT of the monolithic ``_DDL`` so the 16-column definitions live here as the
# single source of truth (``_HPP_COLUMN_DEFS`` feeds ``_HPP_CREATE``).  It has
# NO PRIMARY KEY / UNIQUE / index (DuckDB ART/WAL policy — application identity and
# uniqueness are asserted before commit and rechecked after write).
_HPP_COLUMN_DEFS: tuple[str, ...] = (
    "run_id TEXT NOT NULL",
    "geometry_id TEXT NOT NULL",
    "observation_group_sha256 TEXT NOT NULL",
    "geometry_semantics_version TEXT NOT NULL",
    "numerical_profile_digest TEXT NOT NULL",
    "threshold_id TEXT NOT NULL",
    "structural_identity TEXT NOT NULL",
    "search_representation_id TEXT NOT NULL",
    "evaluation_id TEXT NOT NULL",
    "scoring_semantics_version INTEGER NOT NULL",
    "execution_id TEXT NOT NULL",
    "head TEXT NOT NULL",
    "segment_id INTEGER NOT NULL",
    "finite INTEGER NOT NULL",
    "status TEXT NOT NULL",
    "refusal TEXT NULL",
)

#: ``CREATE TABLE IF NOT EXISTS`` statement for the canonical 16-column table.
_HPP_CREATE = "CREATE TABLE IF NOT EXISTS head_phase_provenance (\n    " + ",\n    ".join(_HPP_COLUMN_DEFS) + "\n);"

# -- analyze_incomplete_diagnostics (geometry era, 29 columns) ------------------
# Durable, report-readable NON-METRIC diagnostics for a non-comparable (skipped)
# geometry representation.  Kept OUT of the monolithic ``_DDL`` so the column
# definitions live here as the single source of truth
# (``_INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS`` feeds ``_INCOMPLETE_DIAGNOSTICS_CREATE``
# and ``db.incomplete_diagnostics.incomplete_diagnostic_columns``).  A row carries the
# complete eleven-field geometry identity, experiment/sim/K, refusal reason and status,
# missing membership/count/digest evidence, the complete evaluation-corpus evidence, and
# the MANDATORY observed-baseline evidence.  It is NEVER an ``analyze_metrics`` row.
# No PRIMARY KEY / UNIQUE / index (DuckDB ART/WAL policy): application-scoped replacement
# is by ``(run_id, geometry_id, evaluation_id, sim_metric)``, preserving unrelated runs.
_INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS: tuple[str, ...] = (
    "run_id                                TEXT NOT NULL",
    "geometry_id                           TEXT NOT NULL",
    "observation_group_sha256                        TEXT NOT NULL",
    "geometry_semantics_version            TEXT NOT NULL",
    "numerical_profile_digest              TEXT NOT NULL",
    "threshold_id                          TEXT NOT NULL",
    "structural_identity                   TEXT NOT NULL",
    "search_representation_id              TEXT NOT NULL",
    "evaluation_id                         TEXT NOT NULL",
    "scoring_semantics_version             INTEGER NOT NULL",
    "execution_id                          TEXT NOT NULL",
    "sim_metric                            TEXT NOT NULL",
    "k                                     INTEGER NOT NULL",
    "experiment                            TEXT NOT NULL",
    "diagnostic_version                    INTEGER NOT NULL",
    "status                                TEXT NOT NULL",
    "reason                                TEXT NOT NULL",
    "metric                                TEXT NOT NULL",
    "evaluation_corpus_hash                TEXT NOT NULL",
    "evaluation_corpus_count               INTEGER NOT NULL",
    "evaluation_corpus_comparable          BOOLEAN NOT NULL",
    "missing_song_ids_json                 TEXT NOT NULL",
    "missing_count                         INTEGER NOT NULL",
    "missing_digest                        TEXT NULL",
    "baseline_strategy_key                 TEXT NOT NULL",
    "baseline_evaluation_corpus_hash       TEXT NOT NULL",
    "baseline_evaluation_corpus_count      INTEGER NOT NULL",
    "baseline_evaluation_corpus_comparable BOOLEAN NOT NULL",
    "created_at                            BIGINT NOT NULL",
)

#: ``CREATE TABLE IF NOT EXISTS`` statement for the diagnostic table.
_INCOMPLETE_DIAGNOSTICS_CREATE = (
    "CREATE TABLE IF NOT EXISTS analyze_incomplete_diagnostics (\n    "
    + ",\n    ".join(_INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS)
    + "\n);"
)


def _table_exists(con, table: str) -> bool:
    row = con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()
    return bool(row and row[0])


def _table_has_column(con, table: str, column: str) -> bool:
    row = con.execute(
        "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
        [table, column],
    ).fetchone()
    return bool(row and row[0])


# ── analyze_metrics (one current run-scoped schema) ──────────────────────────

#: Column definitions for ``analyze_metrics``.  The ``run_id`` column is the row-level
#: realization of the analyze-scope bookkeeping and carries ONE current meaning: the run that
#: produced the row.  There is no partition and no reserved run id — every row is written by
#: a run-scoped caller that supplies the current ``run_id``.  The old four-column PRIMARY KEY was dropped; DuckDB ART/WAL policy
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
    """An incompatible or unexpected primary/analyze schema was detected.

    Raised by :func:`ensure_schema` when an existing ``analyze_metrics`` table cannot be
    treated as the one current run-scoped schema (it predates the ``run_id`` column) and by
    :func:`schema_fingerprint` when the primary geometry schema is missing, mixed, or
    otherwise unexpected. The schema is never repaired in place: the operator explicitly
    resets/recreates it (``run.py reset --scope analysis`` removes disposable analysis
    metadata; re-running the phase then recreates the current schema) before analysis proceeds.
    """


def _ensure_current_analyze_metrics(con) -> None:
    """Create the current ``analyze_metrics`` schema or refuse a pre-cut table.

    * absent table -> create the current run-scoped schema;
    * present CURRENT table (has ``run_id``) -> no-op (``CREATE TABLE IF NOT EXISTS``
      idempotency);
    * present table lacking ``run_id`` (a pre-cut schema) -> raise
      :class:`StaleSchemaError` so the operator explicitly resets/recreates the schema.
    """
    if not _table_exists(con, "analyze_metrics"):
        con.execute(_ANALYZE_METRICS_CREATE)
        return
    if not _table_has_column(con, "analyze_metrics", "run_id"):
        raise StaleSchemaError(
            "analyze_metrics exists without the current run_id column. Refusing to run on it; "
            "reset/recreate explicitly and re-run the phase."
        )
    columns = tuple(
        str(row[0])
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'analyze_metrics' ORDER BY ordinal_position"
        ).fetchall()
    )
    expected = tuple(definition.split()[0] for definition in _ANALYZE_METRICS_COLUMN_DEFS)
    if columns != expected:
        raise StaleSchemaError(
            "analyze_metrics has an unexpected column shape; reset/recreate explicitly and re-run the phase."
        )
    con.execute(_ANALYZE_METRICS_CREATE)


def _require_duckdb() -> None:
    if not _HAS_DUCKDB:
        raise ImportError(
            "duckdb is not installed. Run:\n  pip install -r /workspace/nomarr/scripts/embedding_research/requirements.txt"
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
            "\n  pip install -r /workspace/nomarr/scripts/embedding_research/requirements.txt"
        )


def storage_version_label(value: object) -> str:
    """Return a DuckDB storage-format version metadata value as an opaque LABEL.

    Storage-format version is provenance/audit metadata for the research DB file.
    It is intentionally never parsed or numerically compared against a supported
    range (a hypothetical future 2.x storage value passes through unchanged as a
    label; deciding whether it is compatible is a separately approved follow-up).
    """
    return str(value)


def schema_fingerprint(con) -> str:
    """Return the deterministic fingerprint of the accepted primary schema, refusing drift."""
    import hashlib

    rows = con.execute(
        "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema='main' ORDER BY table_name, ordinal_position"
    ).fetchall()
    actual = tuple(tuple(str(v) for v in row) for row in rows)
    if not any(row[0] == GEOMETRY_TABLE for row in actual):
        raise StaleSchemaError("primary schema is missing song_patch_geometry")
    geometry = tuple(row for row in actual if row[0] == GEOMETRY_TABLE)
    if tuple(row[1] for row in geometry) != GEOMETRY_COLUMNS:
        raise StaleSchemaError("song_patch_geometry schema is pre-cut, mixed, retired, or malformed")
    payload = "\\n".join("|".join(row) for row in actual).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def ensure_schema(con) -> None:
    """Execute the DDL against an already-open connection. Safe to call multiple times.

    Ensures the current run-scoped ``analyze_metrics`` table (creating it when absent, or
    raising :class:`StaleSchemaError` when an incompatible table is present), then the
    monolithic DDL and the two tables owned
    outside the monolithic ``_DDL``: the canonical 16-column ``head_phase_provenance`` table
    and the 29-column ``analyze_incomplete_diagnostics`` table (``_INCOMPLETE_DIAGNOSTICS_CREATE``,
    built from ``_INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS``).  The ``geometry_analysis_records``
    and ``geometry_head_evidence`` tables are defined once in the monolithic ``_DDL``.
    """
    _require_duckdb()
    _ensure_current_analyze_metrics(con)
    con.execute(_DDL)
    con.execute(_GEOMETRY_CREATE)
    con.execute(_HPP_CREATE)
    con.execute(_INCOMPLETE_DIAGNOSTICS_CREATE)
    schema_fingerprint(con)


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
