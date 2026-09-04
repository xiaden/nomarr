"""
DuckDB schema, connection management, and DDL for the embedding research DB.

Tables (26 total)
-----------------
Plan C (Phase 1) makes ``seg_config`` / ``seg_meta`` / ``seg_membership`` the PRIMARY
segmentation schema, replacing the stale copied-threshold PTC vector model (R6). Group
classifications below follow the DD active/archival/dead vocabulary (R14). The DDL of the
obsolete BLOB/vector threshold tables is RETAINED but labeled DEAD: per the Plan A caller
audit they have zero live writers, and physical removal is deliberately deferred to the
explicit Plan E ``cleanup --scope dead`` pass (nothing is silently dropped in this plan).

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
                             complete_flag, latest_catalog_run_id, latest_search_view_hash,
                             reconciled_at, reconciliation_status)  -- singleton, no PK/UNIQUE
  catalog_metadata          (catalog_semantics_version, serialization_version, manifest_version,
                             backbone_set, latest_catalog_run_id, latest_config_ids,
                             reconciled_at)  -- metadata-only singleton, no PK/UNIQUE

Segmentation catalog (Plan C, Phase 1) — PRIMARY segmentation schema:
  seg_config                (config_id INTEGER, backbone, bin_mode, threshold_configured,
                             threshold_effective, semantics, calibration_record,
                             outlier_window, strategy_version, alias_of_config_id,
                             canonical_config_hash, created_at, run_id)
  seg_meta                  (config_id, song_id, seg_id, start_idx, end_idx, member_count,
                             absorbed_outlier_count, weight, medoid_source_patch_idx,
                             segment_signature, created_at)
  seg_membership            (config_id, song_id, seg_id, member_patch_idx,
                             is_absorbed_outlier, membership_version)
  Scalar columns ONLY (no vector/BLOB); NO PRIMARY KEY / UNIQUE (deliberate DuckDB
  ART/WAL policy — application-level uniqueness is asserted before commit and rechecked
  after build). Timestamps are INTEGER milliseconds. ``seg_membership`` is the one
  authoritative membership relation; ``start_idx/end_idx`` are structural report ranges.

ACTIVE — core experiment tables with live writers (unchanged):
  songs                     (song_id PK, path, artist, album, title, genre)
  analyze_metrics           (run_id, strategy_key, strategy_type, sim_metric, k, metric,
                             value)  -- run-scoped; legacy rows run_id='legacy'; no PK/UNIQUE
  song_retrieval_metrics    (strategy_key, sim_metric, k, song_id, ap_k, mrr, recall_k,
                             disc_artist_contrib, disc_genre_contrib, disc_head_contrib)
  stratified_corpus         (config_hash TEXT, song_id TEXT)
  head_phase_provenance     (run_id, config_id, backbone, head, bin_mode,
                             threshold_configured, threshold_effective, semantics,
                             boundary_source, head_pool_variant, status, reason,
                             n_songs, n_pooled, finite, scoring_semantics_version,
                             reference_corpus_hash, threshold)  -- 18-col, no PK/UNIQUE;
                             canonical current + read-only legacy archival rows
  phase_timings             (run_ts, phase, elapsed_s)

DEAD — obsolete copied-vector / threshold tables (DDL'd, zero live writers per the Plan A
caller audit; DDL retained pending the explicit Plan E cleanup pass, never a primary input):
  pooled_vecs, head_results, binned_calibration, binned_song_stats, head_agreement_rows,
  patch_features, binned_pair_sims, binned_classify_ctp, truncation_robustness_rows,
  binned_ctp_vecs, binned_ptc_ctp_metrics, head_sim_corr_rows
"""

from __future__ import annotations

from contextlib import contextmanager, suppress

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

CREATE TABLE IF NOT EXISTS pooled_vecs (
    song_id  TEXT NOT NULL,
    backbone TEXT NOT NULL,
    strategy TEXT NOT NULL,
    vec      FLOAT[] NOT NULL,
    PRIMARY KEY (song_id, backbone, strategy)
);

