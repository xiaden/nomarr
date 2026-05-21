"""
DuckDB schema, connection management, and DDL for the embedding research DB.

Tables (20 total)
-----------------
Flat-embedding pipeline:
  songs                     (song_id PK, path, artist, album, title, genre)
  pooled_vecs               (song_id, backbone, strategy, vec FLOAT[])
  head_results              (song_id, backbone, head, strategy, pathway, act FLOAT[])
  retrieval_rows            (backbone, strategy, sim_metric, k, map_k, mrr, ndcg_k,
                             recall_k, disc_score, mean_within, mean_cross,
                             disc_artist, disc_album, disc_genre, disc_head)
  ann_rows                  (backbone, strategy, ef_search, recall_k, backend)
  ptc_ctp_rows              (backbone, head, strategy, ptc_disc, ctp_disc, delta_disc,
                             ptc_map, ctp_map, delta_map)

Binned-embedding pipeline (one vector per STD-threshold bin per song):
  binned_calibration        (backbone, dist_mode, p10, p25, p50, p75, mean_d, sigma_d,
                             n_patches)
  binned_vecs               (song_id, backbone, bin_mode, std_thresh, bin_id,
                             pool_strategy, vec_raw BLOB, vec_norm BLOB, weight,
                             outlier_count)
  binned_head_results       (song_id, backbone, head, bin_mode, std_thresh, bin_id,
                             act BLOB, weight)
  binned_retrieval_rows     (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric,
                             agg_method, k, disc_score, map_k, mrr, ndcg_k, recall_k,
                             mean_within, mean_cross, disc_artist, disc_album,
                             disc_genre, disc_head)
  head_agreement_rows       (backbone, head, bin_mode, std_thresh, agreement_rate,
                             n_songs)
  binned_song_stats         (song_id, backbone, bin_mode, std_thresh, n_bins,
                             n_patches, n_outliers, min_bin_size, max_bin_size,
                             mean_bin_size, bin_div_std)
  binned_pair_sims          (song_a, song_b, backbone, bin_mode, std_thresh, rep_a,
                             rep_b, sim_metric, agg_method, score)
  patch_features            (song_id, patch_idx, rms, spectral_centroid,
                             onset_strength, chroma_key)
  binned_classify_ctp       (song_id, backbone, head, bin_mode, std_thresh, bin_id,
                             act BLOB, weight)

CTP-derived (segment boundaries from classifier score stream, head-specific):
  binned_ctp_vecs           (song_id, backbone, head, bin_mode, std_thresh, bin_id,
                             pool_strategy, vec_raw BLOB, vec_norm BLOB, weight,
                             outlier_count)
  binned_ctp_retrieval_rows (backbone, head, bin_mode, std_thresh, rep_a, rep_b,
                             sim_metric, agg_method, k, + same metrics as
                             binned_retrieval_rows)
  binned_ptc_ctp_metrics    (backbone, bin_mode, std_thresh, head, divergence_mean,
                             bin_count_var, sim_align_corr)
  head_sim_corr_rows        (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric,
                             agg_method, k, head, corr)

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

from ..config import DB_PATH

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

CREATE TABLE IF NOT EXISTS retrieval_rows (
    backbone    TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    sim_metric  TEXT NOT NULL,
    k           INTEGER NOT NULL,
    map_k       DOUBLE,
    mrr         DOUBLE,
    ndcg_k      DOUBLE,
    recall_k    DOUBLE,
    recall_k_album DOUBLE,
    recall_k_genre DOUBLE,
    disc_score  DOUBLE,
    mean_within DOUBLE,
    mean_cross  DOUBLE,
    disc_artist DOUBLE,
    disc_album  DOUBLE,
    disc_genre  DOUBLE,
    disc_head   DOUBLE,
    PRIMARY KEY (backbone, strategy, sim_metric, k)
);

CREATE TABLE IF NOT EXISTS ann_rows (
    backbone   TEXT NOT NULL,
    strategy   TEXT NOT NULL,
    ef_search  INTEGER NOT NULL,
    recall_k   DOUBLE,
    backend    TEXT,
    PRIMARY KEY (backbone, strategy, ef_search)
);

CREATE TABLE IF NOT EXISTS ptc_ctp_rows (
    backbone   TEXT NOT NULL,
    head       TEXT NOT NULL,
    strategy   TEXT NOT NULL,
    ptc_disc   DOUBLE,
    ctp_disc   DOUBLE,
    delta_disc DOUBLE,
    ptc_map    DOUBLE,
    ctp_map    DOUBLE,
    delta_map  DOUBLE,
    PRIMARY KEY (backbone, head, strategy)
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

-- One row per (song, backbone, bin_mode, std_thresh, bin_id, pool_strategy).
-- Stores both raw and L2-normalised pooled patch vectors for each segment.
-- weight         = number of patches in this segment
-- outlier_count  = patches rejected by the outlier lookahead window
-- bin_mode       = 'temporal_global' | 'temporal_perdim'
--   temporal_global : segment boundary when global L2 distance exceeds thresh
--   temporal_perdim : segment boundary when max per-dim deviation exceeds thresh
-- pool_strategy   = 'mean' | 'median' | 'max' | 'min'
CREATE TABLE IF NOT EXISTS binned_vecs (
    song_id       TEXT NOT NULL,
    backbone      TEXT NOT NULL,
    bin_mode      TEXT NOT NULL,
    std_thresh    DOUBLE NOT NULL,
    bin_id        INTEGER NOT NULL,   -- sequential segment index 0,1,2,...
    pool_strategy TEXT NOT NULL,      -- 'mean' | 'median' | 'max' | 'min'
    vec_raw       BLOB NOT NULL,      -- float32 bytes: np.frombuffer(v, np.float32)
    vec_norm      BLOB NOT NULL,      -- float32 bytes: np.frombuffer(v, np.float32)
    weight        INTEGER NOT NULL,
    outlier_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (song_id, backbone, bin_mode, std_thresh, bin_id, pool_strategy)
);

-- Head activations per bin segment.
CREATE TABLE IF NOT EXISTS binned_head_results (
    song_id    TEXT NOT NULL,
    backbone   TEXT NOT NULL,
    head       TEXT NOT NULL,
    bin_mode   TEXT NOT NULL,
    std_thresh DOUBLE NOT NULL,
    bin_id     INTEGER NOT NULL,
    act        BLOB NOT NULL,        -- float32 bytes: np.frombuffer(v, np.float32)
    weight     INTEGER NOT NULL,
    PRIMARY KEY (song_id, backbone, head, bin_mode, std_thresh, bin_id)
);

-- Retrieval metrics for binned multi-vector similarity search.
-- rep_a / rep_b  : which pool representation is used for each song in a pair
--                  ('mean' | 'median' | 'max' | 'min')
-- sim_metric     : 'cosine' | 'l2'
-- agg_method     : how the [N_a x N_b] bin-vs-bin matrix is collapsed
--                  ('mean' | 'median' | 'max' | 'min')
CREATE TABLE IF NOT EXISTS binned_retrieval_rows (
    backbone      TEXT NOT NULL,
    bin_mode      TEXT NOT NULL,
    std_thresh    DOUBLE NOT NULL,
    rep_a         TEXT NOT NULL,
    rep_b         TEXT NOT NULL,
    sim_metric    TEXT NOT NULL,
    agg_method    TEXT NOT NULL,
    k             INTEGER NOT NULL,
    disc_score    DOUBLE,
    map_k         DOUBLE,
    mrr           DOUBLE,
    ndcg_k        DOUBLE,
    recall_k      DOUBLE,
    recall_k_album DOUBLE,
    recall_k_genre DOUBLE,
    mean_within   DOUBLE,
    mean_cross    DOUBLE,
    disc_artist   DOUBLE,
    disc_album    DOUBLE,
    disc_genre    DOUBLE,
    disc_head     DOUBLE,
    PRIMARY KEY (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)
);

-- Fraction of songs where binned weighted-majority head decision matches
-- the baseline PTC/median single-vector decision.
-- NOTE: upsert_head_agreement() exists but has no call site in the current pipeline.
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
-- bin_div_std = STD of pairwise L2 distances between bin mean vectors
--               (0 = all bins identical, high = very diverse segments).
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
    bin_div_std   FLOAT,
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

-- CTP-derived retrieval metrics. Same schema as binned_retrieval_rows but keyed
-- on (backbone, head, ...) because CTP segment boundaries are head-specific.
-- head = the head whose score stream was STD-binned to determine segment indices.
CREATE TABLE IF NOT EXISTS binned_ctp_retrieval_rows (
    backbone      TEXT NOT NULL,
    head          TEXT NOT NULL,
    bin_mode      TEXT NOT NULL,
    std_thresh    DOUBLE NOT NULL,
    rep_a         TEXT NOT NULL,
    rep_b         TEXT NOT NULL,
    sim_metric    TEXT NOT NULL,
    agg_method    TEXT NOT NULL,
    k             INTEGER NOT NULL,
    disc_score    DOUBLE,
    map_k         DOUBLE,
    mrr           DOUBLE,
    ndcg_k        DOUBLE,
    recall_k      DOUBLE,
    recall_k_album DOUBLE,
    recall_k_genre DOUBLE,
    mean_within   DOUBLE,
    mean_cross    DOUBLE,
    disc_artist   DOUBLE,
    disc_album    DOUBLE,
    disc_genre    DOUBLE,
    disc_head     DOUBLE,
    PRIMARY KEY (backbone, head, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)
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
    # Forward migrations — safe to run on both new and existing DBs.
    con.execute("ALTER TABLE songs ADD COLUMN IF NOT EXISTS genre TEXT")
    con.execute("ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS disc_album DOUBLE")
    con.execute("ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS disc_album DOUBLE")
    con.execute("ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS disc_artist DOUBLE")
    con.execute("ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS disc_genre DOUBLE")
    con.execute("ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS disc_head DOUBLE")
    # Legacy: binned_ctp_vecs and binned_ctp_retrieval_rows were added to the DDL after
    # being introduced as forward migrations. Kept here for pre-DDL databases.
    con.execute(
        "CREATE TABLE IF NOT EXISTS binned_ctp_vecs ("
        "  song_id       TEXT NOT NULL,"
        "  backbone      TEXT NOT NULL,"
        "  head          TEXT NOT NULL,"
        "  bin_mode      TEXT NOT NULL,"
        "  std_thresh    DOUBLE NOT NULL,"
        "  bin_id        INTEGER NOT NULL,"
        "  pool_strategy TEXT NOT NULL,"
        "  vec_raw       BLOB NOT NULL,"
        "  vec_norm      BLOB NOT NULL,"
        "  weight        INTEGER NOT NULL,"
        "  outlier_count INTEGER NOT NULL DEFAULT 0,"
        "  PRIMARY KEY (song_id, backbone, head, bin_mode, std_thresh, bin_id, pool_strategy)"
        ")"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS binned_ctp_retrieval_rows ("
        "  backbone      TEXT NOT NULL,"
        "  head          TEXT NOT NULL,"
        "  bin_mode      TEXT NOT NULL,"
        "  std_thresh    DOUBLE NOT NULL,"
        "  rep_a         TEXT NOT NULL,"
        "  rep_b         TEXT NOT NULL,"
        "  sim_metric    TEXT NOT NULL,"
        "  agg_method    TEXT NOT NULL,"
        "  k             INTEGER NOT NULL,"
        "  disc_score    DOUBLE,"
        "  map_k         DOUBLE,"
        "  mrr           DOUBLE,"
        "  ndcg_k        DOUBLE,"
        "  recall_k      DOUBLE,"
        "  recall_k_album DOUBLE,"
        "  recall_k_genre DOUBLE,"
        "  mean_within   DOUBLE,"
        "  mean_cross    DOUBLE,"
        "  disc_artist   DOUBLE,"
        "  disc_album    DOUBLE,"
        "  disc_genre    DOUBLE,"
        "  disc_head     DOUBLE,"
        "  PRIMARY KEY (backbone, head, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)"
        ")"
    )


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
