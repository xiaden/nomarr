"""
DuckDB schema, connection management, and DDL for the embedding research DB.

Tables (16 total)
-----------------
Flat-embedding pipeline:
  songs                     (song_id PK, path, artist, album, title, genre)
  pooled_vecs               (song_id, backbone, strategy, vec FLOAT[])
  head_results              (song_id, backbone, head, strategy, pathway, act FLOAT[])
  analyze_metrics           (strategy_key, strategy_type, sim_metric, k, metric, value)

Binned-embedding pipeline (one vector per STD-threshold bin per song):
  binned_calibration        (backbone, dist_mode, p10, p25, p50, p75, mean_d, sigma_d,
                             n_patches)
  head_agreement_rows       (backbone, head, bin_mode, std_thresh, agreement_rate,
                             n_songs)
  binned_song_stats         (song_id, backbone, bin_mode, std_thresh, n_bins,
                             n_patches, n_outliers, min_bin_size, max_bin_size,
                             mean_bin_size)
  binned_pair_sims          (song_a, song_b, backbone, bin_mode, std_thresh, rep_a,
                             rep_b, sim_metric, agg_method, score)
  patch_features            (song_id, patch_idx, rms, spectral_centroid,
                             onset_strength, chroma_key)
  binned_classify_ctp       (song_id, backbone, head, bin_mode, std_thresh, bin_id,
                             act BLOB, weight)
  truncation_robustness_rows (backbone, bin_mode, std_thresh, flat_mean_sim,
                              binned_mean_sim, truncation_robustness_delta)

CTP-derived (segment boundaries from classifier score stream, head-specific):
  binned_ctp_vecs           (song_id, backbone, head, bin_mode, std_thresh, bin_id,
                             pool_strategy, vec_raw BLOB, vec_norm BLOB, weight,
                             outlier_count)
  binned_ptc_ctp_metrics    (backbone, bin_mode, std_thresh, head, divergence_mean,
                             bin_count_var, sim_align_corr)
  head_sim_corr_rows        (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric,
                             agg_method, k, head, corr)

Corpus stratification:
  stratified_corpus         (config_hash TEXT, song_id TEXT)

Infrastructure:
  phase_timings             (run_ts, phase, elapsed_s)
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

# Lazy import so the module can be imported without duckdb installed
# (the caller gets an ImportError only when they call connect()).
try:
    import duckdb

    _HAS_DUCKDB = True
except ImportError:
    _HAS_DUCKDB = False

from scripts.embedding_research.config import DB_PATH

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

CREATE TABLE IF NOT EXISTS analyze_metrics (
    strategy_key  TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    sim_metric    TEXT NOT NULL,
    k             INTEGER NOT NULL,
    metric        TEXT NOT NULL,
    value         DOUBLE,
    PRIMARY KEY (strategy_key, sim_metric, k, metric)
);

-- ── Binned-embedding tables ───────────────────────────────────────────────────

-- Per-backbone threshold calibration: empirical percentiles of pairwise
-- patch distances so we can choose data-driven thresholds.
-- dist_mode maps to binned_vecs.bin_mode:
--   'global' → bin_mode='temporal_global'
--   'perdim' → bin_mode='temporal_perdim'
CREATE TABLE IF NOT EXISTS binned_calibration (
    backbone      TEXT NOT NULL,
    dist_mode     TEXT NOT NULL,   -- 'global' | 'perdim'
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
"""


def _require_duckdb() -> None:
    if not _HAS_DUCKDB:
        raise ImportError(
            "duckdb is not installed. Run:\n  pip install -r /workspace/scripts/embedding_research/requirements.txt"
        )


def ensure_schema(con) -> None:
    """Execute the DDL against an already-open connection. Safe to call multiple times."""
    _require_duckdb()
    con.execute(_DDL)


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
        con.execute(_DDL)
    try:
        yield con
    finally:
        con.close()