CREATE TABLE IF NOT EXISTS head_results (
    song_id  TEXT NOT NULL,
    backbone TEXT NOT NULL,
    head     TEXT NOT NULL,
    strategy TEXT NOT NULL,
    pathway  TEXT NOT NULL,   -- 'ptc' or 'ctp'
    act      FLOAT[] NOT NULL, -- softmax probabilities [p0, p1]
    PRIMARY KEY (song_id, backbone, head, strategy, pathway)
);

-- ── Binned-embedding tables ───────────────────────────────────────────────────

-- Per-backbone threshold calibration: empirical percentiles of pairwise
-- patch distances so we can choose data-driven thresholds.
-- dist_mode values are 'temporal_global' | 'temporal_perdim'
CREATE TABLE IF NOT EXISTS binned_calibration (
    backbone      TEXT NOT NULL,
    dist_mode     TEXT NOT NULL,   -- 'temporal_global' | 'temporal_perdim'
    p10           DOUBLE,
    p25           DOUBLE,
    p50           DOUBLE,
    p75           DOUBLE,
    mean_d        DOUBLE,
    sigma_d       DOUBLE,
    n_patches     INTEGER,
    PRIMARY KEY (backbone, dist_mode)
);


-- Fraction of songs where binned weighted-majority head decision matches
-- the baseline PTC/median single-vector decision.
CREATE TABLE IF NOT EXISTS head_agreement_rows (
    backbone       TEXT NOT NULL,
    head           TEXT NOT NULL,
    bin_mode       TEXT NOT NULL,
    std_thresh     DOUBLE NOT NULL,
    agreement_rate DOUBLE,
    n_songs        INTEGER,
    PRIMARY KEY (backbone, head, bin_mode, std_thresh)
);

-- Per-patch audio features extracted by librosa, time-aligned to embedding patches.
-- chroma_key = 0-11 (argmax of 12-dim chroma vector at that patch window)
CREATE TABLE IF NOT EXISTS patch_features (
    song_id            TEXT NOT NULL,
    patch_idx          INTEGER NOT NULL,
    rms                FLOAT,
    spectral_centroid  FLOAT,
    onset_strength     FLOAT,
    chroma_key         INTEGER,
    PRIMARY KEY (song_id, patch_idx)
);

-- Per-pair 192-combo sim scores (optional; can be large at full scale).
-- song_a < song_b enforced on write.
-- NOTE: upsert_binned_pair_sims_bulk() exists but is not called in the current pipeline.
CREATE TABLE IF NOT EXISTS binned_pair_sims (
    song_a       TEXT NOT NULL,
    song_b       TEXT NOT NULL,
    backbone     TEXT NOT NULL,
    bin_mode     TEXT NOT NULL,
    std_thresh   DOUBLE NOT NULL,
    rep_a        TEXT NOT NULL,
    rep_b        TEXT NOT NULL,
    sim_metric   TEXT NOT NULL,
    agg_method   TEXT NOT NULL,
    score        FLOAT NOT NULL,
    PRIMARY KEY (song_a, song_b, backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method)
);

-- Per-song structural stats for a given (backbone, bin_mode, std_thresh).
CREATE TABLE IF NOT EXISTS binned_song_stats (
    song_id       TEXT NOT NULL,
    backbone      TEXT NOT NULL,
    bin_mode      TEXT NOT NULL,
    std_thresh    DOUBLE NOT NULL,
    n_bins        INTEGER,
    n_patches     INTEGER,
    n_outliers    INTEGER,
    min_bin_size  INTEGER,
    max_bin_size  INTEGER,
    mean_bin_size FLOAT,
    PRIMARY KEY (song_id, backbone, bin_mode, std_thresh)
);

-- Classify-first CTP-binned head activations.
-- Per (song, head): head is run on every raw patch -> [n_patches, 2] activations,
-- then the positive-class score sequence is STD-DEV-binned (threshold = std_thresh * std(scores)).
-- Each bin stores the mean activation vector over its patches.
CREATE TABLE IF NOT EXISTS binned_classify_ctp (
    song_id     TEXT NOT NULL,
    backbone    TEXT NOT NULL,
    head        TEXT NOT NULL,
    bin_mode    TEXT NOT NULL,
    std_thresh  DOUBLE NOT NULL,
    bin_id      INTEGER NOT NULL,
    act         BLOB NOT NULL,
    weight      INTEGER NOT NULL,
    PRIMARY KEY (song_id, backbone, head, bin_mode, std_thresh, bin_id)
);

CREATE TABLE IF NOT EXISTS truncation_robustness_rows (
    backbone                     TEXT NOT NULL,
    bin_mode                     TEXT NOT NULL,
    std_thresh                   DOUBLE NOT NULL,
    flat_mean_sim                DOUBLE,
    binned_mean_sim              DOUBLE,
    truncation_robustness_delta  DOUBLE,
    PRIMARY KEY (backbone, bin_mode, std_thresh)
);

-- CTP-derived embedding pools.
-- After score-stream segmentation (see binned_classify_ctp), the same segment
-- boundaries (patch indices) are used to pool the raw embedding patches.
-- This produces embedding-space vectors whose boundaries were determined by
-- classifier dynamics rather than embedding-space distance (as in binned_vecs).
-- head           = the head whose score stream drove the segmentation
-- pool_strategy  = 'mean' | 'median' | 'max' | 'min'
CREATE TABLE IF NOT EXISTS binned_ctp_vecs (
    song_id       TEXT NOT NULL,
    backbone      TEXT NOT NULL,
    head          TEXT NOT NULL,
    bin_mode      TEXT NOT NULL,
    std_thresh    DOUBLE NOT NULL,
    bin_id        INTEGER NOT NULL,
    pool_strategy TEXT NOT NULL,
    vec_raw       BLOB NOT NULL,
    vec_norm      BLOB NOT NULL,
    weight        INTEGER NOT NULL,
    outlier_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (song_id, backbone, head, bin_mode, std_thresh, bin_id, pool_strategy)
);


-- PTC-vs-CTP divergence metrics. Per (backbone, bin_mode, std_thresh, head):
--   divergence_mean = mean over songs of |ptc_score - ctp_score|, where each per-song
--                     score is the weighted mean of act[1] over that song's bins.
--   bin_count_var   = variance of CTP per-song bin counts.
--   sim_align_corr  = Pearson correlation between PTC and CTP per-song score vectors.
CREATE TABLE IF NOT EXISTS binned_ptc_ctp_metrics (
    backbone        TEXT NOT NULL,
    bin_mode        TEXT NOT NULL,
    std_thresh      DOUBLE NOT NULL,
    head            TEXT NOT NULL,
    divergence_mean DOUBLE,
    bin_count_var   DOUBLE,
    sim_align_corr  DOUBLE,
    PRIMARY KEY (backbone, bin_mode, std_thresh, head)
);

-- Per-head Spearman rank correlation between pairwise embedding similarity and
-- the absolute difference in that head's activation score between each pair of songs.
-- Positive corr = high-sim songs have similar head scores (bunching in classifier space).
-- Primary quality signal for binned embedding research.
CREATE TABLE IF NOT EXISTS head_sim_corr_rows (
    backbone    TEXT NOT NULL,
    bin_mode    TEXT NOT NULL,
    std_thresh  DOUBLE NOT NULL,
    rep_a       TEXT NOT NULL,
    rep_b       TEXT NOT NULL,
    sim_metric  TEXT NOT NULL,
    agg_method  TEXT NOT NULL,
    k           INTEGER NOT NULL,
    head        TEXT NOT NULL,
    corr        DOUBLE,
    PRIMARY KEY (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, head)
);

-- Elapsed wall-clock time for each pipeline phase.
-- run_ts = ISO-8601 timestamp of the run start; one row per (run, phase).
CREATE TABLE IF NOT EXISTS phase_timings (
    run_ts    TEXT NOT NULL,
    phase     TEXT NOT NULL,
    elapsed_s DOUBLE NOT NULL,
    PRIMARY KEY (run_ts, phase)
);

CREATE TABLE IF NOT EXISTS stratified_corpus (
    config_hash  TEXT NOT NULL,
    song_id      TEXT NOT NULL,
    PRIMARY KEY (config_hash, song_id)
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
-- Fields Plan C owns later (latest_catalog_run_id / latest_search_view_hash) are written
-- empty/NULL now.  ``reconciled_at`` is INTEGER milliseconds.
CREATE TABLE IF NOT EXISTS corpus_state (
    state_version            INTEGER NOT NULL,
    registered_song_count    INTEGER NOT NULL,
    eligible_song_count      INTEGER NOT NULL,
    complete_flag            BOOLEAN NOT NULL DEFAULT FALSE,
    latest_catalog_run_id    TEXT,
    latest_search_view_hash  TEXT,
    reconciled_at            BIGINT NOT NULL,
    reconciliation_status    TEXT
);

-- ── Segmentation catalog (Plan C, Phase 1) ────────────────────────────────────
-- PRIMARY segmentation schema (R6): replaces the stale copied-threshold PTC vector
-- model.  Scalar columns ONLY (no vector/BLOB); NO PRIMARY KEY / UNIQUE constraint
-- (deliberate DuckDB ART/WAL policy — application-level uniqueness is asserted before
-- commit and rechecked after build, per the DD).  Timestamps are INTEGER milliseconds.
-- ``config_id`` is an integer identity allocated by the application.  ``semantics`` is
-- ``direct_l2`` by default; ``std_scaled`` is explicit legacy-fidelity only.  Every row
-- records BOTH thresholds (they are equal for ``direct_l2``).  ``calibration_record`` is
-- the canonical calibration-basis text (literal ``'none'`` when there is no basis).
-- ``alias_of_config_id`` points at an existing canonical config (NULL when unaliased);
-- aliasing never changes identity.  ``canonical_config_hash`` = sha256 over the fixed
-- canonical input ordering (helpers.thresholds.canonical_config_hash).
CREATE TABLE IF NOT EXISTS seg_config (
    config_id              INTEGER NOT NULL,
    backbone               TEXT NOT NULL,
    bin_mode               TEXT NOT NULL,
    threshold_configured   DOUBLE NOT NULL,
    threshold_effective    DOUBLE NOT NULL,
    semantics              TEXT NOT NULL,
    calibration_record     TEXT NOT NULL,
    outlier_window         INTEGER NOT NULL,
    strategy_version       INTEGER NOT NULL,
    alias_of_config_id     INTEGER,
    canonical_config_hash  TEXT NOT NULL,
    created_at             BIGINT NOT NULL,
    run_id                 TEXT NOT NULL
);

-- Per-segment structural metadata within one config/song.  ``start_idx/end_idx`` are
-- STRUCTURAL REPORT RANGES ONLY — exact membership (incl. absorbed outliers) is the
-- ``seg_membership`` relation below and is never reconstructed from a range.  ``weight``
-- is an integer patch weight.  ``medoid_source_patch_idx`` is an OBSERVED source patch
-- index (deterministic smallest-index tie break), never a copied vector (R7).
-- ``segment_signature`` is the per-segment canonical signature text.  No PK/UNIQUE.
CREATE TABLE IF NOT EXISTS seg_meta (
    config_id                 INTEGER NOT NULL,
    song_id                   TEXT NOT NULL,
    seg_id                    INTEGER NOT NULL,
    start_idx                 INTEGER NOT NULL,
    end_idx                   INTEGER NOT NULL,
    member_count              INTEGER NOT NULL,
    absorbed_outlier_count    INTEGER NOT NULL,
    weight                    INTEGER NOT NULL,
    medoid_source_patch_idx   INTEGER NOT NULL,
    segment_signature         TEXT,
    created_at                BIGINT NOT NULL
);

-- The one AUTHORITATIVE membership relation: each source patch index is stored once,
-- including absorbed outliers exactly as used by scoring and head pooling.  Application
-- checks reject duplicate ``(config_id, song_id, seg_id, member_patch_idx)`` rows and
-- reject indices outside the verified frozen source stream.  No PK/UNIQUE.
CREATE TABLE IF NOT EXISTS seg_membership (
    config_id              INTEGER NOT NULL,
    song_id                TEXT NOT NULL,
    seg_id                 INTEGER NOT NULL,
    member_patch_idx       INTEGER NOT NULL,
    is_absorbed_outlier    BOOLEAN NOT NULL,
    membership_version     INTEGER NOT NULL
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
# Kept OUT of the monolithic ``_DDL`` so the backup-first migration below owns its
# lifecycle and there is a single source of truth for the column definitions.  It has
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


def migrate_head_phase_provenance(con) -> int:
    """Backup-first, transactional create-copy-drop-rename to the 18-col superset.

    If ``head_phase_provenance`` is absent, or already carries the ``run_id`` column
    (i.e. already migrated), this is a no-op returning ``0``.  Otherwise it:

    1. Takes a full pre-migration snapshot into ``head_phase_provenance_backup``
       (the recorded backup location) — nothing destructive happens first.
    2. In ONE transaction: creates the 18-col replacement, copies every pre-existing
       row read-only as ``run_id='legacy'`` (legacy ``threshold`` + old provenance
       values retained verbatim, canonical-only fields NULL), drops the old table,
       and renames the replacement into place.
    3. Verifies schema (column count) and readable rows (count preserved and every
       migrated row is a valid legacy archival row) before committing.

    The old six-column PRIMARY KEY is dropped; no new PK/UNIQUE/index is added.
    Returns the number of migrated legacy rows (``0`` when no migration ran).
    """
    _require_duckdb()
    if not _table_exists(con, "head_phase_provenance"):
        return 0
    if _table_has_column(con, "head_phase_provenance", "run_id"):
        return 0
    n_old = int(con.execute("SELECT COUNT(*) FROM head_phase_provenance").fetchone()[0])
    # Backup-first (D2): full snapshot recorded at head_phase_provenance_backup.
    con.execute("CREATE OR REPLACE TABLE head_phase_provenance_backup AS SELECT * FROM head_phase_provenance")
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute("CREATE TABLE head_phase_provenance_new (\n    " + ",\n    ".join(_HPP_COLUMN_DEFS) + "\n)")
        con.execute(
            "INSERT INTO head_phase_provenance_new ("
            "run_id, config_id, backbone, head, bin_mode, threshold_configured, "
            "threshold_effective, semantics, boundary_source, head_pool_variant, "
            "status, reason, n_songs, n_pooled, finite, scoring_semantics_version, "
            "reference_corpus_hash, threshold) "
            "SELECT 'legacy', NULL, backbone, head, bin_mode, NULL, NULL, NULL, "
            "boundary_source, head_pool_variant, status, reason, n_songs, n_pooled, "
            "finite, scoring_semantics_version, reference_corpus_hash, threshold "
            "FROM head_phase_provenance"
        )
        con.execute("DROP TABLE head_phase_provenance")
        con.execute("ALTER TABLE head_phase_provenance_new RENAME TO head_phase_provenance")
        # Post-migration verification (D2) before commit.
        n_cols = int(
            con.execute(
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'head_phase_provenance'"
            ).fetchone()[0]
        )
        n_new = int(con.execute("SELECT COUNT(*) FROM head_phase_provenance").fetchone()[0])
        if n_cols != len(_HPP_COLUMN_DEFS):
            raise RuntimeError(
                f"head_phase_provenance migration column verification failed: {n_cols} "
                f"columns (expected {len(_HPP_COLUMN_DEFS)})"
            )
        if n_new != n_old:
            raise RuntimeError(
                f"head_phase_provenance migration row-preservation verification failed: {n_new} rows (expected {n_old})"
            )
        bad = int(
            con.execute(
                "SELECT COUNT(*) FROM head_phase_provenance WHERE run_id <> 'legacy' OR threshold IS NULL"
            ).fetchone()[0]
        )
        if bad:
            raise RuntimeError(f"head_phase_provenance migration produced {bad} non-legacy/unclassified rows")
        con.execute("COMMIT")
    except Exception:
        with suppress(Exception):
            con.execute("ROLLBACK")
        raise
    return n_old


# ── analyze_metrics run_id migration (Plan E P3-S3) ────────────────────────────

#: Post-migration column definitions for ``analyze_metrics``.  The run_id column is the
#: physical row-level realization of the Plan C/D ``analyze_scope`` bookkeeping: legacy
#: (pre-migration) rows are copied read-only as ``run_id='legacy'`` and every later
#: run-scoped write stamps its own ``run_id``.  The old four-column PRIMARY KEY is dropped;
#: DuckDB ART/WAL policy (like ``head_phase_provenance``) allows no PK/UNIQUE/index on a
#: maintained table — application-level uniqueness is asserted on write within a run_id
#: (see ``db.flat.write_analyze_metrics``: it replaces only its own run scope).  The
#: ``DEFAULT 'legacy'`` keeps un-scoped/legacy writers (and direct fixture inserts) behaving
#: exactly as before migration, tagging their rows as the shared legacy/baseline scope.
_ANALYZE_METRICS_COLUMN_DEFS: tuple[str, ...] = (
    "run_id         TEXT NOT NULL DEFAULT 'legacy'",
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


#: Run_id used for pre-migration (legacy) ``analyze_metrics`` rows.
LEGACY_RUN_ID = "legacy"


def migrate_analyze_metrics_provenance(con) -> int:
    """Backup-first, transactional create-copy-drop-rename adding ``run_id`` to ``analyze_metrics``.

    If ``analyze_metrics`` is absent, or already carries the ``run_id`` column (i.e. already
    migrated), this is a no-op returning ``0``.  Otherwise it:

    1. Takes a full pre-migration snapshot into ``analyze_metrics_backup`` (the recorded
       backup location) — nothing destructive happens first.
    2. In ONE transaction: creates the run_id-annotated replacement, copies every
       pre-existing row read-only as ``run_id='legacy'``, drops the old table (dropping the
       legacy four-column PRIMARY KEY), and renames the replacement into place.
    3. Verifies schema (column count) and readable rows (count preserved and every migrated
       row is a legacy ``run_id='legacy'`` row) before committing.

    No PK/UNIQUE/index is added.  Returns the number of migrated legacy rows (``0`` when no
    migration ran).
    """
    _require_duckdb()
    if not _table_exists(con, "analyze_metrics"):
        return 0
    if _table_has_column(con, "analyze_metrics", "run_id"):
        return 0
    n_old = int(con.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0])
    # Backup-first: full snapshot recorded at analyze_metrics_backup.
    con.execute("CREATE OR REPLACE TABLE analyze_metrics_backup AS SELECT * FROM analyze_metrics")
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute("CREATE TABLE analyze_metrics_new (\n    " + ",\n    ".join(_ANALYZE_METRICS_COLUMN_DEFS) + "\n)")
        con.execute(
            "INSERT INTO analyze_metrics_new (run_id, strategy_key, strategy_type, sim_metric, k, metric, value) "
            "SELECT 'legacy', strategy_key, strategy_type, sim_metric, k, metric, value FROM analyze_metrics"
        )
        con.execute("DROP TABLE analyze_metrics")
        con.execute("ALTER TABLE analyze_metrics_new RENAME TO analyze_metrics")
        # Post-migration verification before commit.
        n_cols = int(
            con.execute(
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'analyze_metrics'"
            ).fetchone()[0]
        )
        n_new = int(con.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0])
        if n_cols != len(_ANALYZE_METRICS_COLUMN_DEFS):
            raise RuntimeError(
                f"analyze_metrics migration column verification failed: {n_cols} columns "
                f"(expected {len(_ANALYZE_METRICS_COLUMN_DEFS)})"
            )
        if n_new != n_old:
            raise RuntimeError(
                f"analyze_metrics migration row-preservation verification failed: {n_new} rows (expected {n_old})"
            )
        bad = int(con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE run_id <> 'legacy'").fetchone()[0])
        if bad:
            raise RuntimeError(f"analyze_metrics migration produced {bad} non-legacy rows")
        con.execute("COMMIT")
    except Exception:
        with suppress(Exception):
            con.execute("ROLLBACK")
        raise
    return n_old


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

    Migrates a legacy-format ``head_phase_provenance`` (backup-first) and then creates
    the 18-column table (``head_phase_provenance`` is owned outside the monolithic
    ``_DDL`` so the migration can replace it atomically).
    """
    _require_duckdb()
    migrate_head_phase_provenance(con)
    migrate_analyze_metrics_provenance(con)
    con.execute(_DDL)
    con.execute(_ANALYZE_METRICS_CREATE)
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
