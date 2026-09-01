# Embedding Research Pipeline — Contracts

> Canonical API and schema reference. Edit this file whenever a function signature,
> return key, or column name changes. Run tests after any change.

## Table of Contents

- [1. Database Schema](#1-database-schema-db_schemapy-db_typespy-db__initpy)
- [2. Database Operations](#2-database-operations-dbflatpy-dbbinnedpy)
- [3. Similarity & Metrics](#3-similarity--metrics-similaritypy)
- [4. Flat Strategy](#4-flat-strategy)
- [5. Binned Strategy](#5-binned-strategy-strategy_binned)
- [6. Report Sections](#6-report-sections-report)
- [7. Pipeline Orchestration](#7-pipeline-orchestration-runpy-classifypy-embedpy-configpy)

---

## Follow-on primary experiment contract

The default primary experiment (Plans A–C of the embedding-research follow-on) is deliberately
narrow and replaces the completed A–E broad cross-product grid. It has exactly these dimensions:

- **backbone:** `effnet` only by default. MusicNN remains supported by the existing independent
  backbone machinery (its own observed medoid baseline, matching-corpus manifest, and report
  population) but is enabled **only** by an explicit configuration selection (e.g.
  `backbones = ["effnet", "musicnn"]`); it is never part of default runs.
- **flat baseline:** `flat_strategies=["medoid"]` — the observed global medoid
  (`global_pool:{backbone}:medoid`).
- **PTC representation:** `rep_types=["medoid"]` (observed per-bin segment representation).
- **PTC boundary configurations:** the configured temporal bin modes and distance thresholds,
  each reported separately, never collapsed by averaging across thresholds or representations.
- **primary score variant:** `max_per_candidate_segment` — one patch-count-weighted contribution
  per candidate segment, with collision/winner/cosine/contribution traces and explicit
  tie/collision ambiguity variants.
- **similarity:** cosine on unit vectors.
- **comparison:** every PTC threshold/configuration versus the same-corpus observed global medoid.

**CTP is deferred/archival.** CTP segment functions, caches, and archival loaders remain available
and callable, but are disabled from default primary analysis by the `[archival_ctp] enabled=false`
switch: CTP requirements never constrain the primary corpus and CTP rows/winners never enter the
primary report grid. CTP appears only in an archival/deferred section or warning.

**Primary corpus algorithm.** Start with the stratified candidate universe; for each selected
backbone intersect availability of `flat:medoid` and every selected PTC
`(bin_mode, threshold, rep_type=medoid, score_variant)` sidecar; sort the surviving song IDs
canonically; hash backbone, membership, the eligibility dimensions (rep types, score variants,
scoring-semantics version, k) and the boundary configuration; pass that exact manifest to every
flat/PTC loader and reject any returned set or order mismatch without emitting a row. A separately
enabled head phase may derive a narrower manifest from this primary manifest plus head-cache
availability, but may not alter or block primary retrieval rows.

**Evaluation lenses.** MAP, MRR, NDCG, Recall, and discrimination are evaluation lenses — never
optimization objectives and never collapsed into one composite. Each is reported and compared
independently.

Preserved medoid/cache/corpus/report invariants (observed medoid with deterministic ties;
`rep_type=medoid` valid, `agg_method=medoid` rejected; immutable/versioned caches; matching-corpus
rejection; finite-only numeric output; schema-v2 report keys; no `disc_album` anywhere) remain
binding from the completed A–E repair and are documented in the sections below.

---

## 1. Database Schema (db/_schema.py, db/_types.py, db/__init__.py)

## Module: `db/_schema.py`

### Functions

#### `_require_duckdb() -> None`

Private guard. Raises `ImportError` if `duckdb` is not installed. Called by every public function before any DuckDB operation.

#### `ensure_schema(con) -> None`

Executes the full DDL string against an already-open connection. Safe to call multiple times (all `CREATE TABLE` statements use `IF NOT EXISTS`).

#### `upsert_phase_timing(con, run_ts: str, phase: str, elapsed_s: float) -> None`

Inserts or updates one row in `phase_timings` via `INSERT ... ON CONFLICT (run_ts, phase) DO UPDATE SET elapsed_s = excluded.elapsed_s`.

#### `connect(read_only: bool = False) -> Generator[duckdb.DuckDBPyConnection, None, None]`

Context manager. Opens `DB_PATH` (from `scripts.embedding_research.config`). When `read_only=False` (default), calls `ensure_schema` immediately after opening. Closes the connection on exit.

---

## DuckDB Tables (18 total)

### Flat-embedding pipeline

---

## Table: `songs`

**Primary key:** `song_id`

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| song_id | TEXT | PRIMARY KEY |
| path | TEXT | NOT NULL |
| artist | TEXT | — |
| album | TEXT | — |
| title | TEXT | — |
| genre | TEXT | — |

---

## Table: `pooled_vecs`

**Primary key:** `(song_id, backbone, strategy)`

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| song_id | TEXT | NOT NULL |
| backbone | TEXT | NOT NULL |
| strategy | TEXT | NOT NULL |
| vec | FLOAT[] | NOT NULL |

---

## Table: `head_results` *(DEPRECATED — DEAD)*

> **This table is no longer written.** Flat PTC/CTP head activations were migrated to
> the filesystem cache. The DDL is retained in `_schema.py` for migration safety only.
>
> **Canonical filesystem path:**
> `{OUTPUT_ROOT}/cache/{backbone}/heads/{head_name}/{strategy}/{pathway}/{song_id}.npy`
>
> **Owner module:** `scripts/embedding_research/cache/flat_heads.py`

**Former primary key:** `(song_id, backbone, head, strategy, pathway)`

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| song_id | TEXT | NOT NULL |
| backbone | TEXT | NOT NULL |
| head | TEXT | NOT NULL |
| strategy | TEXT | NOT NULL |
| pathway | TEXT | NOT NULL — `'ptc'` or `'ctp'` |
| act | FLOAT[] | NOT NULL — softmax probabilities `[p0, p1]` |

---

## Table: `analyze_metrics`

**Primary key:** `(strategy_key, sim_metric, k, metric)`

Aggregate retrieval metrics computed by the shared `common.analyze.analyze` phase and written by `db.flat.write_analyze_metrics` (non-`None` values only).

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| strategy_key | TEXT | NOT NULL |
| strategy_type | TEXT | NOT NULL |
| sim_metric | TEXT | NOT NULL |
| k | INTEGER | NOT NULL |
| metric | TEXT | NOT NULL |
| value | DOUBLE | — |

---

## Table: `song_retrieval_metrics`

**Primary key:** `(strategy_key, sim_metric, k, song_id)`

Per-song retrieval metrics, one row per song, written by `db.flat.write_song_retrieval_metrics` from the `"per_song"` payload of `similarity.compute_retrieval_metrics`.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| strategy_key | TEXT | NOT NULL |
| sim_metric | TEXT | NOT NULL |
| k | INTEGER | NOT NULL |
| song_id | TEXT | NOT NULL |
| ap_k | DOUBLE | — |
| mrr | DOUBLE | — |
| recall_k | DOUBLE | — |
| disc_artist_contrib | DOUBLE | — |
| disc_genre_contrib | DOUBLE | — |
| disc_head_contrib | DOUBLE | — |

---

## Table: `stratified_corpus`

**Primary key:** `(config_hash, song_id)`

Corpus stratification — the stratified working-set song IDs for a given config hash, written by `db.stratify.write_stratified_sids` in the `stratify` phase.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| config_hash | TEXT | NOT NULL |
| song_id | TEXT | NOT NULL |

---

### Binned-embedding pipeline

---

## Table: `binned_calibration`

**Primary key:** `(backbone, dist_mode)`

`dist_mode` maps to `binned_vecs.bin_mode`: `'global'` → `'temporal_global'`, `'perdim'` → `'temporal_perdim'`.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| dist_mode | TEXT | NOT NULL — `'global'` or `'perdim'` |
| p10 | DOUBLE | — |
| p25 | DOUBLE | — |
| p50 | DOUBLE | — |
| p75 | DOUBLE | — |
| mean_d | DOUBLE | — |
| sigma_d | DOUBLE | — |
| n_patches | INTEGER | — |

---



## Table: `head_agreement_rows`

**Primary key:** `(backbone, head, bin_mode, std_thresh)`

Fraction of songs where binned weighted-majority head decision matches the baseline PTC/median single-vector decision.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| head | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| std_thresh | DOUBLE | NOT NULL |
| agreement_rate | DOUBLE | — |
| n_songs | INTEGER | — |

---

## Table: `patch_features`

**Primary key:** `(song_id, patch_idx)`

Per-patch audio features extracted by librosa, time-aligned to embedding patches. `chroma_key` = 0–11 (argmax of 12-dim chroma vector at that patch window).

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| song_id | TEXT | NOT NULL |
| patch_idx | INTEGER | NOT NULL |
| rms | FLOAT | — |
| spectral_centroid | FLOAT | — |
| onset_strength | FLOAT | — |
| chroma_key | INTEGER | — |

---

## Table: `binned_pair_sims`

**Primary key:** `(song_a, song_b, backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method)`

`song_a < song_b` enforced on write.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| song_a | TEXT | NOT NULL |
| song_b | TEXT | NOT NULL |
| backbone | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| std_thresh | DOUBLE | NOT NULL |
| rep_a | TEXT | NOT NULL |
| rep_b | TEXT | NOT NULL |
| sim_metric | TEXT | NOT NULL |
| agg_method | TEXT | NOT NULL |
| score | FLOAT | NOT NULL |

---

## Table: `binned_song_stats`

**Primary key:** `(song_id, backbone, bin_mode, std_thresh)`

Per-song structural stats for a given `(backbone, bin_mode, std_thresh)`.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| song_id | TEXT | NOT NULL |
| backbone | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| std_thresh | DOUBLE | NOT NULL |
| n_bins | INTEGER | — |
| n_patches | INTEGER | — |
| n_outliers | INTEGER | — |
| min_bin_size | INTEGER | — |
| max_bin_size | INTEGER | — |
| mean_bin_size | FLOAT | — |

---

## Table: `binned_classify_ctp`

**Primary key:** `(song_id, backbone, head, bin_mode, std_thresh, bin_id)`

Classify-first CTP-binned head activations. Head is run on every raw patch → `[n_patches, 2]` activations, then the positive-class score sequence is STD-DEV-binned. Each bin stores the mean activation vector over its patches.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| song_id | TEXT | NOT NULL |
| backbone | TEXT | NOT NULL |
| head | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| std_thresh | DOUBLE | NOT NULL |
| bin_id | INTEGER | NOT NULL |
| act | BLOB | NOT NULL |
| weight | INTEGER | NOT NULL |

---

## Table: `truncation_robustness_rows`

**Primary key:** `(backbone, bin_mode, std_thresh)`

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| std_thresh | DOUBLE | NOT NULL |
| flat_mean_sim | DOUBLE | — |
| binned_mean_sim | DOUBLE | — |
| truncation_robustness_delta | DOUBLE | — |

---

### CTP-derived tables

---

## Table: `binned_ctp_vecs`

**Primary key:** `(song_id, backbone, head, bin_mode, std_thresh, bin_id, pool_strategy)`

CTP-derived embedding pools. Segment boundaries (patch indices) from classifier score segmentation are used to pool raw embedding patches. `head` = the head whose score stream drove segmentation. `pool_strategy` = `'mean'` | `'median'` | `'max'` | `'min'`.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| song_id | TEXT | NOT NULL |
| backbone | TEXT | NOT NULL |
| head | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| std_thresh | DOUBLE | NOT NULL |
| bin_id | INTEGER | NOT NULL |
| pool_strategy | TEXT | NOT NULL |
| vec_raw | BLOB | NOT NULL |
| vec_norm | BLOB | NOT NULL |
| weight | INTEGER | NOT NULL |
| outlier_count | INTEGER | NOT NULL DEFAULT 0 |

---



## Table: `binned_ptc_ctp_metrics`

**Primary key:** `(backbone, bin_mode, std_thresh, head)`

PTC-vs-CTP divergence metrics per `(backbone, bin_mode, std_thresh, head)`. `divergence_mean` = mean over songs of `|ptc_score − ctp_score|`, where each per-song score is the weighted mean of `act[1]` over that song's bins. `bin_count_var` = variance of CTP per-song bin counts. `sim_align_corr` = Pearson correlation between PTC and CTP per-song score vectors.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| std_thresh | DOUBLE | NOT NULL |
| head | TEXT | NOT NULL |
| divergence_mean | DOUBLE | — |
| bin_count_var | DOUBLE | — |
| sim_align_corr | DOUBLE | — |

---

## Table: `head_sim_corr_rows`

**Primary key:** `(backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, head)`

Per-head Spearman rank correlation between pairwise embedding similarity and the absolute difference in that head's activation score between each pair of songs. Positive correlation = high-sim songs have similar head scores. Primary quality signal for binned embedding research.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| std_thresh | DOUBLE | NOT NULL |
| rep_a | TEXT | NOT NULL |
| rep_b | TEXT | NOT NULL |
| sim_metric | TEXT | NOT NULL |
| agg_method | TEXT | NOT NULL |
| k | INTEGER | NOT NULL |
| head | TEXT | NOT NULL |
| corr | DOUBLE | — |

---

### Infrastructure

---

## Table: `phase_timings`

**Primary key:** `(run_ts, phase)`

Elapsed wall-clock time for each pipeline phase. `run_ts` = ISO-8601 timestamp of the run start; one row per `(run, phase)`.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| run_ts | TEXT | NOT NULL |
| phase | TEXT | NOT NULL |
| elapsed_s | DOUBLE | NOT NULL |

---

## Table: `head_phase_provenance`

**Primary key:** `(backbone, head, bin_mode, threshold, boundary_source, head_pool_variant)`

Shared-boundary head-phase preparation provenance (Plan B, Phase 2). One row per `(backbone, head, bin_mode, threshold)` config tuple recording the head-boundary preparation status and per-configuration provenance. ADDITIVE to the primary experiment: never part of `analyze_metrics`, never a primary winner candidate, never carries a CTP boundary source. `boundary_source` is fixed to `"effnet_ptc"` and `head_pool_variant` to `"shared_effnet_ptc_boundary"`; `reference_corpus_hash` declares the primary EffNet corpus this head phase derived its song set from (`NULL` = head-availability-only derived subset).

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| head | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| threshold | DOUBLE | NOT NULL |
| boundary_source | TEXT | NOT NULL |
| head_pool_variant | TEXT | NOT NULL |
| status | TEXT | NOT NULL — `'done'` \| `'skipped'` \| `'error'` |
| reason | TEXT | — |
| n_songs | INTEGER | NOT NULL |
| n_pooled | INTEGER | NOT NULL |
| finite | INTEGER | NOT NULL |
| scoring_semantics_version | INTEGER | NOT NULL |
| reference_corpus_hash | TEXT | — |

---

## Module: `db/_types.py`

No dataclasses are defined here.

---

## Module: `db/__init__.py`

### `__all__` Export List

The 42 public names exported from `scripts.embedding_research.db`, grouped by source submodule:

**From `_schema`:**

- `connect`
- `ensure_schema`
- `upsert_phase_timing`

**From `binned`:**

- `load_binned_sampling_stats`
- `load_calibration`
- `load_classify_ctp_rows`
- `query_classify_ctp_sids`
- `upsert_binned_classify_ctp_bulk`
- `upsert_binned_song_stats`
- `upsert_calibration`
- `upsert_head_sim_corr_batch`

**From `flat`:**

- `clear_song_retrieval_metrics`
- `head_strategy_done`
- `load_analyze_metrics`
- `load_head_labels`
- `upsert_head`
- `write_analyze_metrics`
- `write_song_retrieval_metrics`

**From `head_phase`:**

- `HeadPhaseProvenanceRow`
- `build_head_phase_provenance_rows`
- `head_phase_config_key`
- `load_head_phase_provenance`
- `query_head_phase_done`
- `write_head_phase_provenance`

**From `patch`:**

- `patch_features_done`

**From `queries`:**

- `query_analysis_done`
- `query_binned_classify_done`
- `query_binned_configs`
- `query_binned_embed_done`
- `query_classify_done`
- `query_head_sim_corr_done`

**From `songs`:**

- `load_all_songs`
- `load_sids_and_artists`
- `load_song_albums`
- `load_song_genres`
- `load_song_head_scores`
- `song_exists`
- `upsert_song`

**From `stratify`:**

- `clear_stale_stratification`
- `load_stratified_sids`
- `write_stratified_sids`

**From `truncation`:**

- `upsert_truncation_robustness`

---

## 2. Database Operations (db/flat.py, db/binned.py)

## `db/flat.py`

Module docstring: *Flat-embedding pipeline scalar tables and filesystem-backed caches.*
Pooled vectors and head activations are **not** stored in DuckDB — they live on the filesystem.
Head activations: `cache.flat_heads` (`cache/{backbone}/heads/{head_name}/{strategy}/{pathway}/{song_id}.npy`).
Pooled vectors: `cache.flat_vecs` (`cache/{backbone}/{strategy}/flat/{song_id}.npy`).
This module only handles scalar/metadata tables.

---

### `upsert_head(song_id, backbone, head, strategy, pathway, act)`

**Purpose:** Insert or replace a single song's head activation vector for one (song_id, backbone, head, strategy, pathway) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `song_id` | `str` | Unique song identifier |
| `backbone` | `str` | Embedding model backbone name |
| `head` | `str` | Head name (e.g. `"genre"`, `"artist"`) |
| `strategy` | `str` | Pooling/embedding strategy name |
| `pathway` | `str` | `"ptc"` or `"ctp"` |
| `act` | `list[float]` | Activation / class-probability vector |

**Returns:** `None`

**Filesystem write:** `{OUTPUT_ROOT}/cache/{backbone}/heads/{head}/{strategy}/{pathway}/{song_id}.npy`

**Missing-data behaviour:** No guards; all values passed directly. `act` may be any list.

---

### `head_strategy_done(song_id, backbone, head, strategy)`

**Purpose:** Return `True` when both pathways (ptc **and** ctp) have been written for a given (song_id, backbone, head, strategy) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `song_id` | `str` | Song identifier |
| `backbone` | `str` | Backbone name |
| `head` | `str` | Head name |
| `strategy` | `str` | Strategy name |

**Returns:** `bool` — `True` when both `ptc/` and `ctp/` files exist on disk.

**Filesystem check:** Delegates to `cache.flat_heads.is_done(backbone, head, strategy, song_id)`.

**Missing-data behaviour:** Returns `False` when either pathway file is absent.

---

### `load_head_labels(sids, backbone, head, strategy, pathway, label_names)`

**Purpose:** Return a per-song majority-class label string for the given (backbone, head, strategy, pathway); returns `None` if more than 20% of requested songs are absent.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `sids` | `list[str]` | Ordered list of song IDs to label |
| `backbone` | `str` | Backbone name |
| `head` | `str` | Head name |
| `strategy` | `str` | Strategy name |
| `pathway` | `str` | `"ptc"` or `"ctp"` |
| `label_names` | `list[str]` | Mapping from class index → label string |

**Returns:** `list[str] | None` — label list aligned to `sids`, or `None` if >20% missing.

**Filesystem reads:** `cache.flat_heads.load_bulk(backbone, head, strategy, pathway, sids)`
Path pattern: `{OUTPUT_ROOT}/cache/{backbone}/heads/{head}/{strategy}/{pathway}/{song_id}.npy`

**Missing-data behaviour:**

- A song absent from the cache receives label `"unknown"` and increments a missing counter.
- If `missing > 0.2 * len(sids)` the entire result is discarded and `None` is returned.
- A class index `cls` that exceeds `len(label_names)` falls back to the string `f"class_{cls}"`.

---

### `clear_song_retrieval_metrics(con, strategy_key, sim_metric, k)`

**Purpose:** Delete all per-song retrieval metric rows for the given (strategy_key, sim_metric, k) combination.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `strategy_key` | `str` | Strategy identifier |
| `sim_metric` | `str` | Similarity metric name (e.g. `"cosine"`) |
| `k` | `int` | Retrieval cut-off |

**Returns:** `None`

**SQL table affected:** `song_retrieval_metrics`

**Query:** `DELETE FROM song_retrieval_metrics WHERE strategy_key = ? AND sim_metric = ? AND k = ?`

Called by the shared analysis path before writing fresh per-song rows.

---

### `write_song_retrieval_metrics(con, strategy_key, sim_metric, k, per_song)`

**Purpose:** Write per-song retrieval metrics into the `song_retrieval_metrics` table, one row per song, replacing any existing rows for the (strategy_key, sim_metric, k) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `strategy_key` | `str` | Strategy identifier |
| `sim_metric` | `str` | Similarity metric name (e.g. `"cosine"`) |
| `k` | `int` | Retrieval cut-off |
| `per_song` | `dict` | The `"per_song"` dict returned by `similarity.compute_retrieval_metrics`, keyed `song_ids`, `ap_k`, `mrr`, `recall_k`, `disc_artist_contrib`, `disc_genre_contrib`, `disc_head_contrib` |

**Returns:** `None`

**SQL table written:** `song_retrieval_metrics`

**Write behaviour:** `INSERT OR REPLACE` one row per song in `per_song["song_ids"]`; a missing per-song metric array yields SQL `NULL` for that column. No-op when `per_song["song_ids"]` is empty.

---

### `write_analyze_metrics(con, strategy_key, strategy_type, sim_metric, k, metrics)`

**Purpose:** Insert the non-`None` analysis metric values into `analyze_metrics`.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `strategy_key` | `str` | Strategy identifier |
| `strategy_type` | `str` | `"global_pool"` \| `"ptc"` \| `"ctp"` |
| `sim_metric` | `str` | Similarity metric name |
| `k` | `int` | Retrieval cut-off |
| `metrics` | `dict` | Metric values keyed by metric name |

**Returns:** `None`

**SQL table written:** `analyze_metrics`

**Write behaviour:** Entries with `None` values are skipped. Dict-valued entries are flattened as `"{name}_{sub_name}"`. List/ndarray-valued entries are skipped (per-song lists are never written as aggregate metrics). Each row is `INSERT OR REPLACE`.

---

### `load_analyze_metrics(con)`

**Purpose:** Load `analyze_metrics` as a wide DataFrame.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |

**Returns:** `pd.DataFrame` — pivoted on `metric` so each metric name becomes a column, indexed by `(strategy_key, strategy_type, sim_metric, k)`, sorted by `disc_general DESC` (when present). Empty DataFrame when no rows exist.

**SQL table read:** `analyze_metrics`

**Query:** `SELECT * FROM analyze_metrics`, then pivoted via `pivot_table` on the `metric` column (`aggfunc="first"`).

---

## `db/binned.py`

Module docstring: *Binned-embedding pipeline: calibration, retrieval, stats.*

### `upsert_calibration(con, backbone, dist_mode, p10, p25, p50, p75, mean_d, sigma_d, n_patches)`

**Purpose:** Insert or update distance-distribution calibration statistics for a (backbone, dist_mode) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `dist_mode` | `str` | Distance mode used to key calibration (matches the binning mode, e.g. `'temporal_global'` | `'temporal_perdim'`) |
| `p10` | `float` | 10th percentile of pairwise distances |
| `p25` | `float` | 25th percentile of pairwise distances |
| `p50` | `float` | Median pairwise distance |
| `p75` | `float` | 75th percentile of pairwise distances |
| `mean_d` | `float` | Mean pairwise distance |
| `sigma_d` | `float` | Standard deviation of pairwise distances |
| `n_patches` | `int` | Number of patches sampled for calibration |

**Returns:** `None`

**SQL table written:** `binned_calibration`

**Columns in INSERT:** `backbone, dist_mode, p10, p25, p50, p75, mean_d, sigma_d, n_patches`

**Conflict resolution:** `ON CONFLICT (backbone, dist_mode) DO UPDATE SET p10, p25, p50, p75, mean_d, sigma_d, n_patches = excluded values`

---

### `load_calibration(con, backbone, dist_mode)`

**Purpose:** Retrieve calibration statistics for a (backbone, dist_mode) combination.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `dist_mode` | `str` | Distance mode |

**Returns:** `dict | None` — dict with keys `(p10, p25, p50, p75, mean_d, sigma_d, n_patches)`, or `None` if no row exists.

**SQL table read:** `binned_calibration`

**Columns selected:** `p10, p25, p50, p75, mean_d, sigma_d, n_patches`

**WHERE clause:** `backbone=? AND dist_mode=?`

**Missing-data behaviour:** Returns `None` when `fetchone()` returns `None` (no row found).

---

### `upsert_binned_classify_ctp_bulk(con, rows)`

**Purpose:** Bulk-insert CTP per-bin activations; ignores rows that already exist; no-op if `rows` is empty.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `rows` | `list[tuple]` | Each tuple: `(song_id, backbone, head, bin_mode, std_thresh, bin_id, act, weight)` |

**Returns:** `None`

**SQL table written:** `binned_classify_ctp`

**Columns in INSERT:** `song_id, backbone, head, bin_mode, std_thresh, bin_id, act, weight`

**Conflict resolution:** `ON CONFLICT (song_id, backbone, head, bin_mode, std_thresh, bin_id) DO NOTHING`

---

### `query_classify_ctp_sids(con, backbone, head, bin_mode, std_thresh)`

**Purpose:** Return the set of distinct song IDs that have CTP classification data for the given (backbone, head, bin_mode, std_thresh) configuration.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `head` | `str` | Head name |
| `bin_mode` | `str` | Binning mode |
| `std_thresh` | `float` | Std-dev threshold (explicitly cast to `float` before query) |

**Returns:** `list[str]` — list of song IDs; empty list if no rows.

**SQL table read:** `binned_classify_ctp`

**Query:** `SELECT DISTINCT song_id WHERE backbone=? AND head=? AND bin_mode=? AND std_thresh=?`

---

### `load_classify_ctp_rows(con, backbone, head, bin_mode, std_thresh, *, sid_list=None)`

**Purpose:** Return all CTP classification rows for the given config as a list of `(song_id, act, weight)` tuples, optionally restricted to a specific song list.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `head` | `str` | Head name |
| `bin_mode` | `str` | Binning mode |
| `std_thresh` | `float` | Std-dev threshold (cast to `float` before query) |
| `sid_list` | `list[str] \| None` | If provided, adds `AND song_id = ANY(?)` filter |

**Returns:** `list[tuple]` — each element is `(song_id, act, weight)`; empty list if no rows.

**SQL table read:** `binned_classify_ctp`

**Columns selected:** `song_id, act, weight`

**WHERE clause (base):** `backbone=? AND head=? AND bin_mode=? AND std_thresh=?`

**WHERE clause (with sid_list):** appends `AND song_id = ANY(?)`

---

### `upsert_head_sim_corr_batch(con, rows)`

**Purpose:** Bulk-insert per-head Spearman correlation scores between head-label ranks and similarity ranks; no-op if `rows` is empty.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `rows` | `list[tuple]` | Each tuple **must** be ordered as `(backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, head, corr)` |

**Returns:** `None`

**SQL table written:** `head_sim_corr_rows`

**Columns in INSERT:** `backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, head, corr`

**Conflict resolution:** `ON CONFLICT (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, head) DO UPDATE SET corr=excluded.corr`

---

### `load_binned_sampling_stats(con)`

**Purpose:** Load one aggregated row per song across all completed binned configs, for deterministic stratified sampling of the library.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |

**Returns:** `list[dict]` — each dict has keys: `song_id, artist, n_configs, avg_n_bins, avg_n_patches, avg_n_outliers, avg_mean_bin_size`. Empty list if no data.

**SQL tables read:** `binned_song_stats` (aliased `bs`) joined to `songs` via `USING (song_id)`

**Aggregation:** `COUNT(*) AS n_configs`, `AVG(n_bins)`, `AVG(n_patches)`, `AVG(n_outliers)`, `AVG(mean_bin_size)` — grouped by `bs.song_id, s.artist`, ordered by `bs.song_id`

**Missing-data behaviour:** SQL `NULL` aggregate values are mapped to `0.0` via `float(r[i]) if r[i] is not None else 0.0`.

---

### `upsert_binned_song_stats(con, song_id, backbone, bin_mode, std_thresh, stats)`

**Purpose:** Insert or update per-song binning statistics for a (song_id, backbone, bin_mode, std_thresh) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `song_id` | `str` | Song identifier |
| `backbone` | `str` | Backbone name |
| `bin_mode` | `str` | Binning mode |
| `std_thresh` | `float` | Std-dev threshold |
| `stats` | `dict` | Stat values (see key mapping below) |

**`stats` key mapping (all via `dict.get`, absent keys → SQL NULL):**

| Dict key | Column |
| --- | --- |
| `n_bins` | `n_bins` |
| `n_patches` | `n_patches` |
| `n_outliers` | `n_outliers` |
| `min_bin_size` | `min_bin_size` |
| `max_bin_size` | `max_bin_size` |
| `mean_bin_size` | `mean_bin_size` |

**Returns:** `None`

**SQL table written:** `binned_song_stats`

**Columns in INSERT (10):** `song_id, backbone, bin_mode, std_thresh, n_bins, n_patches, n_outliers, min_bin_size, max_bin_size, mean_bin_size`

**Conflict resolution:** `ON CONFLICT (song_id, backbone, bin_mode, std_thresh) DO UPDATE SET n_bins, n_patches, n_outliers, min_bin_size, max_bin_size, mean_bin_size = excluded values`

---

## 3. Similarity & Metrics (similarity.py)

## Module-Level Constants

| Symbol | Type | Value / Meaning |
| -------- | ------ | ----------------- |
| `_FAISS` | `bool` | `True` if `faiss` is importable; controls ANN backend selection |
| `_SKLEARN` | `bool` | `True` if `sklearn` is importable; controls NDCG backend selection |
| `_log` | `logging.Logger` | Module logger (`scripts.embedding_research.similarity`) |

---

## Type Aliases (from `vector_types`)

| Name | Meaning |
| ------ | --------- |
| `RawTensor` | Wrapper around a raw `np.ndarray` of shape `(n, d)` (any norm) |
| `UnitTensor` | Wrapper around an L2-normalised `np.ndarray` of shape `(n, d)` |
| `RawVector` | Wrapper around a single raw `np.ndarray` of shape `(d,)` |

---

## `l2_normalise(vecs: RawTensor) -> UnitTensor`

**Parameters:**

- `vecs`: `RawTensor` — input vectors, shape `(n, d)`

**Returns:** `UnitTensor` — same vectors scaled to unit L2 norm, shape `(n, d)`.

**Key invariants:**

- Delegates to `vecs.normalize()` — implementation lives in `vector_types`.
- Zero vectors will produce NaN after normalisation (no guard).
- No copy is guaranteed; callers must not mutate the result in place.

---

## `cosine_matrix(vecs: RawTensor) -> np.ndarray`

**Parameters:**

- `vecs`: `RawTensor` — input vectors, shape `(n, d)`

**Returns:** `np.ndarray` dtype `float32`, shape `(n, n)` — pairwise cosine similarities.

Formula: $S = \hat{V} \hat{V}^\top$ where $\hat{V}$ is the L2-normalised version of `vecs`.

**Key invariants:**

- Diagonal is exactly `1.0` for non-zero vectors.
- Values are clamped to `[-1, 1]` by normalisation; floating-point error may push diagonals
  slightly above `1.0` before the downstream clip in callers.
- Output is `float32` even if input is `float64`.

---

## `_rankings_from_sim(sim_matrix: np.ndarray) -> np.ndarray`  _(internal, widely used)_

**Parameters:**

- `sim_matrix`: `np.ndarray` shape `(n, n)` — pairwise similarities (any metric)

**Returns:** `np.ndarray` dtype `int32`, shape `(n, n-1)` — per-row indices sorted descending
by similarity, with the self-index excluded.

**Algorithm:**

1. For each row `i`, copy the row and set `row[i] = -inf`.
2. `argsort(-row)` gives descending order; self is always last.
3. Return `sorted_idx[:n-1]` (drops the last element which is always self).

**Key invariants:**

- Self-index is never present in any output row.
- Ties are broken by the underlying `np.argsort` stable sort (NumPy default is not stable;
  tie order is implementation-defined).

---

## `compute_retrieval_metrics(sim_matrix, labels, k, albums, genres, head_scores, head_names) -> dict`

### Signature

```python
def compute_retrieval_metrics(
    sim_matrix: np.ndarray,
    labels: list[str],
    k: int = 10,
    *,
    albums: list[str] | None = None,
    genres: list[str] | None = None,
    head_scores: list[list[float]] | None = None,
    head_names: list[str] | None = None,
) -> dict:
```

### Parameters

| Parameter | Type | Required | Description |
| ----------- | ------ | ---------- | ------------- |
| `sim_matrix` | `np.ndarray` shape `(n, n)` | yes | Pairwise similarity matrix. Must be square. Cosine similarity output — values are used as-is. |
| `labels` | `list[str]` length `n` | yes | Artist label per song. Two songs are "relevant" to each other if and only if their label strings are equal. Used for MAP@k, MRR, NDCG@k, Recall@k, and `disc_artist`. |
| `k` | `int` | no (default `10`) | Cut-off depth for all `@k` metrics. |
| `albums` | `list[str] \| None` length `n` | no | Album label per song. Currently used only to compute `album_recalls` internally (see **Known Discrepancy** below). Must be exactly length `n` to be activated; ignored otherwise. |
| `genres` | `list[str] \| None` length `n` | no | Genre label per song. Used for `recall_{k}_genre`, `precision_k_genre`, and `disc_genre`. Must be exactly length `n`. |
| `head_scores` | `list[list[float]] \| None` | no | Classifier head score vectors. Two layouts accepted — function auto-transposes (see **head_scores shape** below). Individual float values must be class-1 probabilities in `[0, 1]`. |
| `head_names` | `list[str] \| None` | no | Name for each head. If provided and length matches `head_score_matrix.shape[0]`, enables `per_head_corr` output. If absent, `per_head_corr` is an empty dict. |

### Returns

A plain `dict` with the following keys. All keys are always present regardless of which optional
parameters were supplied. Missing data degrades to `0.0` or `{}` as noted.

#### Retrieval metrics (artist-grouped)

| Key | Type | Description |
| ----- | ------ | ------------- |
| `map_{k}` | `float` | Mean Average Precision at k over artist groupings. Key is dynamic, e.g. `map_10` for `k=10`. `0.0` if no song has any same-artist neighbour. AP denominator is `min(k, |relevant|)`. |
| `mrr` | `float` | Mean Reciprocal Rank over all songs that have at least one same-artist neighbour. Rank is 1-based over the full sorted list (not truncated at k). `0.0` if corpus has no repeated artists. |
| `ndcg_{k}` | `float` | Mean Normalised Discounted Cumulative Gain at k. Key is dynamic, e.g. `ndcg_10`. Uses binary relevance (1 if same artist, 0 otherwise). Uses `sklearn.metrics.ndcg_score` when available, manual DCG otherwise. Skips songs with fewer than 2 relevant documents (sklearn requirement). `0.0` if no usable songs. |
| `recall_{k}` | `float` | Mean Recall at k grouped by artist. For each song, fraction of its same-artist songs that appear in its top-k. Key is dynamic, e.g. `recall_10`. `0.0` if no song has a same-artist neighbour. |

#### Retrieval metrics (genre-grouped)

| Key | Type | Description |
| ----- | ------ | ------------- |
| `recall_{k}_genre` | `float` | Mean Recall at k grouped by genre. Key is dynamic, e.g. `recall_10_genre`. `0.0` if `genres` is `None`, wrong length, or no song has a same-genre neighbour. |
| `precision_k_genre` | `float` | Mean Precision at k grouped by genre. Fraction of the top-k results that share the query song's genre, averaged over all songs. `0.0` if `genres` not provided or unusable. |

#### Head-precision metric

| Key | Type | Description |
| ----- | ------ | ------------- |
| `precision_k_head_mean` | `float` | Mean over heads of mean-precision at k using score bins as pseudo-labels. For each head, each song's bin `= min(int(score × 10), 9)` (10 bins, 0–9). Precision is fraction of top-k results that share the query's bin. Averaged first within head, then across heads. `0.0` if `head_scores` is `None`. |

#### Discrimination scores

All discrimination scores use the formula:
$$\text{disc} = \text{mean}(\text{within-group similarities}) - \text{mean}(\text{cross-group similarities})$$

For `disc_artist` this is computed over per-song pairs (upper triangle iteration).
For `disc_genre` and `disc_head` bin-groups it is computed via full matrix masks.

| Key | Type | Description |
| ----- | ------ | ------------- |
| `disc_artist` | `float` | Discrimination by artist. Mean within-artist sim minus mean cross-artist sim, over all upper-triangle pairs `(i < j)`. `0.0` if the corpus is single-artist or has no cross-artist pairs. |
| `disc_score` | `float` | **Back-compat alias** for `disc_artist`. Identical value. |
| `disc_genre` | `float` | Discrimination by genre. Uses full-matrix within/cross masks (not upper-triangle). `0.0` if `genres` is `None`, wrong length, all songs share one genre, or there are no cross-genre pairs. |
| `disc_head` | `float` | Mean score-bin discrimination across all heads that had non-constant bin distributions. Score bins: `bin = min(int(score × 10), 9)` where `score` is the class-1 probability (`act[1]`). Heads where all songs fall in the same bin are skipped silently (DEBUG logged). `0.0` if `head_scores` is `None` or all heads are constant-bin. |
| `disc_general` | `float` | Composite discrimination: mean of whichever components in `(disc_artist, disc_genre, disc_head)` are non-zero. A WARNING is logged for each zero-valued component excluded. `0.0` only if all three components are zero. **This is the preferred single-number discrimination signal.** |

#### Internal similarity statistics

| Key | Type | Description |
| ----- | ------ | ------------- |
| `mean_within` | `float` | Raw mean of all within-artist pairwise similarities (upper triangle). `0.0` if no within-artist pairs exist. |
| `mean_cross` | `float` | Raw mean of all cross-artist pairwise similarities (upper triangle). `0.0` if no cross-artist pairs exist. Note: `disc_artist == mean_within - mean_cross` by construction. |

#### Per-head correlations

| Key | Type | Description |
| ----- | ------ | ------------- |
| `per_head_corr` | `dict[str, float]` | Spearman rank correlation between pairwise cosine similarity and mean absolute head-score difference, per head. Key is the head name from `head_names`. Value is `0.0` if either series has zero variance. Empty dict `{}` if `head_names` is `None` or its length does not match the number of heads in `head_score_matrix`. |

### `head_scores` Shape Handling

The function accepts either layout and auto-transposes:

| Raw shape | Interpretation | Action |
| ----------- | --------------- | -------- |
| `(n_heads, n_songs)` | One row per head | Used as-is: `head_score_matrix = head_scores_arr` |
| `(n_songs, n_heads)` | One row per song | Transposed: `head_score_matrix = head_scores_arr.T` |

Detection rule:

- If `shape[1] == n` and `shape[0] > 0` → treated as `(n_heads, n_songs)`.
- Else if `shape[0] == n` and `shape[1] > 0` → treated as `(n_songs, n_heads)` and transposed.
- Ambiguous when `n_heads == n_songs`; layout is then `(n_heads, n_songs)` (first branch wins).

### `bin_idx` Formula

```python
bin_idx = np.minimum((h_scores * 10).astype(np.int32), 9)
```

- Input `h_scores`: 1-D array of class-1 probabilities, range `[0.0, 1.0]`.
- Multiplied by 10 and floored to `int32` → 10 integer bins `{0, 1, …, 9}`.
- Clipped at 9 so that `score == 1.0` maps to bin 9 (not 10).
- Bin 0 covers `[0.0, 0.1)`, bin 1 covers `[0.1, 0.2)`, …, bin 9 covers `[0.9, 1.0]`.

### `disc_general` Invariants

- **Non-zero filter:** components equal to exactly `0.0` (float) are excluded before averaging.
- **Warning:** a WARNING-level log line is emitted for each excluded zero component:
  `[disc_general] excluding zero-valued component(s) from mean: disc_artist=0.0 — disc_general may undercount`
- **Edge case:** if all three components are `0.0`, `disc_general` is `0.0` (no warning for this case).
- **Degrades gracefully:** corpus with only artist labels (no genres, no heads) →
  `disc_general == disc_artist`, with warnings for the two zero components.
- **This is known behaviour, not a bug.** Zero components typically mean the optional data was
  not supplied, not that the model is bad.

### No `disc_album` metric

The `albums` parameter is accepted (it feeds album-level metadata in the analyze/report layers
via `load_song_albums`), but **no `disc_album` metric is computed or returned**.
`compute_retrieval_metrics` returns `disc_artist`, `disc_genre`, `disc_head`, `disc_general` —
never `disc_album`. Do not add a `disc_album` key, SELECT, upsert, or schema field.

---

## `ann_recall_sweep(vecs, labels, k, n_queries, ef_values, recall_target) -> dict`

### Signature

```python
def ann_recall_sweep(
    vecs: RawTensor,
    labels: list[str],
    k: int = 10,
    n_queries: int = 200,
    ef_values: list[int] | None = None,
    recall_target: float = 0.995,
) -> dict:
```

### Parameters

| Parameter | Type | Default | Description |
| ----------- | ------ | --------- | ------------- |
| `vecs` | `RawTensor` shape `(n, d)` | — | The full embedding matrix to index. |
| `labels` | `list[str]` length `n` | — | Artist labels. Present in the signature for consistency but **not used** inside the function body. |
| `k` | `int` | `10` | Recall cut-off depth. |
| `n_queries` | `int` | `200` | Number of random query vectors sampled for the sweep. Seed is fixed at `42` for reproducibility. Capped at `n` if `n < n_queries`. |
| `ef_values` | `list[int] \| None` | `[16, 32, 64, 128, 256]` | `efSearch` values to test in ascending order. |
| `recall_target` | `float` | `0.995` | Early-stop threshold. Sweep halts after the first `ef` that achieves `recall_k >= recall_target`. |

### Returns

`dict[str, dict]` — keys are `"ef_{ef}"` for each tested `ef` value.

```python
{
    "ef_16":  {"recall_k": 0.91, "ef_search": 16,  "backend": "faiss"},
    "ef_64":  {"recall_k": 0.998, "ef_search": 64, "backend": "faiss"},
    # sweep stopped here because recall_k >= recall_target
}
```

| Inner key | Type | Description |
| ----------- | ------ | ------------- |
| `recall_k` | `float` | Mean recall@k of the ANN index against brute-force exact top-k across the sampled queries. |
| `ef_search` | `int` | The `efSearch` value used (redundant with the outer key but useful for downstream table construction). |
| `backend` | `str` | `"faiss"` if faiss is installed, `"numpy"` if the brute-force fallback was used. |

**Key invariants:**

- Exact top-k is computed from `cosine_matrix` on the full corpus (not sampled), then sliced.
- Self-index is excluded from exact top-k via `row[qi] = -inf`.
- The result dict contains only entries for tested `ef` values; higher values are absent if
  `recall_target` was reached early.
- When `backend == "numpy"`, the ANN index is brute-force exact, so `recall_k` will be `1.0`
  for all `ef` values (the sweep will terminate at the first entry).

---

## `ANNIndex`

Wraps faiss HNSW (cosine) index with a numpy brute-force fallback. Only the cosine metric is supported.

### Constructor

```python
ANNIndex(
    vecs: RawTensor,
    metric: str = "cosine",
    hnsw_m: int = 32,
    hnsw_ef_construction: int = 200,
    hnsw_ef_search: int = 64,
    nlist: int = 100,
)
```

| Parameter | Type | Default | Description |
| ----------- | ------ | --------- | ------------- |
| `vecs` | `RawTensor` shape `(n, d)` | — | Embedding matrix. A copy is stored internally (`self._vecs`). |
| `metric` | `str` | `"cosine"` | Similarity metric. Must be `ANNIndex.SUPPORTED_METRICS = ("cosine",)`. Asserted at construction; `AssertionError` on invalid value. |
| `hnsw_m` | `int` | `32` | HNSW graph connectivity parameter. Higher values improve recall at the cost of index build time and memory. Used only for `metric="cosine"` with faiss. |
| `hnsw_ef_construction` | `int` | `200` | HNSW construction beam width. Affects index quality, not query speed. Used only for cosine+faiss. |
| `hnsw_ef_search` | `int` | `64` | HNSW search beam width. Controls the recall/speed trade-off at query time. Can be updated via `set_ef_search()`. |
| `nlist` | `int` | `100` | Parity of the removed IVF/L2 path; unused now that only the cosine metric is supported. |

**Backend selection at construction:**

| Condition | Index built |
| ----------- | ------------- |
| faiss available + `metric="cosine"` | `faiss.IndexHNSWFlat` with `METRIC_INNER_PRODUCT` on L2-normalised vectors |
| faiss not available | No faiss index built; `self._index = None`; numpy fallback used at query time |

**State after construction:**

| Attribute | Type | Description |
| ----------- | ------ | ------------- |
| `self.metric` | `str` | The `metric` argument as stored. |
| `self.n` | `int` | Number of vectors. |
| `self.d` | `int` | Embedding dimension. |
| `self._vecs` | `np.ndarray` | Raw copy of the input vectors. |
| `self._normed` | `np.ndarray` | L2-normalised vectors — set only when `metric="cosine"` and faiss is available. |
| `self._hnsw_ef_search` | `int` | Current `efSearch` value. |
| `self._built_with` | `str` | `"faiss"` or `"numpy"`. |
| `self._index` | faiss index or `None` | The faiss index object, or `None` if faiss unavailable. |

---

### `ANNIndex.set_ef_search(ef: int) -> None`

**Parameters:**

- `ef`: `int` — new `efSearch` value

**Effect:**

- Updates `self._hnsw_ef_search`.
- If faiss is available, the index is cosine-metric, and `self._index` is not `None`, also sets
  `self._index.hnsw.efSearch = ef` immediately.
- No-op fallback: faiss index is always HNSW-cosine, so `efSearch` applies to all faiss-backed queries.

---

### `ANNIndex.query(qvec: RawVector, k: int) -> np.ndarray`

**Parameters:**

- `qvec`: `RawVector` — query vector, shape `(d,)`
- `k`: `int` — number of nearest neighbours to return

**Returns:** `np.ndarray` dtype depends on backend, shape `(k,)` — indices of the `k`
approximate nearest neighbours in the original `vecs` array. Indices are not sorted by
distance in the numpy fallback (they are `argsort` order, i.e. descending sim / ascending dist).

**Backend dispatch:**

| Condition | Behaviour |
| ----------- | ---------- |
| faiss + cosine | L2-normalises `qvec`, calls `self._index.search(qn[None,:], k)`, returns `nn_idx[0]` |
| numpy + cosine | Normalises all stored vectors and query; returns `argsort(-sims)[:k]` |

**Key invariants:**

- Self is not excluded from results. Callers that need self-exclusion must filter it out
  (as `recall_at_k` does via `approx.discard(qi)`).
- `k` must not exceed `n`; no bounds check is performed.

---

### `ANNIndex.recall_at_k(exact_top_k, k, query_indices) -> float`

```python
def recall_at_k(
    self,
    exact_top_k: dict[int, list[int]],
    k: int,
    query_indices: list[int] | None = None,
) -> float:
```

**Parameters:**

| Parameter | Type | Description |
| ----------- | ------ | ------------- |
| `exact_top_k` | `dict[int, list[int]]` | Mapping from query index to ordered list of exact nearest-neighbour indices (self excluded). Only the first `k` entries are used. |
| `k` | `int` | Cut-off depth. Must be consistent with `exact_top_k` entry lengths. |
| `query_indices` | `list[int] \| None` | Subset of queries to evaluate. If `None`, all keys of `exact_top_k` are used. |

**Returns:** `float` — mean recall@k over all evaluated queries.

$$\text{recall@k} = \frac{|\text{approx}_k \cap \text{exact}_k|}{k}$$

**Key invariants:**

- Calls `self.query(RawVector(self._vecs[qi]), k + 1)` and discards `qi` from the result set
  (`approx.discard(qi)`). The `+1` overfetch compensates for the possible self-hit.
- Exact set is `set(exact_top_k[qi][:k])` — top-k only, regardless of list length.
- Returns the arithmetic mean across all queries via `np.mean`.
- Returns `nan` if `query_indices` is empty (numpy mean of empty list).

---

## 4. Flat Strategy

> **Module organization (post-consolidation):** flat (global-pool) strategy code no longer lives
> under a `strategy_flat/` package. It is owned by `pooling.py` (the `STRATEGIES` registry,
> `pool_medoid`, `select_global_medoid_index`, `load_flat_strategy_names`), `strategy_global_pool/`
> (`segment_fn.py`, `_embed.py`), and `cache/flat_vecs.py` (filesystem cache). The shared analyze
> phase is wired through `common/analyze.py` via `GLOBAL_POOL_ANALYZE_CFG` in `run.py`; the old
> `_analyze.py` / `_truncate.py` responsibilities were consolidated into `common/`. The binding
> contracts are the cache layout, the `STRATEGIES` registry, and the per-backbone
> `global_pool:{backbone}:{strategy}` identity.

## Module-level constants and paths

| Symbol | Value | Owner module |
| --- | --- | --- |
| `OUTPUT_ROOT` | `WORKSPACE / 'scripts/outputs/embedding_research'` | `config.py` |
| `PATCHES_DIR` | `OUTPUT_ROOT / 'patches'` | `config.py` |
| `_CACHE_ROOT` | `OUTPUT_ROOT / 'cache'` | `cache/flat_vecs.py` |
| `STRATEGIES` | `{"mean", "trimmed_10", "trimmed_20", "median", "max_norm", "l2norm_mean", "medoid"}` — name → pool function; includes the observed-patch `medoid` | `pooling.py` |
| `METRICS` | `{"cosine": cosine_matrix}` | `similarity.py` |
| `HEADS` | `{backbone: {head_name: onnx_path}}` — populated by `_discover_heads()` at import time | `config.py` |
| `HEAD_LABELS` | `{head_name: [label_0, label_1]}` for known binary classifiers | `config.py` |
| `BACKBONES` | `{"effnet": {...}, "musicnn": {...}}` | `config.py` |
| `BIN_MODES` | list of binning modes, e.g. `["temporal_global", "perdim"]` | `helpers/binning.py` |
| `DIST_THRESHOLDS` | list of normalized L2 distance thresholds for temporal segmentation (see `[binning].dist_thresholds`); truncation robustness is NOT an active phase | `helpers/binning.py` |

### Filesystem layout

```
OUTPUT_ROOT/
  cache/
    {backbone}/
      {strategy}/
        flat/
          {song_id}.npy          # float32 [embed_dim] — pooled vector
      heads/
        {head}/
          {strategy}/
            {pathway}/
              {song_id}.npy      # float32 — head activation
    binned_ptc/
      {cache_semantics_tag()}/{backbone}/{bin_mode}/{_threshold_key(std_thresh)}/{song_id}.npz
    binned_ctp/
      {cache_semantics_tag()}/{backbone}/{head}/{_threshold_key(std_thresh)}/{song_id}.npz
  patches/
    {backbone}/
      {song_id}.npy            # float32 [n_patches, embed_dim] — raw patch embeddings
```

**Cache path threshold segment:** every cache module (`cache/binned_ptc.py`, `cache/binned_ctp.py`) renders the threshold segment via `_threshold_key` — an alias for `helpers.binning.threshold_key`, whose body is `return f"{float(x):.3f}"`. So the `{_threshold_key(std_thresh)}` segment in the paths above always formats the threshold with three decimals (e.g. `0.500`).

---

## `strategy_global_pool/__init__.py`

Re-exports exactly one symbol:

```python
from ._embed import embed

__all__ = ["embed"]
```

Flat strategy registration and pooling live in `pooling.py` (`STRATEGIES`,
`load_flat_strategy_names`, `pool_medoid`, `select_global_medoid_index`); the shared analyze
phase is wired via `GLOBAL_POOL_ANALYZE_CFG` in `run.py`.

---

## `cache/flat_vecs.py` — Filesystem cache for flat pooled vectors

### `_purge_corrupt(p: Path) -> None`

**Signature:** `_purge_corrupt(p: Path) -> None`

| | |
| --- | --- |
| **Reads** | Nothing |
| **Writes** | Deletes `p` from disk |
| **Returns** | `None` |

**Behaviour:** Calls `p.unlink()`. Logs a warning either way. If `OSError`
is raised (e.g. permission denied), the warning is logged and the file is left
in place. The caller treats the file as absent after this call.

**Preconditions:** Called only when `np.load(p)` raises `EOFError | OSError |
ValueError`, meaning the file is present but unreadable.

---

### `_strat_dir(backbone: str, strategy: str) -> Path`

**Signature:** `_strat_dir(backbone: str, strategy: str) -> Path`

| | |
| --- | --- |
| **Reads** | Nothing |
| **Writes** | Nothing |
| **Returns** | `Path` — `_CACHE_ROOT / backbone / strategy / flat` |

Pure path computation. Directory is not created here.

---

### `_vec_path(song_id: str, backbone: str, strategy: str) -> Path`

**Signature:** `_vec_path(song_id: str, backbone: str, strategy: str) -> Path`

| | |
| --- | --- |
| **Reads** | Nothing |
| **Writes** | Nothing |
| **Returns** | `Path` — `_CACHE_ROOT / backbone / strategy / flat / {song_id}.npy` |

Pure path computation. This is the canonical path for a single pooled vector.

---

### `save_pooled(song_id: str, backbone: str, strategy: str, vec: np.ndarray) -> None`

**Signature:** `save_pooled(song_id: str, backbone: str, strategy: str, vec: np.ndarray) -> None`

| | |
| --- | --- |
| **Reads** | Nothing |
| **Writes** | `_CACHE_ROOT / backbone / strategy / flat / {song_id}.npy` |
| **Returns** | `None` |

**Behaviour:**

- Creates parent directories (`parents=True, exist_ok=True`).
- Casts `vec` to `float32` before saving (always float32 on disk regardless of
  input dtype).
- Uses `np.save(str(p), ...)` — not atomic on all platforms; see note below.

**Invariants:**

- Saved file always has dtype `float32`.
- Shape is `[embed_dim]` (1-D), inherited from the pooling function output.

**Note:** The docstring says "atomically" but `np.save` is not truly atomic. The
caller (`_embed_song`) checks `_is_done()` before calling, so partial writes
are detected on next load by `_purge_corrupt`.

---

### `is_done(song_id: str, backbone: str, strategy: str) -> bool`

**Signature:** `is_done(song_id: str, backbone: str, strategy: str) -> bool`

| | |
| --- | --- |
| **Reads** | `_CACHE_ROOT / backbone / strategy / flat / {song_id}.npy` |
| **Writes** | May delete the file if corrupt (via `_purge_corrupt`) |
| **Returns** | `bool` |

**Returns `True` iff:** file exists AND `np.load()` succeeds without raising
`EOFError | OSError | ValueError`.

**Returns `False` when:**

- File does not exist.
- File is corrupt/unreadable — also deletes the file as a side effect.

---

### `load_pooled(song_id: str, backbone: str, strategy: str) -> np.ndarray | None`

**Signature:** `load_pooled(song_id: str, backbone: str, strategy: str) -> np.ndarray | None`

| | |
| --- | --- |
| **Reads** | `_CACHE_ROOT / backbone / strategy / flat / {song_id}.npy` |
| **Writes** | May delete file if corrupt |
| **Returns** | `np.ndarray` shape `[embed_dim]` dtype `float32`, or `None` |

**Returns `None` when:**

- File does not exist.
- File is corrupt — also deletes it via `_purge_corrupt`.

---

### `list_done_sids(backbone: str, strategy: str) -> list[str]`

**Signature:** `list_done_sids(backbone: str, strategy: str) -> list[str]`

| | |
| --- | --- |
| **Reads** | `_CACHE_ROOT / backbone / strategy / flat / *.npy` (directory glob) |
| **Writes** | Nothing |
| **Returns** | Sorted `list[str]` of `song_id` strings |

**Behaviour:** Globs `*.npy` files in the strategy directory and returns their
stems (filename without extension) sorted lexicographically.

**Invariant:** Returns `[]` if directory does not exist.

**Note:** Does NOT validate that each file is readable. The returned list may
contain IDs whose files are corrupt; those are caught when `load_pooled` is
called.

---

### `list_configs() -> set[tuple[str, str]]`

**Signature:** `list_configs() -> set[tuple[str, str]]`

| | |
| --- | --- |
| **Reads** | `_CACHE_ROOT/**/*.npy` (two-level directory walk) |
| **Writes** | Nothing |
| **Returns** | `set[tuple[str, str]]` — set of `(backbone, strategy)` pairs |

**Behaviour:** Walks the two-level directory tree
`_CACHE_ROOT/{backbone}/{strategy}/flat/` and returns every `(backbone,
strategy)` pair that contains at least one `.npy` file.

**Returns `set()` when:** `_CACHE_ROOT` does not exist.

---

### `load_matrix(backbone: str, strategy: str, con=None) -> tuple[RawTensor, list[str], list[str], list[str], list[str]]`

**Signature:**

```python
load_matrix(
    backbone: str,
    strategy: str,
    con = None,
) -> tuple[RawTensor, list[str], list[str], list[str], list[str]]
```

| | |
| --- | --- |
| **Reads** | All `.npy` files in `cache/{backbone}/{strategy}/flat/` via `list_done_sids` + `load_pooled` |
| **Reads (DB)** | `songs` table — `SELECT song_id, artist, album, genre WHERE song_id IN (...)` when `con` is provided |
| **Writes** | May delete corrupt files (via `load_pooled` → `_purge_corrupt`) |
| **Returns** | `(vecs, sids, artists, albums, genres)` |

**Return shape:**

| Field | Type | Shape / notes |
| --- | --- | --- |
| `vecs` | `RawTensor` wrapping `np.ndarray float32` | `[n, embed_dim]` |
| `sids` | `list[str]` | length `n`, sorted lexicographically (inherited from `list_done_sids`) |
| `artists` | `list[str]` | length `n`; `"unknown"` when `con=None` or song not in DB |
| `albums` | `list[str]` | length `n`; `"unknown"` when `con=None` or song not in DB |
| `genres` | `list[str]` | length `n`; `"unknown"` when `con=None` or song not in DB |

**Returns empty when:**

- No `.npy` files exist for the pair → `(RawTensor([0,0], float32), [], [], [], [])`.
- All files are corrupt (load_pooled returns None for every sid).

**Preconditions:** `con`, if provided, must have the `songs` table created by
`ensure_schema`. Songs absent from the table get `"unknown"` for all three
metadata fields without raising an error.

---

## `_embed.py` — Flat-pool embedding

### `_embed_song(...) -> bool`

**Signature:**

```python
_embed_song(
    path: Path,
    backbone_name: str,
    backbone_cfg: dict,
    load_audio_fn,          # nomarr.components.ml.audio.ml_audio_comp.load_audio_mono
    preprocess_fn,          # nomarr.components.ml.audio.ml_preprocess_comp.preprocess_for_backbone
    session,                # onnxruntime.InferenceSession (created once per backbone)
    run_in_batches_fn,      # nomarr.components.ml.onnx.ml_session_comp._run_in_batches
    batch_size: int,
    con,                    # DuckDB connection
    *,
    force: bool = False,
) -> bool
```

| | |
| --- | --- |
| **Reads (FS)** | Audio file at `path` (via `load_audio_fn`) |
| **Reads (FS)** | `cache/{backbone_name}/{strategy}/flat/{song_id}.npy` to check `_is_done()` |
| **Reads (DB)** | `songs` table — `song_exists(con, sid)` |
| **Writes (FS)** | `PATCHES_DIR / backbone_name / {song_id}.npy` — raw patch array `float32 [n_patches, embed_dim]` |
| **Writes (FS)** | `cache/{backbone_name}/{strategy}/flat/{song_id}.npy` for every strategy in `STRATEGIES` |
| **Writes (DB)** | `songs` table via `upsert_song` if song is new |
| **Returns** | `bool` — `True` if any work was done, `False` if fully skipped |

**`song_id` flow:**

- Derived deterministically from `path` via `song_id(path)` — a 12-character
  hash of the absolute path.
- Used as the filename stem for all cached files.
- Registered in the `songs` table on first encounter.

**Skip conditions (returns `False` immediately):**

- `force=False` AND `_is_done(sid, backbone_name, strategy)` returns `True` for
  **every** strategy in `STRATEGIES`. The check is an `all()` over all 6
  strategies; partial completion causes re-processing of any missing strategies.

**Error/skip conditions during processing:**

- `load_audio_fn` raises any exception → re-raised as `RuntimeError("Audio load
  failed: {path}")`; propagates to the `embed()` loop which catches it and
  increments the error counter.
- `preprocess_fn` returns `None` or empty patches → returns `False` (song
  silently skipped; no DB write, no patch file).

**`backbone_cfg` keys used:**

- `backbone_cfg["backbone_name"]` — passed to `preprocess_fn` as the backbone
  identifier (e.g. `"effnet"` or `"musicnn"`).

**Patch sidecar invariant:** Written only if `force=True` OR the sidecar does
not already exist. Content is `float32 [n_patches, embed_dim]` where
`n_patches` is determined by `preprocess_fn`.

**Per-strategy pooled vector invariant:** Written only if `force=True` OR
`_is_done()` is `False` for that specific strategy. The value is the output of
the pooling function cast to `float32`.

---

### `embed(con, *, song_ids=None, force=False, backbones=None, device='cpu') -> None`

**Signature:**

```python
embed(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    device: str = "cpu",
) -> None
```

| | |
| --- | --- |
| **Reads (FS)** | All audio files discovered by `discover_audio()` under `MEDIA_ROOT` |
| **Reads (config)** | `BACKBONES` registry; `_BACKBONE_BATCH_SIZE` per backbone |
| **Writes (FS)** | Patch sidecars and pooled vectors (via `_embed_song`) |
| **Writes (DB)** | `songs` table entries (via `_embed_song`) |
| **Returns** | `None` |

**`song_ids` flow:**

- When `song_ids` is a `frozenset[str]`, `audio_paths` is filtered to only
  those paths whose `song_id(path)` is a member of the set.
- When `None`, all discovered audio paths are processed.

**Backbone filtering:**

- `backbones=None` → iterates over all keys in `BACKBONES` (`"effnet"`,
  `"musicnn"`).
- `backbones=["effnet"]` → only the named backbones are processed.

**Session lifecycle:** One `onnxruntime.InferenceSession` is created per
backbone (not per song). The session is shared across all songs for that
backbone.

**Error handling:** Exceptions from `_embed_song` are caught per-song;
errors increment a counter and processing continues. The error message is
printed via `tqdm.write`. Errors do not abort the backbone loop.

**Preconditions:**

- `PATCHES_DIR` is created unconditionally before the backbone loop.
- `bootstrap_nomarr()` is called first to ensure nomarr imports are resolvable.

---

## Flat-pool analysis (consolidated into `common/analyze.py`)

> **Not an independent module.** The historical `strategy_global_pool/_analyze.py` module
> (`_analyze_strategy`, `_analyze_ptc_vs_ctp`, `_analyze_ann`, `analyze`) was removed from the
> tree; `strategy_global_pool/` now contains only `__init__.py`, `_embed.py`, and `segment_fn.py`.
> Flat (global-pool) retrieval analysis runs through the shared analyze phase in
> `common/analyze.py` — entry point `common.analyze.analyze(con, cfg, *, song_ids, force,
> backbones, k)` — wired from `run.py::_analyze_phase` via `GLOBAL_POOL_ANALYZE_CFG`
> (`strategy_type="global_pool"`, `strategy_names` from `pooling.STRATEGIES`, `load_vecs_fn`
> reading the flat cache via `cache/flat_vecs.py`, `db_write_fn` = `db.write_analyze_metrics`).

**Live entry point:** `common.analyze.analyze(con, GLOBAL_POOL_ANALYZE_CFG, **kw)`.

- Reads pooled flat vectors from `cache/{backbone}/{strategy}/flat/*.npy` via
  `cache/flat_vecs.load_matrix` (which also joins artist/album/genre metadata from the `songs` DB
  table when a connection is provided).
- For each `(backbone, strategy_name)` pair it computes retrieval rows for all `METRICS`
  (`"cosine"`) and writes them via `GLOBAL_POOL_ANALYZE_CFG["db_write_fn"]`.
- A pair is considered **done** when all `METRICS` keys are recorded with a non-zero `n_songs`
  that is not stale relative to `cache/flat_vecs.list_done_sids(backbone, strategy)` (a grown
  corpus forces a recompute).
- No `flat_ref/` files are written by any analysis path; the persistent flat representation is the
  per-backbone filesystem cache `cache/{backbone}/{strategy}/flat/{song_id}.npy`.
---

## Truncation robustness (`_truncate.py`) — NOT an active phase

> **Removed module.** The historical `_truncate.py` module (`_flat_rep`, `_binned_rep`, `_cosine`,
> `analyze_truncation`) was removed from the tree — no `_truncate.py` exists anywhere in the
> repository. `run.py` `_PHASES` has no `truncate` phase (phases are `ingest`, `embed`, `stratify`,
> `segment`, `classify`, `analyze`, `head`, `report`) and no `--skip-truncation` CLI flag exists.
> Truncation robustness analysis is **not an active pipeline phase**; the functions documented here
> are dead references and have been removed.
---

## Cross-cutting invariants

1. **`song_id` is always a 12-character hash** derived from the absolute
   filesystem path via `config.song_id(path)`. It is used as the filename stem
   in every cache file and as the primary key in the `songs` DB table.

2. **All pooled vectors are stored as `float32`** regardless of the dtype
   produced by the pooling function or ONNX session output.

3. **Flat cache key pattern:** `cache/{backbone}/{strategy}/flat/{song_id}.npy` — the per-backbone
   filesystem cache written and read by `cache/flat_vecs.py`. Each file is a `float32 [embed_dim]`
   pooled vector; presence of the file is the canonical "done" signal for that
   (song, backbone, strategy) combination.

4. **Per-backbone keying:** the cache root is `OUTPUT_ROOT/cache/{backbone}/{strategy}/flat/`, so
   a given `{song_id}` is never shared between backbones or strategies — the key always includes
   the backbone and strategy names. No `flat_ref/` upper-triangle/sids files exist; flat-binned
   Spearman uses the same per-backbone flat cache, not any `flat_ref/` directory.

5. **`act[1]` is the head score used throughout the flat (global-pool) strategy.** `act[0]`
   (negative-class probability) is never read. Absent songs default to `0.0`.

6. **ANN sweep is always on `strategy="mean"` only**, regardless of which
   strategies triggered the `analyze()` call.

7. **`list_done_sids` does not validate readability** — it returns stems of all
   `.npy` files. Corrupt files are detected lazily when `load_pooled` is called.

8. **`genres` in retrieval metrics** comes from the `songs.genre` column joined
   inside `load_matrix`. It is never inferred from the filesystem.

---

## 5. Binned Strategy (strategy_binned/)

## Module-level constants — `_constants.py`

### `AGG_METHODS: list[str]`

- **Source:** `research_config.toml` → `pooling.hypotheses.weighted_reductions` (the legacy weighted hypothesis block); default when absent `["target_weighted", "bidirectional_weighted", "normalized_mean_pair_weighted"]`.
- **Validation:** each value must be in `_ALLOWED_AGG_METHODS = ("target_weighted", "bidirectional_weighted", "normalized_mean_pair_weighted")`; legacy generic reductions (`mean`/`median`/`max`/`min`) and `agg_method="medoid"` are rejected at module load (`ValueError` raised).
- **Invariant:** exactly the three weighted reductions; agg_mats are keyed by this list. They are labelled **legacy weighted hypotheses** — opt-in comparison formulas, never default primary semantics.

### `PRIMARY_SCORE_VARIANT: str`

- **Value:** `"max_per_candidate_segment"` — the authoritative follow-on primary score (one patch-count-weighted contribution per candidate segment, with collision/winner/cosine/contribution traces).

### `SCORE_VARIANTS: list[str]`

- **Source:** `research_config.toml` → `pooling.score_variants`.
- **Validation:** each value must be in `_ALLOWED_SCORE_VARIANTS` (the primary variant plus the three weighted hypotheses); a generic `mean`/`median`/`max`/`min`/`medoid` aggregate is rejected by `validate_score_variant`.
- **Invariant:** the shipped config sets `pooling.score_variants=["max_per_candidate_segment"]`, so the evaluated surface is **primary-only** and the weighted hypotheses run only when explicitly added to that key. When `pooling.score_variants` is **absent** from the config, the fallback is the full surface `[PRIMARY_SCORE_VARIANT, *AGG_METHODS]` (primary plus all three weighted hypotheses).

### `REP_TYPES: list[str]`

- **Source:** `research_config.toml` → `pooling.rep_types`; default primary `["medoid"]` (observed per-bin segment representation).
- **Validation:** `_ALLOWED_REP_TYPES = ("mean", "median", "medoid", "max", "min")` — a separate set that includes `"medoid"` (allowed as a representation). Used for **representation** only, never for aggregation.
- **Invariant:** `"medoid"` is allowed *as a representation* (observed per-bin patch row), distinct from the aggregation set `AGG_METHODS`.

### `SIM_METRICS: list[str]`

- **Source:** `research_config.toml` → `similarity.metrics`; default `["cosine"]`.

### `_EXPECTED_ROWS_PER_CONFIG: int`

- `len(REP_TYPES) × len(REP_TYPES) × len(SIM_METRICS) × len(AGG_METHODS)` — **retained for reference only; not referenced by code** (0 call sites). This is a legacy formula from the pre-score-variants cross-product era; it is superseded by the `score_variants` iteration in `common/analyze.py` and is kept only to preserve history.

### `_BIN_POOL_STRATEGIES: dict[str, Callable[[np.ndarray], np.ndarray]]`

- Maps `"mean"`, `"median"`, `"max"`, `"min"` to their numpy axis-0 reductions over a `[n_seg, D]` float32 array. `"medoid"` **is present** as well (`_constants.py:67`) — it selects the observed segment row closest to the centroid — and the observed-patch payload is built separately via `_build_medoid_payload`.

---

## `_pool.py`

### `select_medoid_index(unit_seg: np.ndarray) -> tuple[int, float]`

- **Reads:** nothing external.
- **Writes:** nothing.
- **Input:** `unit_seg [n, D]` — unit-normalised rows.
- **Returns:** `(local_idx: int, centrality: float)` where `local_idx` is the row whose cosine similarity to all other rows is highest (argmax of row-mean of sim matrix). For `n == 1` returns `(0, 1.0)`.
- **Invariant:** deterministic; argmax resolves ties by choosing the smallest index.

### `_build_pool_payload(raw_patches, unit_patches, indices, pool_fn) -> dict`

- **Reads:** slices of `raw_patches.data` and `unit_patches.data` at `indices`.
- **Writes:** nothing.
- **Returns:** dict with keys:
  - `vec_raw: RawVector` — `pool_fn(raw_seg)` unnormalised
  - `vec_norm: UnitVector` — `pool_fn(unit_seg)` re-normalised via `UnitVector` setter
  - `vec_unit: UnitVector` — alias for `vec_norm`
  - `source_indices: list[int]`
  - `selected_local_idx: None`, `selected_global_idx: None`, `medoid_centrality: None`
  - `weight: int` — `len(indices)`
- **Invariant:** `vec_norm` is always a unit vector.

### `_build_medoid_payload(raw_patches, unit_patches, indices) -> dict`

- **Reads:** same slices.
- **Writes:** nothing.
- **Returns:** same key set as `_build_pool_payload` but:
  - `selected_local_idx: int` — index within `indices`
  - `selected_global_idx: int` — `indices[selected_local_idx]`
  - `medoid_centrality: float`
  - `vec_raw` and `vec_norm` are the **observed** patch row at `selected_global_idx`, not a synthetic aggregate.

### `_pool_segment(raw_patches: RawTensor, unit_patches: UnitTensor, indices: list[int]) -> dict[str, dict]`

- **Reads:** nothing external.
- **Writes:** nothing.
- **Returns:** `{strategy_name: payload_dict}` for every key in `_BIN_POOL_STRATEGIES` that is also in `REP_TYPES` (i.e. the returned key set is `_BIN_POOL_STRATEGIES ∩ REP_TYPES`, config-driven via `[pooling].rep_types`). With the checked-in `rep_types=['medoid']` this is `{"medoid"}`. `medoid` is present in both `_BIN_POOL_STRATEGIES` (the observed-patch argmin path) and `REP_TYPES`. All payloads are for the same `indices`.
- **Invariant:** key set is `_BIN_POOL_STRATEGIES ∩ REP_TYPES` (config-driven), independent of `AGG_METHODS` (which holds only the three weighted reductions).

---

## `_features.py`

### `_extract_patch_features(path: Path | str, n_patches: int) -> list[dict] | None`

- **Reads:** audio file at `path`, loaded at `_BACKBONE_SR = 16_000 Hz`.
- **Writes:** nothing.
- **Returns:** list of `n_patches` dicts with keys `rms: float`, `spectral_centroid: float`, `onset_strength: float`, `chroma_key: int`. Returns `None` if `librosa` is unavailable, `n_patches < 1`, or audio load fails.
- **Precondition:** librosa must be importable; otherwise returns `None` silently.
- **Invariant:** output list length equals `n_patches` exactly when not `None`.

### `_run_head_batch(session, vecs: np.ndarray) -> np.ndarray`

- **Reads:** nothing external.
- **Writes:** nothing.
- **Input:** `session` — ONNX InferenceSession; `vecs [N, D]` float32.
- **Returns:** `[N, n_classes]` float32 activations.
- **Precondition:** session must expose input `"embeddings"` and output `"activations"`.

---

## `_calibrate.py`

### `_load_cached_calibration(con, backbone: str) -> dict[str, dict] | None`

- **Reads:** DB — calls `_db.load_calibration(con, backbone, bin_mode)` for each `bin_mode` in `BIN_MODES`.
- **Writes:** nothing.
- **Returns:** `{bin_mode: stats_dict}` or `None` if no per-mode rows exist. Falls back from the legacy single-row format (`"p50"` key present) to per-mode rows.

### `_calibrate(con, backbone: str, audio_paths: list[Path], force: bool = False) -> dict[str, dict]`

- **Reads:**
  - Filesystem: sidecar `.npy` files at `patches_path(song_id, backbone)` for each path in `audio_paths`.
  - DB: existing calibration rows (skipped when `force=True` or absent).
- **Writes:**
  - DB: upserts one calibration row per `dist_mode` via `_db.upsert_calibration`.
- **Returns:** `{dist_mode: {p10, p25, p50, p75, mean_d, sigma_d, n_patches}}` for every dist mode in `_DIST_FNS`.
- **Precondition:** sidecar files must be at least 2 rows; shorter files are silently skipped.
- **Invariant:** centroids are renormalised to the unit sphere before computing distances.

---

## `cache/binned_ptc.py` — PTC filesystem cache

### Path layout

```
{OUTPUT_ROOT}/cache/binned_ptc/{cache_semantics_tag()}/{backbone}/{bin_mode}/{_threshold_key(std_thresh)}/{song_id}.npz
```

The `cache_semantics_tag()` value is embedded in `CACHE_BASE` at module import; changing algorithm semantics requires a tag bump to invalidate old caches.

### `cache_path(backbone, bin_mode, std_thresh, song_id) -> Path`

- Pure path construction; no I/O.

### `config_dir(backbone, bin_mode, std_thresh) -> Path`

- Pure path construction; no I/O.

### `list_done_keys() -> set[tuple[str, str, str, float]]`

- **Reads:** filesystem — walks `CACHE_BASE` directory tree.
- **Returns:** set of `(song_id, backbone, bin_mode, std_thresh)` for every `.npz` file found.
- **Writes:** nothing.
- **Returns empty set** if `CACHE_BASE` does not exist.

### `list_configs(backbone: str | None = None) -> set[tuple[str, str, float]]`

- **Reads:** filesystem — walks one or all backbone subdirs.
- **Returns:** `(backbone, bin_mode, std_thresh)` tuples for every config directory that contains at least one `.npz`.

### `list_sids(backbone, bin_mode, std_thresh) -> list[str]`

- **Reads:** filesystem — `config_dir(...).glob("*.npz")`.
- **Returns:** sorted list of `song_id` strings (stems of `.npz` filenames).

### `save(backbone, bin_mode, std_thresh, song_id, bulk_vecs, bulk_heads) -> None`

**Signature:**

```python
def save(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
    bulk_vecs: list[tuple],   # see schema below
    bulk_heads: list[tuple],  # see schema below
) -> None
```

**`bulk_vecs` row schema** (15-element tuple):

```
(sid, backbone, bin_mode, std_thresh, bin_id, pool_strategy,
 vec_raw_bytes, vec_norm_bytes, weight, outlier_count,
 selected_global_idx, selected_local_idx, medoid_centrality,
 bin_start_idx, bin_end_idx)
```

**`bulk_heads` row schema** (8-element tuple):

```
(sid, backbone, head_name, bin_mode, std_thresh, bin_id, act_bytes, seg_size)
```

- **Reads:** nothing.
- **Writes:** one `.npz` file at `cache_path(...)`. Creates parent dirs.
- **npz arrays written:**
  - `weights [n_bins] int32`, `outliers [n_bins] int32`, `bin_start_idx [n_bins] int32`, `bin_end_idx [n_bins] int32`
  - `pool_{strategy}_raw [n_bins, D] float32` per strategy
  - `pool_{strategy}_norm [n_bins, D] float32` per strategy
  - `pool_{strategy}_selected_global_idx [n_bins] int32` per strategy
  - `pool_{strategy}_selected_local_idx [n_bins] int32` per strategy
  - `pool_{strategy}_centrality [n_bins] float32` per strategy
  - `head_{head_name} [n_bins, n_classes] float32` per head
- **Early return** if both `bulk_vecs` and `bulk_heads` are empty.
- **Invariant:** bins are written in sorted bin_id order.

### `load_bins(backbone, bin_mode, std_thresh, song_id, *, vec_type="raw") -> list[dict]`

- **Reads:** one `.npz` file.
- **Writes:** nothing.
- **Returns:** list of `n_bins` dicts with keys:
  - `bin_id`, `weight`, `outlier_count`, `bin_start_idx`, `bin_end_idx`
  - `vec_{strategy}` — raw or norm array per strategy present
  - `{strategy}_selected_global_idx`, `{strategy}_selected_local_idx`, `{strategy}_centrality` (optional, present when key exists)
- **On corrupt file:** purges the `.npz` and returns `[]`.

### `load_bin_stats(backbone, bin_mode, std_thresh, song_id) -> list[dict]`

- **Reads:** one `.npz` file — only `weights`, `outliers`, and one representative vector.
- **Writes:** nothing.
- **Returns:** list of `n_bins` dicts: `{bin_id, weight, outlier_count, vec_mean}` where `vec_mean` is sourced from `pool_mean_raw` → fallback to `pool_median_raw` → `pool_medoid_raw` → first available `pool_*_raw` key.
- **Use:** lightweight call for `_compute_song_stats`; avoids loading all four strategy arrays.

### `load_norm_pair(backbone, bin_mode, std_thresh, song_id, rep_a, rep_b) -> tuple[UnitTensor, UnitTensor]`

- **Reads:** one `.npz` file — exactly `pool_{rep_a}_norm` and `pool_{rep_b}_norm` keys.
- **Writes:** nothing.
- **Returns:** `(UnitTensor([n_bins, D]), UnitTensor([n_bins, D]))`. When `rep_a == rep_b`, both return values share the same underlying array.
- **On corrupt file:** returns two empty `(0, 0)` tensors.
- **Invariant:** opens and closes the `.npz` in a single `try/finally` block.

### `load_head_acts(backbone, bin_mode, std_thresh, song_id) -> tuple[dict[str, np.ndarray], np.ndarray] | tuple[None, None]`

- **Reads:** one `.npz` file — keys prefixed `head_`, and `weights`.
- **Writes:** nothing.
- **Returns:** `(head_acts, weights)` where `head_acts` maps `head_name -> float32 [n_bins, n_classes]`, `weights` is `int32 [n_bins]`. Returns `(None, None)` when no `head_*` keys are present or file does not exist.
- **Key stripping:** the `head_` prefix is removed when building the dict keys.

---

## `cache/binned_ctp.py` — CTP filesystem cache

### Path layout

```
{OUTPUT_ROOT}/cache/binned_ctp/{cache_semantics_tag()}/{backbone}/{head}/{_threshold_key(std_thresh)}/{song_id}.npz
```

Adds one extra `{head}` path segment relative to the PTC layout.

### `cache_path(backbone, head, std_thresh, song_id) -> Path`

- Pure path construction; no I/O.

### `config_dir(backbone, head, std_thresh) -> Path`

- Pure path construction; no I/O.

### `is_done(backbone, head, std_thresh, song_id) -> bool`

- **Reads:** filesystem — opens `.npz` to verify readability.
- **Writes:** may delete corrupt `.npz`.
- **Returns:** `True` iff the file exists and `np.load` succeeds without exception.

### `query_ctp_configs() -> set[tuple[str, str, float]]`

- **Reads:** filesystem — walks `CACHE_BASE` three levels deep.
- **Returns:** `(backbone, head, std_thresh)` for every non-empty config directory.

### `list_done_keys() -> set[tuple[str, str, str, float]]`

- **Reads:** filesystem.
- **Returns:** `(song_id, backbone, head, std_thresh)` for every `.npz` file.

### `save(backbone, head, std_thresh, song_id, bulk_vecs) -> None`

**`bulk_vecs` row schema** (15-element tuple — same as PTC but with `head` substituted for `bin_mode`, per the strategy segment fn):

```
(sid, backbone, head, std_thresh, bin_id, pool_strategy,
 vec_raw_bytes, vec_norm_bytes, weight, outlier_count,
 selected_global_idx, selected_local_idx, medoid_centrality,
 bin_start_idx, bin_end_idx)
```

- **Reads:** nothing.
- **Writes:** one `.npz` file at `cache_path(...)`.
- **npz arrays:** same pool strategy arrays as PTC cache; **no** `head_*` activation arrays (CTP cache does not store head activations).

### `load_all_reps(con, backbone, head, std_thresh, song_ids=None) -> tuple[list[str], list[str], list[list[dict]]]`

**Signature:**

```python
def load_all_reps(
    con,
    backbone: str,
    head: str,
    std_thresh: float,
    song_ids: frozenset[str] | None = None,
) -> tuple[list[str], list[str], list[list[dict]]]
```

- **Reads:**
  - Filesystem: all `.npz` files in `config_dir(backbone, head, std_thresh)`.
  - DB: `songs` table — `SELECT song_id, artist FROM songs WHERE song_id = ANY(?)` for artist labels.
- **Writes:** may delete corrupt `.npz` files.
- **Returns:** `(sids, artists, song_data)` — three co-indexed lists where index `i` refers to the same song.
  - `sids: list[str]` — sorted song_ids
  - `artists: list[str]` — artist label per song; defaults to `"unknown"` when absent in DB
  - `song_data: list[list[dict]]` — per-song list of bin dicts, each bin having:
    - `bin_id, weight, outlier_count, bin_start_idx, bin_end_idx`
    - `vec_{strategy}` (alias for raw)
    - `vec_{strategy}_raw [D] float32` for each pool strategy
    - `vec_{strategy}_norm [D] float32` when norm key present
    - `{strategy}_selected_global_idx`, `{strategy}_selected_local_idx`, `{strategy}_centrality` (optional)
- **Filtering:** songs with any bin missing any of the `REP_TYPES` `pool_{rep}_raw` keys are excluded entirely.
- **Returns `([], [], [])` when** the config dir does not exist.
- **Alignment invariant:** `sids[i]`, `artists[i]`, and `song_data[i]` are always the same song. The DB-resolved artist labels are looked up in one batch query before the loop.

---

## `cache/sim.py` — REMOVED in Plan C

The write-only `sim_pairs` cache path and the zero-caller `cache/sim.py` module
(`sim_cache_path` / `load_sim` / `save_sim`) were **removed** in Plan C.  The
caller audit proved no active consumer — `analyze` composes
`compute_agg_mats` + `compute_retrieval_rows` directly and never read or wrote a
similarity-matrix cache.  There is no `sim/` cache directory and no `sim_cache`
reset path in `run.py`.  The in-memory per-bin pairwise similarity matrices built
inside `similarity.py` remain fully live (they are inputs to the agg reductions);
only the disk cache for them is gone.

---

## `corpus.py` — matching corpus manifests (added in Plan C)

Every analyzed backbone (EffNet, MusicNN) gets its **own independent** matching
corpus: the deterministic, canonically-sorted set of song IDs that all flat and
binned configurations for that backbone compare.  A song participates only if it
is present in every required dataset (flat vectors, PTC bins, and CTP bins only when
[archival_ctp] enabled=true), so all compared configurations run on exactly the same
song set.

### `class MatchingCorpusManifest`

```python
@dataclass(frozen=True)
class MatchingCorpusManifest:
    song_ids: tuple[str, ...]  # canonically sorted; immutable
    corpus_hash: str           # sha256 hex of the backbone + eligible corpus
    backbone: str              # "effnet" | "musicnn"
```

- **Canonically sorted and immutable:** constructed sorted; the corpus hash is
  order-insensitive but data-sensitive.
- **Equality and the hash are order-insensitive** across the constructor input
  (the stored tuple is canonicalized to a sorted tuple in `__post_init__`, and
  `corpus_identity_hash` sorts the song IDs before hashing).

### `corpus_identity_hash(backbone: str, eligible_song_ids: Collection[str], eligibility_inputs: Mapping[str, object] | None = None) -> str`

Deterministic sha256 over the backbone, the eligible song IDs, and (when given)
eligibility inputs.  Order-insensitive: the song IDs are canonically sorted
before hashing, so any change in corpus membership or eligibility gives a new
hash, but reordering the same song set does not.

### `build_matching_corpus(backbone: str, candidate_song_ids: Collection[str], available_by_requirement: Mapping[str, Collection[str]], *, eligibility_inputs: Mapping[str, object] | None = None) -> MatchingCorpusManifest`

Intersects the song sets of every requirement (each dataset's available song
list) over the candidate universe, sorts the surviving IDs, and returns the
manifest.  A song missing from any single required dataset is excluded.

### `validate_matching_corpus(manifest: MatchingCorpusManifest, song_ids: Sequence[str], context: str) -> None`

Raises `ValueError` if `song_ids` differ from `manifest.song_ids` in **set or
order**.  This is the fail-loud boundary in `common/analyze.py`: a loader that
returns a different corpus (or the same corpus reordered) is rejected and the
config is skipped — the code never silently intersects or reorders.

---

## `cache_identity.py` — versioned matrix-cache identity (added in Plan C)

```python
SCORING_SEMANTICS_VERSION = 1
```

The representation-pair (per-bin similarity matrix) caches are keyed on a hash
that includes the scoring-semantics version **and** the matching-corpus hash, so
changes to either invalidate the cache by pointing at a different root.

### `matrix_cache_identity(*, backbone, pathway, threshold, rep_a, rep_b, aggregate, metric, song_ids, corpus_hash) -> str`

sha256 hex digest of every dimension above (backbone, pathway, threshold, the
representation pair, aggregate, metric, the song-ID set **and order**, and the
corpus hash).  Two corpora with identical rep names but different underlying
arrays have different `corpus_hash` values and therefore never collide.

### `validate_matrix_cache_identity(expected_identity: str, stored_identity: str | None, context: str) -> None`

Raises `ValueError` if `stored_identity` is not `None` and differs from
`expected_identity`.  A `None` stored identity (fresh path) is allowed.  This is
the load-boundary check that rejects a stale corpus's cache entry.

### `versioned_cache_root(base: Path, *, scoring_version: int = SCORING_SEMANTICS_VERSION, corpus_hash: str | None = None) -> Path`

Returns `base / v{scoring_version} / {corpus_hash}`.  A scoring-semantics version
bump or corpus change selects a different root: the old root is **preserved on
disk but never read** (a version bump therefore cannot serve stale data).

---

## `common/analyze.py` — `skip_reasons` diagnostics (added in Plan C)

`analyze` appends human-readable reasons to `cfg["extra_cfg"]["skip_reasons"]`
(a `list[str]`) whenever a configuration is skipped.  Every skip is **recorded**
and the config emits **no row**.  Recorded reasons include:

- `"< 2 matching-corpus songs (incomplete sidecars/bins/reps)"` — fewer than two
  songs survive the matching corpus, so no pair can be compared.
- `"matching-corpus song-ID set mismatch"` — the loader returned a different
  song set than the manifest.
- `"matching-corpus song-ID order mismatch"` — the loader returned the same set
  in a different order (never silently reordered).
- any loader exception is caught and recorded as a load-failure skip.

---

## `_process.py`

### `_compute_song_stats(sid, bins_list, backbone, bin_mode, std_thresh, con) -> None`

- **Reads:** `bins_list` in memory (list of bin dicts from `load_bin_stats`).
- **Writes:** DB — upserts `binned_song_stats` row via `_db.upsert_binned_song_stats`.
- **Stats written:** `n_bins`, `n_patches`, `n_outliers`, `min_bin_size`, `max_bin_size`, `mean_bin_size`.

### `compute_agg_mats(norm_a, norm_b, weights_a, weights_b, metric, *, progress=None) -> dict[str, np.ndarray]`

**Signature:**

```python
def compute_agg_mats(
    norm_a: list[UnitTensor],     # [n_songs], each [n_bins_i, D]
    norm_b: list[UnitTensor],     # [n_songs], each [n_bins_i, D]
    weights_a: list[np.ndarray],  # [n_songs], each [n_bins_i] float
    weights_b: list[np.ndarray],  # [n_songs], each [n_bins_i] float
    metric: str,                  # "cosine" (l2 removed)
    *,
    progress=None,                # optional tqdm progress object
) -> dict[str, np.ndarray]       # AGG_METHODS -> [n, n] float32
```

- **Reads:** nothing external.
- **Writes:** nothing.
- **Returns:** one `[n_songs, n_songs] float32` matrix per configured aggregate name (`AGG_METHODS`).
- **Ordered pairs:** every ordered `(i, j)` pair is evaluated independently, including `i > j` and the diagonal. The diagonal follows the same reduction formula — it is **not** unconditionally set to `1.0` (the single-bin identical-rep self-comparison still yields exactly `1.0` from cosine).
- **No mirroring:** forward `S_ij = norm_a[i] @ norm_b[j].T` and reverse `S_ji = norm_a[j] @ norm_b[i].T` are computed separately; no `rep_a == rep_b` or symmetric-similarity assumption.
- **Weights:** `weights_a[i]` weights the source bins of `norm_a[i]`; `weights_b[j]` weights the target bins of `norm_b[j]`. These are the per-song temporal patch-count weights.
- **Aggregation:** each `AGG_METHODS` entry dispatches to the corresponding pure reduction in `_weighted.py`; an unknown/legacy agg raises `ValueError` (legacy generic reductions and `agg_method=medoid` are rejected).
- **Invariant:** `norm_a[i].data` rows are guaranteed unit-normalised by the `UnitTensor` setter before this function is called.

### `compute_retrieval_rows(agg_mats, artists, backbone, bin_mode, std_thresh, rep_a, rep_b, metric, k, n_songs, *, albums, genres, flat_upper_tri, flat_sids, current_sids, head_scores, head_names) -> tuple[list[_BinnedRetrievalRow], list[tuple]]`

**Signature:**

```python
def compute_retrieval_rows(
    agg_mats: dict[str, np.ndarray],
    artists: list[str],
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    rep_a: str,
    rep_b: str,
    metric: str,
    k: int,
    n_songs: int,
    *,
    albums: list[str] | None = None,
    genres: list[str] | None = None,
    flat_upper_tri: np.ndarray | None = None,     # upper-triangle of flat sim matrix
    flat_sids: list[str] | None = None,           # song order for flat_upper_tri
    current_sids: list[str] | None = None,        # song order for agg_mats
    head_scores: list[list[float]] | None = None, # from common/analyze.py::_load_head_scores_and_names
    head_names: list[str] | None = None,
) -> tuple[list[_BinnedRetrievalRow], list[tuple]]
```

- **Reads:** nothing from disk itself; `flat_upper_tri` / `flat_sids` are passed in as pre-loaded arguments. The **only current caller** is `_optimize.py:328`, which passes no `flat_upper_tri` / `flat_sids` / `current_sids`, so Spearman is never activated in the pipeline. (Note: `_optimize.py:327` is the preceding `compute_agg_mats` call; `compute_retrieval_rows` is called at `:328`. The only other reference is the **dead** legacy wrapper `_process_group` at `_process.py:330`, which is not invoked by any live pipeline path.) The live analysis path does **not** compose `compute_retrieval_rows` — `common/analyze.py` computes metrics via `similarity.compute_retrieval_metrics` directly.
- **Writes:** nothing.
- **Returns:** `(rows, per_head_rows)` where `rows` has one `_BinnedRetrievalRow` per `AGG_METHODS` entry, and `per_head_rows` has one tuple `(backbone, bin_mode, std_thresh, rep_a, rep_b, metric, agg, k, h_name, corr)` per head per agg.
- **Spearman computation:** implemented but dormant — runs only when `flat_upper_tri is not None and flat_sids is not None and current_sids is not None`. Because no pipeline caller supplies those arguments (see note above), `flat_binned_spearman` and `flat_binned_beneficial_reorder_rate` are always `None` in practice. The "no overlap" branch is described for correctness: when `len(common) < 2` (fewer than 2 shared songs), the two Spearman fields are set to `None` rather than skipping the function.
- **`head_scores` here** is `head_scores_for_retrieval` from the caller — per-head mean/ptc scores read from the filesystem cache by `common.analyze.py::_load_head_scores_and_names` (which reads `cache.flat_heads` mean/ptc activations via `cache.flat_heads.load_bulk`), not from `_db.load_song_head_scores` or any `query_flat_head_labels`. It is passed directly to `_compute_retrieval_metrics`.

### `_process_group(norm_a, norm_b, bin_counts, artists, rep_a, rep_b, metric, backbone, bin_mode, std_thresh, k, progress, albums, genres, head_scores, head_names, n_songs) -> tuple[list[_BinnedRetrievalRow], list[tuple]]`

- **Compatibility wrapper** retained for legacy callers; **not invoked by any live pipeline path** (dead). It forwards its arguments to `compute_agg_mats` + `compute_retrieval_rows`, but the live shared analysis path (`common.analyze.analyze`) does **not** compose `compute_retrieval_rows` — it calls `similarity.compute_retrieval_metrics` directly (see the caller note under `compute_retrieval_rows` above). This wrapper's `head_scores` / `head_names` / `progress` parameters therefore have no independent semantics.

---

## `_weighted.py`

Pure weighted directional scoring reductions (Part B). They read only their `np.ndarray`
arguments, perform no I/O, accumulate in float64, and return a Python `float`; the caller
casts matrix outputs to float32.

**Ordered-pair convention:** `S[a, b]` is the similarity from **source bin** `a` of song A to
**target bin** `b` of song B (rows = source bins, columns = target bins). For a directional
pair `(A, B)` the matrix has shape `(n_A, n_B)`. `w_A`/`w_B` are **positive temporal
patch-count weights**. Ordered song pairs are evaluated independently; the reverse matrix is
*separately supplied* and never derived by transposing/copying the forward matrix.

**Aggregate keys** (`_constants.AGG_METHODS`): `["target_weighted",
"bidirectional_weighted", "normalized_mean_pair_weighted"]` — exactly the three supported
Part B reductions. Legacy generic reductions and `agg_method=medoid` are rejected at the
validation boundary in `_constants.py`; `rep_type=medoid` remains a valid per-bin
representation (REP_TYPES unchanged).

### `target_weighted(pair_similarity: np.ndarray, target_weights: np.ndarray) -> float`

Mean over source rows of the target-weighted row means:
`(1/n_A) * sum_a( sum_b(w_target[b] * S[a,b]) / sum_b(w_target[b]) )`.
`target_weights` must be 1-D with length == column dimension; zero total weight raises
`ValueError`.

### `normalized_mean_pair_weighted(pair_similarity: np.ndarray, source_weights: np.ndarray, target_weights: np.ndarray) -> float`

Weighted global bilinear mean:
`sum_ab(w_A[a] * w_B[b] * S[a,b]) / (sum_a(w_A[a]) * sum_b(w_B[b]))`.
`source_weights` length must equal the row dimension; `target_weights` length the column
dimension; a zero-total weight on either side raises `ValueError`.

### `bidirectional_weighted(forward_similarity, reverse_similarity, forward_target_weights, reverse_target_weights) -> float`

Arithmetic mean of the two separately-supplied directional scores:
`(target_weighted(fwd, w_fwd_tgt) + target_weighted(rev, w_rev_tgt)) / 2`. The reverse
matrix is a separate input — never a transpose/copy of the forward matrix. Symmetric only
when the reverse direction is supplied consistently.

### Validation contract

- Similarity inputs must be 2-D (source x target); wrong ndim raises `ValueError`.
- Every weight vector must be 1-D and length-match its dimension; mismatch raises `ValueError`.
- Zero-total-weight inputs (denominator undefined) raise `ValueError`.

---

## `_sample.py`

### `_select_stratified_sample(con, sample_size: int, seed: int, n_buckets: int = 4) -> list[str]`

**Signature:**

```python
def _select_stratified_sample(
    con,
    sample_size: int,
    seed: int,
    n_buckets: int = 4,
) -> list[str]
```

- **Reads:** DB — `_db.load_binned_sampling_stats(con)` — rows with `{song_id, artist, n_configs, avg_n_bins, avg_n_patches, avg_n_outliers, avg_mean_bin_size}`.
- **Writes:** nothing.
- **Returns:** list of `song_id` strings, deterministically sampled.
- **Strategy:** each song is bucketed on two axes (`avg_n_bins` quantile × artist-popularity bucket), then a proportional allocation with largest-remainder rounding fills strata. Within each stratum, a per-stratum BLAKE2b-seeded RNG shuffles before selection.
- **Invariant:** returns all rows when `sample_size <= 0` or `sample_size >= total`.

---

## Binned analysis (consolidated into `common/analyze.py`)

> **Not an independent module.** The historical binned `_analyze.py` module (`_blas_ctx`,
> `_build_ctp_rep_tensors`, `_compute_head_agreement`, `analyze`, `analyze_ctp`) was removed from
> the tree — `strategy_binned/` contains no `_analyze.py`. Binned (PTC/CTP) retrieval analysis runs
> through the shared analyze phase in `common/analyze.py` — entry point
> `common.analyze.analyze(con, cfg, *, song_ids, force, backbones, k)` — wired from
> `run.py::_analyze_phase` via `PTC_ANALYZE_CFG` (`strategy_type="ptc"`, rep types from
> `strategy_binned/_constants.REP_TYPES`) and `CTP_ANALYZE_CFG` (`strategy_type="ctp"`, per-head
> threshold strategy names).

**Live entry points:**

- `common.analyze.analyze(con, PTC_ANALYZE_CFG, **kw)` — patch-to-centroid binned retrieval.
- `common.analyze.analyze(con, CTP_ANALYZE_CFG, **kw)` — centroid-to-patch binned retrieval
  (**ARCHIVAL / opt-in**: only invoked when `[archival_ctp] enabled=true`; absent from default runs).

- The shared `analyze` iterates `(backbone, strategy_name)` pairs, loads each strategy's vectors
  via `cfg["load_vecs_fn"]`, computes retrieval metrics, and writes rows via `cfg["db_write_fn"]`
  (`db.write_analyze_metrics`).
- PTC strategy names are enumerated from `BIN_MODES`/`STD_THRESHOLDS`; CTP strategy names map each
  known head to its `CTP_SCORE_THRESHOLDS`. See `run.py`.
- PTC and CTP song lists are **independent** — each comes from its own cache scan and callers must
  join on `song_id` themselves; no code enforces alignment.
- No `flat_ref/` files are loaded or written by the binned path.

---

## Binned embed (segment phase — `strategy_ptc/segment_fn.py`, `strategy_ctp/segment_fn.py`)

There is **no** `strategy_binned/_embed.py` module. Binned pooling runs in the **segment phase**
(`run.py::_segment_phase`), dispatched through the shared `common.segment.segment(...)` loop.

**Live entry points (wired from `run.py::_segment_phase`):**

- **PTC** — `strategy_ptc/segment_fn.py::make_segment_fn(con)` builds the segmenting closure that
  decodes a `ptc_{bin_mode}_{std_thresh}` strategy name, derives the segmentation threshold from
  cached per-backbone calibration, calls `temporal_segment`, pools each segment via
  `strategy_binned._pool._pool_segment`, then `CACHE_WRITE_FN` (`_cache_write`) persists the pooled
  bins via `binned_ptc.save(backbone, bin_mode, std_thresh, song_id, bulk_vecs, bulk_heads=[])`.
- **CTP** — `strategy_ctp/segment_fn.py::make_segment_fn(head_sessions, run_in_batches_fn)` decodes
  a `ctp_{head}_{std_thresh}` strategy name, runs the ONNX head on the patches to get the score
  stream, segments by STD threshold, pools each segment, then `CACHE_WRITE_FN` persists via
  `binned_ctp.save(backbone, head, std_thresh, song_id, bulk_vecs)`.

Both adapters expose `SKIP_CHECK_FN` (filesystem-cache skip via `binned_ptc.list_done_keys()` /
`binned_ctp.list_done_keys()`) and `CACHE_WRITE_FN`. The shared loop
`common.segment.segment(con, segment_fn, strategy_names, ...)` applies them per in-scope song ×
backbone × strategy: it reads the raw sidecar `.npy` at `_patches_path(sid, backbone)`, skips songs
with a missing sidecar, and calls `skip_check_fn(sid, backbone, strategy_name)` to drop
already-cached strategies unless `force=True`.

**Segment flow (PTC), per `(bin_mode, std_thresh)` combo:**

1. Load sidecar: `np.load(patches_path(sid, backbone))` → `raw [n_patches, D]`.
2. Normalise: `unit_all = raw_all.normalize()`.
3. `temporal_segment(unit_all.data, threshold, dist_fn)` → segments.
4. For each segment: `_pool_segment(raw_all, unit_all, seg["indices"])` → all pool strategies.
5. `binned_ptc.save(backbone, bin_mode, std_thresh, sid, bulk_vecs)` writes one `.npz` per combo.

**Vectors: DB vs filesystem**

- **Vectors are stored to filesystem only.** The PTC / CTP cache `.npz` files are the canonical
  store for all bin-level vector data.
- The DB receives only **scalar data** (acoustic `patch_features` and calibration stats).
- This is the documented performance fix: the old `binned_vecs` DB table was removed;
  `cache/binned_ptc.py` module docstring states explicitly: *"The DB is no longer used for binned
  vec / head data; it only stores scalar analysis results and song metadata."*

---

## `_optimize.py`

### `OptimizationResult`

```python
@dataclass(frozen=True)
class OptimizationResult:
    threshold: float   # canonical threshold value (via canonical_threshold())
    score: float       # objective metric value at the optimal threshold
```

### `_build_grid(search_range: tuple[float, float], step: float = 0.05) -> list[float]`

- Returns sorted unique canonical thresholds from `lo` to `hi` (inclusive within floating-point tolerance) spaced by `step`.
- `lo` and `hi` are canonicalised via `canonical_threshold()`.
- Returns `[lo]` when `hi <= lo`.

### `_golden_section_max(f, a, b, *, tol, max_evals) -> tuple[float, float, int]`

- **Reads/writes:** nothing external.
- **Returns:** `(optimal_x, f(optimal_x), n_evals)`.
- Stops when interval width < `tol` or `n_evals >= max_evals`.
- **Precondition:** `f` is unimodal on `[a, b]`; the GSS is not valid for multimodal functions.

### `_eval_threshold(dist_thresh, *, backbone, bin_mode, song_data, objective, k, rep_type, agg_method, metric, head_scores_by_sid, head_names) -> tuple[float, dict, dict]`

**Signature:**

```python
def _eval_threshold(
    dist_thresh: float,
    *,
    backbone: str,
    bin_mode: str,
    song_data: list[tuple[str, str, str | None, str | None, np.ndarray]],
    objective: str,           # "disc_artist" | "disc_genre" | "disc_general"
    k: int,
    rep_type: str,            # pool strategy for the optimizer
    agg_method: str,          # weighted reduction for reading rows
    metric: str,              # "cosine" (only supported metric; l2 was removed)
    head_scores_by_sid: dict[str, np.ndarray] | None,
    head_names: list[str] | None,
) -> tuple[float, dict, dict[str, tuple[tuple[int, ...], ...]]]
```

- **`song_data` element type** (`_SongEntry`): `(sid: str, artist: str, album: str | None, genre: str | None, raw_f32: np.ndarray [n_patches, D])`.
- **Reads:** nothing external — all data is in-memory.
- **Writes:** nothing.
- **Returns:**
  - `float` — mean objective score across rows matching `agg_method`, or `0.0` on failure.
  - `dict` — diagnostics dict (bins stats, discriminability metrics, sim_checksum).
  - `dict[str, tuple[tuple[int,...], ...]]` — `sid -> layout` mapping where layout is `tuple` of `tuple[int, ...]` of patch indices per segment.
- **Early return** with all-zero metrics when `n < 4` valid songs remain after segmentation.
- **head_scores alignment:** `head_scores_aligned [n_valid_songs, n_heads]` is built by looking up each `eval_sid` in `head_scores_by_sid`; missing sids use a neutral `0.5` fill.
- **No cache reads or writes.** All segmentation and pooling is done purely in memory from `song_data`.

### `optimize_std_threshold(con, *, backbone, bin_mode, song_ids, k, objective, search_range, subsample_size, tolerance, max_evals, seed, method, grid, grid_step, flat_epsilon, rep_type, agg_method, metric, csv_stem_suffix) -> OptimizationResult`

**Signature:**

```python
def optimize_std_threshold(
    con,
    *,
    backbone: str,
    bin_mode: str,
    song_ids: frozenset[str] | set[str] | None = None,
    k: int = 10,
    objective: str = "disc_artist",
    search_range: tuple[float, float] = (0.1, 1.2),
    subsample_size: int = 200,
    tolerance: float = 0.05,
    max_evals: int = 15,
    seed: int = 42,
    method: str = "grid",         # "grid" (default) | "gss"
    grid: list[float] | None = None,  # explicit grid; overrides build_grid when provided
    grid_step: float = 0.05,
    flat_epsilon: float = 1e-8,
    rep_type: str = "median",
    agg_method: str = "target_weighted",
    metric: str = "cosine",
    csv_stem_suffix: str = "",
) -> OptimizationResult
```

- **Reads:**
  - DB: `_db.load_all_songs(con)` → all songs. `_db.load_song_head_scores(con, backbone, sample_sids, strategy="median", pathway="ptc")` → optional head scores for the subsample.
  - Filesystem: sidecar `.npy` files at `_patches_path(sid, backbone)` for each sampled song.
- **Writes:**
  - Filesystem: `{OUTPUT_ROOT}/optimizer/threshold_curve_{backbone}_{bin_mode}{csv_stem_suffix}.csv` — per-threshold diagnostics table.
- **Returns:** `OptimizationResult(threshold, score)` — best threshold found and its objective value.

#### Objective

- Maximises `objective` (default `"disc_artist"`) — a discriminability metric (e.g. fraction of top-k neighbours from same artist).
- Valid values: `"disc_artist"`, `"disc_genre"`, `"disc_general"`, `"disc_head"`.

#### Search method

- **`method="grid"` (default):** evaluates `_eval_threshold` for every threshold in `thresholds` (built via `_build_grid(search_range, step=grid_step)` when `grid` is not supplied). Returns the threshold with the highest score. Does **not** assume unimodality.
- **`method="gss"` (legacy opt-in):** uses `_golden_section_max` on `[search_range[0], search_range[1]]`. Valid only for unimodal objectives; does not write a CSV.
- When neither method produces thresholds (empty `thresholds` list and method not "gss"), falls through to `_build_grid`.

#### Inconclusive result

- When `max(scores) - min(scores) < flat_epsilon` → logs a warning and returns the midpoint of `search_range` with the max seen score. This indicates the objective is insensitive to threshold changes over the sweep.

#### Head scores in optimizer

- `_db.load_song_head_scores(con, backbone, sample_sids, strategy="median", pathway="ptc")` is called once after subsampling.
- If unavailable, `head_scores_by_sid = None` and `head_names = None`; `_eval_threshold` uses `None` for both, meaning `disc_head` will be `0.0`.

#### Early return when too few valid songs

- When `n_valid < 10`: returns `OptimizationResult(threshold=canonical_threshold(midpoint), score=0.0)` without evaluating any thresholds.

---

## Cross-cutting invariants

### Vectors: DB vs filesystem (summary)

| Data type | Storage |
| --- | --- |
| Bin-level vectors (`pool_*_raw`, `pool_*_norm`) | **Filesystem only** — `cache/binned_ptc/**/*.npz` |
| Bin-level head activations (`head_*`) | **Filesystem only** — same `.npz` |
| CTP bin-level vectors | **Filesystem only** — `cache/binned_ctp/**/*.npz` |
| Pairwise sim matrices (`sim_*`) | **In-memory only** — never cached to disk (disk sim cache removed in Plan C) |
| Scalar analysis results (`analyze_metrics`, `song_retrieval_metrics`) | **DB only** |
| Song stats (`binned_song_stats`) | **DB only** |
| Head agreement (`head_agreement_rows`) | **DB only** |
| Calibration stats | **DB only** |
| Patch-level acoustic features (`patch_features`) | **DB only** |
| Head sim correlations (`head_sim_corr_rows`) | **DB only** |

### Song ID alignment rules

- Within the shared binned analyze path: `sids`, `artists`, `albums`, `genres`, and per-head score arrays loaded by `cfg["load_vecs_fn"]` are co-indexed on the same `sids` order.
- PTC and CTP song lists for the same `(backbone, bin_mode, std_thresh)` are **aligned via the matching corpus manifest** (`corpus.py`): each loader restricts its discovery to `manifest.song_ids`, so all binned and flat configurations for a backbone compare the exact same deterministic song set. A loader that returns a different set or order than the manifest is rejected (`validate_matching_corpus`) and the config is skipped with a recorded reason — never silently intersected or reordered.
- No `flat_ref/` directory participates in binned analysis; there is no separate Spearman reference song set.

### `cache_semantics_tag()` and cache invalidation

- `CACHE_BASE` in `cache/binned_ptc.py` and `cache/binned_ctp.py` embeds `cache_semantics_tag()` at module import time.  The similarity-matrix cache (`cache/sim.py`, `SIM_CACHE_BASE`) was removed in Plan C.
- Changing the tag invalidates all caches by using a different root directory; old directories are orphaned, not deleted.
- Independent from the semantics tag, `versioned_cache_root` (see `cache_identity.py`) keys the representation-pair matrix caches on a scoring-semantics version and the matching-corpus hash, so a stale corpus or a changed scoring version is served from a different (orphaned) root rather than reused.

### `agg_method=medoid` prohibition

- `medoid` is blocked at three levels: `_constants.py` at import time (for `AGG_METHODS`), `optimize_std_threshold` (explicit ValueError), and `compute_agg_mats` inner loop (explicit ValueError). `rep_type=medoid` is allowed and uses the observed patch row rather than a synthetic aggregate.

---

## 6. Report Sections (report/)

## Table of Contents

1. [_base.py — shared primitives](#_basepy--shared-primitives)
2. [_corpus.py](#_corpuspy)
3. [_efficiency.py](#_efficiencypy)
4. [_optimizer.py](#_optimizerpy)
5. [_retrieval.py](#_retrievalpy)
6. [_binned.py](#_binnedpy)
7. [_heads.py](#_headspy)
8. [_summary.py](#_summarypy)
9. [_winners.py](#_winnerspy)
10. [_winners_report.py](#_winners_reportpy)
11. [_truncation.py](#_truncationpy)
12. [V2 Section Dict Shape Reference](#v2-section-dict-shape-reference)

---

## _base.py — shared primitives

### Constants

The `_base.py` module does **not** define `FLAT_COLUMNS` / `BINNED_COLUMNS` module-level
constants.  The flat and binned column sets are **local lists** (`flat_columns` /
`binned_columns`) inside `section_unified_table` in `report/_retrieval.py` (see lines
~96–203).  They are the row sets the unified-ranking table is reindexed to:

- `flat_columns` — 49 items: flat identity (`backbone`, `strategy`, `sim_metric`, `k`),
  the core retrieval metrics + means/variances/kurtoses per label axis, and
  `map_k_general`.
- `binned_columns` — 55 items: binned identity (`backbone`, `bin_mode`, `std_thresh`,
  `rep_a`, `rep_b`, `sim_metric`, `agg_method`, `k`), the same metric columns, plus
  `flat_binned_spearman` and `flat_binned_beneficial_reorder_rate`.

#### Plot theme constants

| Constant | Value | Purpose |
| --- | --- | --- |
| `_PLOT_BG` | `"#12131e"` | Plotly plot area background |
| `_PAPER_BG` | `"#1a1b26"` | Plotly paper background |
| `_GRID_COLOR` | `"#555"` | Grid line colour |
| `_FONT_COLOR` | `"#e0e0e8"` | Font/annotation colour |
| `_H_SMALL` | `320` | Minimum height for small charts (px) |
| `_H_MED` | `420` | Medium chart height (px) |
| `_H_LARGE` | `560` | Large chart height (px) |

---

### Helper functions

#### `apply_dark_theme(fig, *, grid=True) -> None`

Applies dark styling to a Plotly `go.Figure` in-place. Sets `plot_bgcolor`,
`paper_bgcolor`, font colour, grid/axis styles, and margins. No return value.

#### `figure_dict(fig) -> dict`

Converts a Plotly figure to a JSON-serialisable dict by calling `fig.to_json()`
then `json.loads`. Ensures all numpy types are converted to plain Python scalars.

#### `make_chart(fig, *, id='', title='') -> dict`

Builds a chart descriptor:

```python
{"id": str, "title": str, "type": "plotly", "figure": dict}
```

`figure` is the output of `figure_dict(fig)`.

#### `empty_df(columns: list[str]) -> pd.DataFrame`

Returns an empty `pd.DataFrame` with the given column names and no rows.

#### `fmt(v) -> str`

Formats a single value for table display:

- `None` → `"—"`
- `float` that is `NaN` → `"—"`
- `float` with a real value → `f"{v:.4f}"`
- anything else → `str(v)`

#### `rep_label(rep: str | None) -> str`

Returns a human-readable pooling label:

- `None` → `"—"`
- `"median"` → `"coord-median"`
- `"medoid"` → `"medoid"`
- anything else → unchanged string

#### `agg_label(agg: str | None) -> str`

Returns a human-readable aggregation label:

- `None` → `"—"`
- `"median"` → `"median"`
- `"medoid"` → `"medoid"`
- `"target_weighted"` → `"target-wtd"`
- `"bidirectional_weighted"` → `"bidir-wtd"`
- `"normalized_mean_pair_weighted"` → `"norm-pair-wtd"`
- anything else → unchanged string

#### `binned_config_label(*, bin_mode, std_thresh, rep_a, rep_b, agg_method) -> str`

Builds the stable config label used throughout the report:

```
{bin_mode}/{std_thresh:g}/{rep_label(rep_a)}x{rep_label(rep_b)}/{agg_label(agg_method)}
```

`std_thresh` is formatted with `g` if `notna`, otherwise `"—"`.

#### `table_exists(con, name: str) -> bool`

Queries `information_schema.tables` in DuckDB. Returns `True` if the table
exists, `False` on any error or miss.

#### `_pareto_front_indices(x: list[float], y: list[float]) -> set[int]`

Private. Returns the set of indices not dominated on both axes (higher = better
on both). Used internally by `section_unified_table` and `section_per_backbone`.

#### `make_table(rows, *, id='', title='', collapsible=False, summary_text='', open=False) -> dict`

Builds a table descriptor:

```python
# Non-empty:
{
    "id": str,
    "title": str,
    "columns": list[str],   # keys of rows[0]
    "rows": list[list[str]], # fmt()-formatted values
    "collapsible": bool,
    "summary_text": str,
    "open": bool,
    "empty": False,
}

# Empty (rows == []):
{
    "id": str,
    "title": str,
    "columns": [],
    "rows": [],
    "collapsible": bool,
    "summary_text": str,
    "open": bool,
    "empty": True,
}
```

All values in `rows` are passed through `fmt()`.

#### `make_panel(id, title, *, open=False, charts=None, tables=None, text='', subsections=None) -> dict`

Builds a collapsible panel descriptor:

```python
{
    "id": str,
    "title": str,
    "open": bool,
    "charts": list[dict],      # defaults to []
    "tables": list[dict],      # defaults to []
    "text": str,
    "subsections": list[dict], # defaults to []
}
```

#### `make_section(id, title, *, ...) -> dict`

Builds a v2 section descriptor. This is the canonical return type for every
`section_*` function. See the [V2 Section Dict Shape Reference](#v2-section-dict-shape-reference)
for the full schema.

---

## _corpus.py

### `disc_score_warning(con) -> list[dict]`

**Signature:** `(con) -> list[dict]`

**DB reads:**

| Table | Columns accessed | Query |
| --- | --- | --- |
| `songs` | `artist`, `COUNT(*)` | `COUNT(DISTINCT artist)`, `COUNT(*)`, artist group counts |

**Return value:** A list of warning dicts. Each dict has:

```python
{
    "id": str,      # "single_artist" | "no_within_artist_pairs"
    "level": str,   # "error" | "warning"
    "message": str,
    "detail": str,
}
```

**Empty/stub behaviour:**

- Returns `[]` if `songs` table is missing or any query raises an exception.
- Returns `[]` if corpus has ≥2 artists and at least one artist has ≥2 songs.
- Returns a single `"error"` dict if `n_artists < 2`.
- Returns a single `"warning"` dict if every artist has exactly 1 song.

---

### `section_corpus(con) -> dict`

**Signature:** `(con) -> dict`

**DB reads:**

| Table | Columns accessed |
| --- | --- |
| `songs` | `COUNT(*)`, `COUNT(DISTINCT artist)`, `COUNT(DISTINCT album)`, `artist`, `n` (alias) |

**Return value:** v2 section dict with `id="corpus"`, `title="Corpus Overview"`.

**Populated fields when data is present:**

- `stats`: `[{label, value}]` — `songs`, `artists`, `albums`, `avg songs/artist`, `artists with ≥2 songs`
- `charts`: one horizontal bar chart (`id="artist_distribution"`) showing top-40 artists, green if ≥2 songs, red if 1
- `tables`: one collapsible table (`id="per_artist"`) with columns `artist`, `songs`, all artists
- `description`: trust-signal explanation
- `warnings`, `panels`, `subsections`, `headline`, `stats` extras: all `[]` / `None` / `""`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| `songs` table missing | `"No songs table found."` |
| `songs` table exists but `COUNT(*) == 0` | `"No songs in the database yet. Run the embed phase."` |
| Subsequent query error | `"Could not load corpus data."` |

---

## _efficiency.py

### `section_efficiency(con) -> dict`

**Signature:** `(con) -> dict`

**DB reads:**

| Table | Columns accessed |
| --- | --- |
| `phase_timings` | `run_ts`, `phase`, `elapsed_s` |

**Return value:** v2 section dict with `id="efficiency"`, `title="Pipeline Efficiency"`.

**Populated fields when data is present:**

- `charts`: one horizontal bar chart (`id="phase_timing"`) for the latest run's phases
- `tables`: one collapsible pivot table (`id="timing_history"`, `title="History (all runs)"`) if more than one `run_ts` exists; otherwise `[]`
- `description`: latest run timestamp, total seconds/minutes, phase count
- Query orders by `run_ts, phase`; latest run is `df["run_ts"].max()`
- `stats`, `panels`, `subsections`, `warnings`, `headline`: all `[]` / `None`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| `phase_timings` table missing | `"No timing data yet. Run the pipeline to populate this section."` |
| Query exception | `"Could not load timing data."` |
| Table exists but is empty | `"No timing data yet."` |

---

## _optimizer.py

### `load_optimizer_curves() -> list[dict]`

**Signature:** `() -> list[dict]`

**Filesystem reads:** Globs `outputs/optimizer/*.csv` (relative to
`scripts/embedding_research/outputs/`).

**CSV columns expected (any may be absent, handled gracefully):**

| Column | Required | Notes |
| --- | --- | --- |
| `objective_total` | Yes (or `objective`) | Primary sort key; descending |
| `objective` | Fallback | Used if `objective_total` absent |
| `threshold_key` | No | Row key; falls back to `threshold` |
| `threshold` | Fallback | Used if `threshold_key` absent |
| `disc_general` | No | Included in top-3 table |
| `disc_artist` | No | Included in top-3 table |
| `disc_genre` | No | Included in top-3 table |
| `disc_head` | No | Included in top-3 table |
| `map_k` | No | Included in top-3 table |
| `mrr` | No | Included in top-3 table |
| `ndcg_k` | No | Included in top-3 table |
| `recall_k` | No | Included in top-3 table |
| `layout_changed_count_vs_prev` | No | Displayed as `layoutΔ` |
| `median_bins_per_song` | No | In summary row |

**Filename convention:** `{backbone}__{bin_mode}.csv` — split on first `__`.
If no `__` present, `bin_mode` is set to `"unknown"`.

**Return value:** A list of dicts:

```python
{
    "backbone": str,
    "bin_mode": str,
    "data": pd.DataFrame,  # full curve, sorted by objective_total desc
    "best": dict,          # row dict with highest objective_total
    "source": pathlib.Path,
}
```

**Empty/stub behaviour:** Returns `[]` if `outputs/optimizer/` directory is
missing, or all CSVs are empty or lack an objective column.

---

### `section_optimizer() -> dict`

**Signature:** `() -> dict`

**Reads:** Calls `load_optimizer_curves()` (filesystem only — no DB).

**Return value:** v2 section dict with `id="optimizer"`, `title="Optimizer Results"`.

**Populated fields when data is present:**

- `tables`: one table (`id="optimizer_summary"`) with columns:
  `backbone`, `bin_mode`, `best threshold`, `best objective`, `median bins`,
  `disc_general`, `map_k`, `n evals`, `source`
- `panels`: one `make_panel` per backbone/bin_mode combination, each containing
  a top-3 candidate table with columns:
  `threshold`, `objective`, `disc_general`, `disc_artist`, `disc_genre`,
  `disc_head`, `map_k`, `mrr`, `ndcg_k`, `recall_k`, `layoutΔ`
- `description`, `stats`, `charts`, `subsections`, `warnings`, `headline`: all `[]` / `None`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| `outputs/optimizer/` directory missing | `"No optimizer artifacts found. Run the optimize phase first."` |
| Directory exists, no CSVs loadable | `"No threshold-curve CSVs found. Run the optimize phase first."` |
| CSVs parsed but no summary rows produced | `"Optimizer artifacts found, but no readable threshold-curve data was parsed."` |

---

## _retrieval.py

### `query_analyze_metrics(con) -> pd.DataFrame`

**Signature:** `(con) -> pd.DataFrame`

**DB reads:**

| Table | Columns selected | Order |
| --- | --- | --- |
| `analyze_metrics` | `strategy_key`, `strategy_type`, `sim_metric`, `k`, plus one pivoted column per metric value | `disc_general DESC NULLS LAST` |

Pivots `analyze_metrics` via `PIVOT ... ON metric USING FIRST(value) GROUP BY strategy_key, strategy_type, sim_metric, k`, filters rows to `STRATEGY_TYPES = ["global_pool", "ptc", "ctp"]`, then decodes each `strategy_key` into derived `backbone` / `strategy` / `head` / `bin_mode` / `std_thresh` / `rep_a` / `rep_b` / `agg_method` columns via `_decode_strategy_key`. This decoded frame is the single input consumed by all retrieval report sections.

**Return value:** `pd.DataFrame` with `ANALYZE_METRICS_COLUMNS` plus the derived configuration columns.

**Empty/stub behaviour:** Returns `empty_df(ANALYZE_METRICS_COLUMNS)` if:

- the `analyze_metrics` table does not exist, or
- the SELECT/PIVOT query raises any exception.

---

### `section_unified_table(df) -> dict`

**Signature:** `(df: pd.DataFrame) -> dict`

**DataFrame input:** the decoded `analyze_metrics` frame from `query_analyze_metrics`. The function derives `flat_df = df[strategy_type == "global_pool"]` and `binned_df = df[strategy_type in (ptc, ctp)]` internally.

**Processing:**

1. Flat rows get synthetic columns: `type="flat"`, `pathway="flat"`, `config=<flat strategy>`.
2. Binned rows get `type="binned"`, `pathway=ptc|ctp`, and `config=binned_identity_label(...)` (full pathway/head/bin/rep/agg identity, never collapsed).
3. Combined, sorted by `map_k_general DESC, map_k_artist DESC` (`na_position="last"`); top 20 rows emitted as table.
4. A per-backbone bar chart (`id="unified_disc_bar"`) compares the **flat medoid baseline** (`flat_medoid_value`) against the best binned `disc_genre` per backbone — never a max across flat strategies.
5. A `pooling_variants` panel lists, per `(rep_a, rep_b, agg_method)` triple, the exact best binned config (full identity) and its `disc_genre`.

**Return value:** v2 section dict with `id="unified-ranking"`, `title="Unified Ranking"`.

**Populated fields when data is present:**

- `charts`: one bar chart of flat medoid baseline vs best binned `disc_genre` per backbone
- `tables`: one collapsible top-20 table (`id="top20"`) with columns:
  `type`, `backbone`, `pathway`, `config`, `k`, `map_k_general`, `map_k_artist`,
  `map_k_genre`, `map_k_head`, `disc_general`, `disc_artist`, `disc_genre`,
  `disc_head`, `disc_score`, `map_k`, `mrr`, `ndcg_k`, `recall_k`,
  `recall_k_genre`, `flat_binned_spearman`, `flat_binned_beneficial_reorder_rate`
- `panels`: one `pooling_variants` panel (may be `[]`)
- `subsections`, `stats`, `warnings`, `headline`: all `[]` / `None`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| Both `flat_df` and `binned_df` empty | `"No retrieval results yet. Run the eval phase first."` |
| No parts after concat | `"No results could be ranked."` |

---

### `section_per_backbone(df) -> dict`

**Signature:** `(df: pd.DataFrame) -> dict`

**DataFrame input:** the decoded `analyze_metrics` frame. Flat/binned subsets derived internally as in `section_unified_table`.

**Disc column selection (applied independently to flat and binned):**
Uses `disc_general` if that column exists and has at least one non-null value;
otherwise falls back to `disc_score`.

**Per-backbone content built:**

- **Scatter chart** (`disc` vs `map_k`): flat points + top-`_TOP_N` (15) binned
  points, Pareto-optimal points marked as stars.
- **Delta bar chart** (binned Δ vs flat baseline): each binned config's best
  `disc_col` minus the **explicit flat medoid baseline** (`flat_medoid_value`, i.e.
  `global_pool:{backbone}:medoid`), top-15 configs, green/red coloured. A config
  is never compared against a max/median/mean across flat strategies.
- **Top-N table** (`id=f"top_configs_{backbone}"`): top-5 flat rows + top-15
  binned rows, columns `type`, `backbone`, `config`, plus metric columns
  (`disc_col`, `map_k_general`, `map_k_artist`, `map_k`, `mrr`, `ndcg_k`, `recall_k`).

**Return value:** v2 section dict with `id="per-backbone"`,
`title="Per-Backbone Analysis"`, `subsections` list where each entry is an
inline v2 dict (all 11 keys present) with `id=f"backbone-{backbone}"`.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| No backbone names produced | `"No backbone data yet."` |

---

## _binned.py

### `section_threshold_sweep(df) -> dict`

**Signature:** `(df: pd.DataFrame) -> dict`

**DataFrame input:** the decoded `analyze_metrics` frame. Binned rows
(`strategy_type in (ptc, ctp)`) and flat rows (`strategy_type == "global_pool"`)
are split internally; flat rows supply the medoid baseline only.

**Processing:**

- Optionally filters binned rows to `DIST_THRESHOLDS` from
  `scripts.embedding_research.helpers.binning` (silently skipped on `ImportError`).
- Groups binned rows by the full 6-dim combinatorial
  `(bin_mode, std_thresh, rep_a, rep_b, agg_method, head)` and computes, per group,
  the mean / variance / stddev / kurtosis (`min 4 points`) of `disc` plus a row count
  (`n`); when `map_k_general` is present also the mean/variance of that column.  Thresholds
  are never collapsed into a max.
- One trace per `(bin_mode, rep_a, rep_b, agg_method, head)` with y-axis =
  **mean disc** (mean MAP@k when available), x-axis = `std_thresh`, ±1 std error bars.
- Adds an amber dashed horizontal line at the **flat medoid baseline**
  (`flat_medoid_value`) per backbone — never `max(flat_disc)` across strategies.
- MAP@k general primary chart id is `f"sweep_map_{backbone}"` (one per backbone);
  disc mean/variance/kurtosis charts use ids `sweep_mean_{backbone}` /
  `sweep_var_{backbone}` / `sweep_kurt_{backbone}`.

**Return value:** v2 section dict with `id="threshold-sweep"`,
`title="Threshold Sweep"`. Each backbone becomes an inline v2 subsection dict
(all 11 keys present) with `id=f"sweep-{backbone}"`.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| No binned rows | `"No binned results yet."` |

---

### `section_bin_diversity(con) -> dict`

**Signature:** `(con) -> dict`

**DB reads:**

| Table | Columns read | When |
| --- | --- | --- |
| `binned_song_stats` | `backbone`, `bin_mode`, `std_thresh`, `n_bins` | If table exists (PTC stream) |
| `binned_classify_ctp` | `backbone`, `head`, `bin_mode`, `std_thresh`, `song_id`, `bin_id` | If table exists (CTP stream) |

**Aggregation queries produce:**

- From `binned_song_stats`: `mean_bins`, `median_bins`, `min_bins`, `max_bins` grouped by `backbone, bin_mode, std_thresh`
- From `binned_classify_ctp`: same aggregates grouped by `backbone, head, bin_mode, std_thresh` (using `MAX(bin_id)+1` as `n_bins` per song)

**Optional dependency:** `scripts.embedding_research.helpers.binning.DIST_THRESHOLDS` —
used to add a `WHERE std_thresh IN (...)` filter. Silently ignored on `ImportError`.

**Return value:** v2 section dict with `id="bin-diversity"`,
`title="Bin Diversity"`, per-backbone subsections.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| Neither `binned_song_stats` nor `binned_classify_ctp` exist | `"No segment data available yet. Run the classify phase."` |
| Both tables exist but all queries return empty | `"No segment data available yet."` |

---

### `section_segment_counts(con) -> dict`

**Signature:** `(con) -> dict`

**DB reads:** Identical to `section_bin_diversity` — queries `binned_song_stats`
and `binned_classify_ctp` with the same column set and aggregation queries.

**Return value:** v2 section dict with `id="segment-counts"`,
`title="Segment Counts per Threshold"`, per-backbone subsections.

**Content difference vs `section_bin_diversity`:** Renders line charts of
`mean_bins` vs `std_thresh` for PTC (by `bin_mode`) and CTP (by `head`)
plotted together, rather than grouped bar charts.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| Neither table exists | `"No segment data available yet."` |
| Both tables return empty data | `"No segment data available."` |

---

### `section_bin_mode_comparison(df) -> dict`

**Signature:** `(df: pd.DataFrame) -> dict`

**DataFrame input:** the decoded `analyze_metrics` frame; binned/flat subsets
split internally as in `section_threshold_sweep`.

**Processing:**

- Optionally filters binned rows to `DIST_THRESHOLDS` (same as `section_threshold_sweep`).
- Requires `len(bin_mode.unique()) >= 2`; returns early if only one mode found.
- Per backbone: re-aggregates by `(bin_mode, std_thresh)` taking the **mean** of
  `map_k_general` (or the disc column when `map_k_general` is absent) across all
  `(rep_a, rep_b, agg_method, sim_metric, k)` variants at each threshold — no
  max-collapsing.
- Compares `temporal_global` vs `temporal_perdim` counts over the common thresholds
  shared by both modes.
- Adds an amber dashed horizontal line at the **flat medoid baseline**
  (`flat_medoid_value`) — never `max(flat_disc)` across strategies.
- Verdict: `"temporal_global wins for this backbone."` / `"temporal_perdim wins for this backbone."`
  / `"Both modes perform equivalently for this backbone."`.

**Return value:** v2 section dict with `id="bin-mode-comparison"`,
`title="Bin Mode Comparison: global vs perdim"`, per-backbone subsections.
Each subsection is an inline v2 dict (all 11 keys) with `id=f"bmc-{backbone}"`.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| No binned rows | `"No binned results yet."` |
| `< 2` distinct bin modes | `"Only one bin mode found — need both temporal_global and temporal_perdim."` |

---

### `section_flat_binned_correlation(df) -> dict`

**Signature:** `(df: pd.DataFrame) -> dict`

**DataFrame input:** the decoded `analyze_metrics` frame.

**Processing:**

- Reads the decoded `flat_binned_spearman` and `flat_binned_beneficial_reorder_rate`
  columns (present on binned rows from the shared analyze phase).
- Groups by `(strategy_type, bin_mode, head, std_thresh, rep_a, rep_b, agg_method)`.
- Per backbone renders a Spearman rho chart plus a raw-stats panel
  (`flat_binned_spearman`, `flat_binned_beneficial_reorder_rate`).

**Return value:** v2 section dict with `id="flat-binned-corr"`,
`title="Flat-Binned Rank Correlation"`, per-backbone subsections with `id=f"fbcorr-{backbone}"`.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| No binned rows at all | `"No binned results yet."` (early return at `report/_binned.py` `section_flat_binned_correlation`) |
| Neither `flat_binned_spearman` nor `flat_binned_beneficial_reorder_rate` has a non-null value | `"No flat-binned correlation data available."` |

---

## _heads.py

### `section_head_sim_corr(con) -> dict`

**Signature:** `(con) -> dict`

**DB reads:**

| Table | Columns read | Order |
| --- | --- | --- |
| `head_sim_corr_rows` | `backbone`, `head`, `bin_mode`, `std_thresh`, `rep_a`, `rep_b`, `agg_method`, `spearman_r` (rounded 4dp) | `backbone, head, bin_mode, std_thresh` |

`strategy` is derived from the row columns via `binned_config_label` after the query — it is
not a table column.

**Processing:**

- Pivots per backbone: `index=head`, `columns=strategy`, `values=spearman_r` (mean aggfunc).
- Renders a heatmap per backbone (RdYlGn diverging at 0).
- Builds a best-strategy-per-head table from the raw rows.

**Return value:** v2 section dict with `id="head-sim-corr"`,
`title="Head × Embedding Similarity Correlation"`, per-backbone subsections.
Each subsection is an inline v2 dict (all 11 keys) with `id=f"corr-{backbone}"` and:

- `charts`: one heatmap chart
- `tables`: one collapsible best-strategy table

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| `head_sim_corr_rows` table missing | `"Run the classify and analyze phases to populate this section."` |
| Query exception | `f"Query error: {exc}"` |
| Table exists but empty | `"No correlation data yet."` |

---

### `section_head_value(con, flat_df=None) -> dict`

**Signature:** `(con, flat_df: pd.DataFrame | None = None) -> dict` — `flat_df` is accepted for a
backward-compatible call signature only and is **not used** (the archival CTP note no longer reads it).

**Status: ARCHIVAL / DEFERRED.** CTP (classify-then-pool) is a deferred, archival pathway that is
excluded from the primary EffNet PTC-versus-global-medoid experiment. This section is retained purely
as a labelled archival note and raw reference table; it is **never** a primary winner/delta source.
Exact primary winners/deltas live in the *Exact Winners & Deltas* section; shared-boundary head-output
preparation lives in the `head-output-shared-ptc-boundary` section.

**DB reads:**

| Table | Columns read | Required |
| --- | --- | --- |
| `ptc_ctp_rows` | `backbone`, `head`, `strategy`, `ptc_disc` (4dp), `ctp_disc` (4dp), `delta_disc` (4dp) | Yes |

**Processing:**

- Emits an `archival_warning` in every populated and empty case.
- Renders the **raw** `ptc_ctp_rows` comparison rows (`Δdisc = ctp_disc - ptc_disc`) as a single
  reference table only — no winner/delta aggregation, no heatmaps, no medoid baseline, no `flat_df` use.

**Return value:** v2 section dict with `id="head-value"`, `title="Head Value (Archival CTP Reference)"`.

**Populated fields:**

- `tables`: `[head_value_archival_ctp]` (raw archival CTP reference rows)
- `warnings`: `[archival_warning]`
- `description`, `stats`, `charts`, `panels`, `subsections`, `headline`: `[]` / `None`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| `ptc_ctp_rows` table missing | `"No archival CTP comparison rows (ptc_ctp_rows) present. CTP is deferred/archival and excluded from primary analysis."` |
| Query exception | `f"Query error: {exc}"` |
| Table exists but empty | `"No archival CTP comparison data."` |

---

### `section_head_output_shared_ptc_boundary(con, manifest=None) -> dict`

**Signature:** `(con, manifest: HeadPhaseManifest | None = None) -> dict`

Shared-boundary head-output preparation status and coverage. Reports whether the shared `effnet_ptc`
boundary head phase has been prepared for each `(head, bin_mode, threshold)` configuration, the
persisted shared-boundary provenance (`boundary_source="effnet_ptc"`, `head_pool_variant=...`),
per-threshold song coverage (`n_songs` / `n_pooled`), and any missing-data warnings. Preparation-status
section only — never emits primary winner/delta rows.

**DB reads:**

| Table | Columns read | Required |
| --- | --- | --- |
| `head_phase_provenance` | all columns, ordered `backbone, head, bin_mode, threshold, boundary_source, head_pool_variant` | Yes |

Read via `db.head_phase.load_head_phase_provenance(con)`.

**Warnings (from `manifest`, when supplied):**

| Condition | Warning |
| --- | --- |
| `manifest.errors` | `"Head phase finished with {n} error configuration(s); shared-boundary head outputs are incomplete."` |
| `manifest.done == 0` | `"Head phase produced no pooled output (skipped=… errors=…); shared-boundary head outputs are unavailable in this report."` |
| no provenance rows and `manifest is None` | `"No shared-boundary head-phase provenance found. Run the head phase (classify.run_shared_ptc_head_pooling) to populate head-output provenance."` |

**Return value:** v2 section dict with `id="head-output-shared-ptc-boundary"`,
`title="Head Output: Shared PTC Boundary"`.

**Populated fields:**

- `tables`: `[head_phase_provenance]` — per-`(head, bin_mode, threshold)` row with `status`,
  `n_songs`, `n_pooled`, `coverage` (`100.0 * n_pooled / n_songs`%, blank when `n_songs == 0`),
  `boundary_source`, `head_pool_variant`, `reference_corpus_hash` (`"—"` when `NULL`)
- `warnings`: provenance + manifest warnings
- `description`, `stats`, `charts`, `panels`, `subsections`, `headline`: `[]` / `None`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| no provenance rows (table missing or empty) | `"No shared-boundary head-phase data yet. Run the head phase to populate provenance."` |

---

## _summary.py

### `section_summary(df) -> dict`

**Signature:** `(df: pd.DataFrame) -> dict`

**DataFrame input:** the decoded `analyze_metrics` frame; flat/binned subsets
split internally (`strategy_type == "global_pool"` vs `ptc`/`ctp`).

**Processing (per backbone):**

1. `flat_medoid_disc_genre` — the explicit flat **medoid** baseline on `disc_genre`
   (`flat_medoid_value`, i.e. `global_pool:{backbone}:medoid`). Never a max/median/mean
   across flat strategies.
2. `best_binned_config` — `binned_identity_label(...)` of the binned row with the
   highest `disc_genre`.
3. `best_binned_disc_genre` — that winning row's `disc_genre`.
4. `delta_vs_medoid` — `best_binned_disc_genre - flat_medoid_disc_genre`.

**Return value:** v2 section dict with `id="summary"`, `title="Summary"`.

**Populated fields:**

- `tables`: one table (`id="backbone_summary"`) with per-row columns:
  `backbone`, `flat_medoid_disc_genre`, `best_binned_config`,
  `best_binned_disc_genre`, `delta_vs_medoid`
- `headline`: `{color, icon, text}` summarising whether binned beats the medoid
  baseline on `disc_genre`:
  - green `✓` when every backbone's best binned beats its medoid baseline
  - amber `⚠` when some backbones beat their baseline and some do not
  - red `✕` when none beat their baseline
- `description`, `stats`, `charts`, `panels`, `subsections`, `warnings`: `[]` / `None`
- `empty_message`: `""`

> **No `_dominance_rate` helper and no composite-tuning-sensitivity metric.** Those
> were removed in Plan D. The summary compares binned configurations only against the
> explicit flat medoid baseline.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| No backbone names produced | `"No retrieval data yet. Run the eval phase first."` |

---

## _winners.py

> **Report-data DTOs.** `_winners.py` defines the winner/delta/factor schemas and the
> pure builders that turn the decoded `analyze_metrics` frame into winner rows,
> per-config deltas vs the explicit medoid baseline, and factor summaries. It defines
> no section dicts itself — `_winners_report.py` wraps the builders in report sections.

### Schema constants

`WINNER_DELTA_COLUMNS` — **33 columns**, one row per
`(backbone, group, metric, k, winner, baseline)`. The 33 columns are the decoded
winner identity, the ten bounded per-pair `TRACE_SUMMARY_COLUMNS`
("trace_*"), and the baseline/delta/corpus fields:

`backbone`, `group`, `metric`, `k`, `winner_strategy_key`, `winner_strategy_type`,
`winner_value`, `winner_flat_strategy`, `winner_pathway`, `winner_head`,
`winner_bin_mode`, `winner_threshold`, `winner_rep_a`, `winner_rep_b`,
`winner_aggregate`, `winner_ambiguity_variant`, `winner_sim_metric`,
(`trace_n_pairs`, `trace_numerator_sum`, `trace_denominator_sum`,
`trace_numerator_mean`, `trace_denominator_mean`, `trace_collision_count`,
`trace_winner_count`, `trace_retained_contributions`, `trace_dropped_contributions`,
`trace_finite`), `baseline_strategy_key`, `baseline_value`, `delta`, `tie_break_key`,
`corpus_hash`, `corpus_size`.

`FACTOR_SUMMARY_COLUMNS` — **10 columns**, one row per
`(backbone, factor, factor_value, group, metric, k)`:

`backbone`, `factor`, `factor_value`, `group`, `metric`, `k`, `n_wins`,
`mean_delta`, `best_delta`, `config_ids`.

### Configuration constants

- `GROUPS = ("artist", "genre", "head", "general")` — `general` included only when
  legitimately populated (`_general_cell_valid`).
- `METRIC_FAMILIES = ("MAP", "MRR", "NDCG", "Recall", "discrimination")`
- `GROUP_METRIC_COLUMNS` — maps each group → `{family: analyze_metrics column}`,
  e.g. artist MAP→`map_k_artist`, artist MRR→`mrr`, genre MRR→`mrr_genre`,
  head discrimination→`disc_head`, general MAP→`map_k_general` and general
  discrimination→`disc_general`. `general` has only the MAP and discrimination families.
- `TIE_BREAK_ORDER = ("strategy_type", "pathway/head", "bin_mode", "threshold", "rep_a", "rep_b", "aggregate", "strategy_key")` — the winner among value-tied rows is the one sorting earliest by this key (smallest tuple).
- `STRATEGY_TYPE_RANK = {"global_pool": 0, "ptc": 1, "ctp": 2}`
- `FACTOR_COLUMNS` — maps each factor name to its winner-row column (strategy_type, flat_strategy, pathway, head, bin_mode, threshold, rep_a, rep_b, score_variant→`winner_aggregate`, ambiguity_variant→`winner_ambiguity_variant`, sim_metric).

### Builders

`build_comparison_grid(rows, k_values=None) -> pd.DataFrame` — enumerates one row per
`backbone × group × metric-family × K` cell that has at least one eligible (non-null
metric) flat/binned row. No dimension is averaged. `general` cells obey
`_general_cell_valid` (general metric non-null, and for MAP at least two of
`map_k_artist`/`map_k_genre`/`map_k_head` populated, mirroring how `map_k_general`
is derived). Columns: `backbone`, `group`, `metric`, `metric_col`, `k`, `n_eligible`.

`select_winner(rows, *, backbone, metric_col, k) -> dict | None` — deterministic
winner for one cell over all eligible flat+binned rows; null metric rows excluded;
ties broken by the smallest `TIE_BREAK_ORDER` key. Returns decoded fields plus
`value` (float) and `tie_break_key` (display), or `None` with no eligible row.

`build_winner_delta_rows(rows, baseline_rows, k_values=None, *, corpus_hash, corpus_size) -> pd.DataFrame` —
baseline per cell is exactly `global_pool:{backbone}:medoid` resolved from
`baseline_rows` for the same backbone and K (`canonical_flat_baseline`) — never a
cross-strategy or cross-backbone aggregate. The baseline reference is excluded from
winner candidacy, so `delta = winner_value - baseline_value` can be negative, zero on
a tie, positive only when a config beats it. Emits `WINNER_DELTA_COLUMNS`;
`corpus_hash`/`corpus_size` carried verbatim.

`build_factor_summary(winner_delta_rows) -> pd.DataFrame` — for every factor in
`FACTOR_COLUMNS`, groups winner rows by `(backbone, factor value, group, metric, K)`
and emits `n_wins`, `mean_delta`, `best_delta`, and the contributing `config_ids`
(winner strategy keys). No averaging across hidden configurations.

---

## _winners_report.py

### `section_winners(df, corpus_by_backbone=None) -> dict`

**Signature:** `(df: pd.DataFrame, corpus_by_backbone: Mapping[str, Any] | None = None) -> dict`

**DataFrame input:** the decoded `analyze_metrics` frame. `corpus_by_backbone`
optionally maps each backbone to its `MatchingCorpusManifest`; `_corpus_identity`
extracts `(corpus_hash, len(manifest))` to populate `corpus_hash`/`corpus_size`.

**Processing:**

- For each backbone: builds the `winner_delta` table (`id=f"winner_delta_{backbone}"`,
  title `"Winners & deltas vs global_pool:{backbone}:medoid"`) and, when present, the
  `factor_summary` table (`id=f"factor_summary_{backbone}"`, title `"Factor summary"`).
- Each backbone becomes an inline v2 subsection dict (all 11 keys) with `id=f"winners-{backbone}"`.

**Return value:** v2 section dict with `id="winners"`, `title="Exact Winners & Deltas"`.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| Empty / no `backbone` or `strategy_type` column | `"No retrieval data yet. Run the eval phase first."` |
| No winner-delta rows computable for any backbone | `"No winner-delta rows could be computed. An explicit global_pool:{backbone}:medoid baseline row is required for each backbone."` |

---

## _truncation.py

### `_delta_text(value: float | None) -> str`

Private helper. Formats a delta value:

- `None` → `"—"`
- `value > 0` → `f"+{value:.4f} ↑"`
- `value < 0` → `f"{value:.4f} ↓"`
- `value == 0` → `f"{value:.4f}"`

---

### `section_truncation(con) -> dict`

**Signature:** `(con) -> dict`

**DB reads:**

| Table | Columns read | Order |
| --- | --- | --- |
| `truncation_robustness_rows` | `backbone`, `bin_mode`, `std_thresh`, `flat_mean_sim`, `binned_mean_sim`, `truncation_robustness_delta` | `backbone, bin_mode, std_thresh` |

**Processing:**

1. Groups rows by `backbone`.
2. Per backbone, builds a table with columns:
   `bin_mode`, `std_thresh`, `flat_mean_sim`, `binned_mean_sim`, `delta (δ)` (via `_delta_text`).
3. Computes `mean_delta` across all rows.
4. Builds a `headline` dict with icon `"✂️"` and colour:
   - `#4ade80` if `mean_delta > 0`
   - `#f87171` if `mean_delta < 0`
   - `#7ec8e3` if `mean_delta == 0`

**Return value:** v2 section dict with `id="truncation"`, `title="Truncation Robustness"`.

**Populated fields:**

- `stats`: `[{label: "rows", value: int}, {label: "backbones", value: int}, {label: "mean δ", value: str}]`
- `subsections`: per-backbone dicts with keys:
  `id`, `title`, `description` (= `_INTERPRETATION_GUIDE`), `stats`, `charts`,
  `tables`, `panels`, `subsections`, `warnings`
  (**Note:** subsection dicts do NOT include `headline` or `empty_message` keys.)
- `headline`: `{icon, color, text}`
- `charts`, `tables`, `panels`, `warnings`: all `[]`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| `truncation_robustness_rows` table missing | `"No truncation data yet. Run the truncation phase to populate this section."` |
| Query exception | `"Could not load truncation robustness data."` |
| Table exists but empty | `"No truncation data yet. Run the truncation phase to populate this section."` |

---

## V2 Section Dict Shape Reference

All `section_*` functions return a dict produced by `make_section()`. The
full shape is:

```python
{
    "id": str,                    # kebab-case section identifier
    "title": str,                 # human-readable title
    "description": str,           # markdown/HTML description; "" when empty
    "stats": list[dict],          # [{"label": str, "value": any}, ...]; [] when none
    "charts": list[dict],         # make_chart() dicts; [] when none
    "tables": list[dict],         # make_table() dicts; [] when none
    "panels": list[dict],         # make_panel() dicts; [] when none
    "subsections": list[dict],    # inline section-shaped dicts; [] when none
    "warnings": list[dict],       # [{"id", "level", "message", "detail"}, ...]; [] when none
    "headline": dict | None,      # {"color": str, "icon": str, "text": str} or None
    "empty_message": str,         # non-empty string when section has no data
}
```

**Guaranteed keys:** All 11 keys above are always present in the returned dict
(defaults applied by `make_section`).

**Empty section contract:** When a section has no data, it is returned with all
list fields as `[]`, `headline=None`, `description=""`, `stats=[]`, and a
non-empty `empty_message`. Charts and tables will also be `[]`.

**Inline subsection dicts** (built by-hand in `section_per_backbone`,
`section_threshold_sweep`, `section_bin_mode_comparison`,
`section_head_sim_corr`, `section_bin_diversity` (ids `div-{backbone}`),
`section_segment_counts` (ids `seg-{backbone}`),
`section_flat_binned_correlation` (ids `fbcorr-{backbone}`), and
`section_winners` (ids `winners-{backbone}`)) carry all 11 keys. The exception is
`section_truncation` subsections, which carry only 9 keys (`headline` and
`empty_message` are absent from those inner dicts).

### Chart descriptor shape

```python
{"id": str, "title": str, "type": "plotly", "figure": dict}
```

### Table descriptor shape

```python
{
    "id": str,
    "title": str,
    "columns": list[str],
    "rows": list[list[str]],  # fmt()-encoded
    "collapsible": bool,
    "summary_text": str,
    "open": bool,
    "empty": bool,
}
```

### Panel descriptor shape

```python
{
    "id": str,
    "title": str,
    "open": bool,
    "charts": list[dict],
    "tables": list[dict],
    "text": str,
    "subsections": list[dict],
}
```

---

## 7. Pipeline Orchestration (run.py, classify.py, embed.py, config.py)

## 1. Pipeline Phases

All phases are registered in `run.py`'s `_PHASES` ordered dict and executed by `main()` in the
order shown. Each phase receives the shared `cfg` dict built from `research_config.toml`.

```
ingest → embed → stratify → segment → classify → analyze → head → report
```

`optimize` is **not** a phase — it is a manual-only utility invoked via `strategy_binned._optimize.optimize_std_threshold` (see the `### Threshold optimization` section below); `truncate` is an **inactive** phase (no `run._PHASES` key; truncation robustness is not active, see `DIST_THRESHOLDS`).

### Phase 1 — `ingest`

**Entry point:** `strategy_meta.ingest(con, limit, force)`

**What it does:** Walks `MEDIA_ROOT` for all audio files (stratified to `limit` songs), extracts
full metadata via `path_to_meta` (nomarr tag normaliser), and writes each song to the `songs`
table with columns `(song_id, path, artist, album, title, genre)`.

**DB state required:** `songs` table must exist (created by `db.ensure_schema`).

**DB state produced:** `songs` table populated. Every subsequent phase reads `song_id` and `path`
from this table (binned sub-phases) or derives them from `discover_audio()` (flat sub-phases).

---

### Threshold optimization `optimize` — manual-only utility (no run.py phase)

The threshold optimizer is **not** a `run._PHASES` phase: there is no `_optimize_phase` function and
`run.py::_PHASES` has no `optimize` key. It is invoked directly as a manual utility by calling
`strategy_binned._optimize.optimize_std_threshold` (see its module docstring and the
`[optimization]` / `[optimization.strategy]` config sections below).

**What `optimize_std_threshold` does:** For one `(backbone, bin_mode)` pair, given an in-memory
subsample of songs it grid-searches (or runs GSS) over `search_range` to find the distance
threshold that maximises the chosen disc metric using the configured weighted aggregation.
It writes the full per-threshold diagnostics table to
`{OUTPUT_ROOT}/optimizer/threshold_curve_{backbone}_{bin_mode}.csv`. It reads nothing back from
that CSV (the prior skip-guard cache logic lives in this section's historical notes and does not
apply to the current manual utility).

**DB state required:** `songs` table populated so `optimize_std_threshold` can subsample song ids;
the optimizer loads raw patch sidecars directly (it does not require the binned embed cache).

**DB state produced:** Nothing written to the DB. The optimal threshold is returned in-memory as
an `OptimizationResult`; the caller is responsible for using that value.

**Filesystem reads/writes:**
- Reads: raw patch sidecar files for the sampled songs
- Writes: `{OUTPUT_ROOT}/optimizer/threshold_curve_{backbone}_{bin_mode}.csv`

---

### Phase 3 — `embed`

**Entry point:** `run.py::_embed(con, cfg)` — two sequential sub-phases.

#### Sub-phase 3a — flat embed

**Entry point:** flat (global-pool) vectors are produced in the **segment** phase —
`run.py::_segment_phase` calls `common.segment.segment(con, strategy_global_pool.segment_fn.segment_fn, cfg["flat_strategies"], ...)`. Pooling per strategy is defined by `pooling.STRATEGIES`; vectors are written via `cache.flat_vecs.save_pooled`.

**What it does:**

1. For each backbone × audio file: runs the backbone ONNX model on mel-spectrogram patches to
   produce a `[n_patches, embed_dim]` float32 array.
2. Saves the raw patches as a **sidecar** file:  
   `{PATCHES_DIR}/{song_id}.{backbone}.npy`  
   (skipped if file already exists and `force=False`).
3. Applies every configured pooling strategy in `STRATEGIES` (mean, trimmed_10, trimmed_20, median, max_norm, l2norm_mean, medoid) to produce a
   `[embed_dim]` flat vector per strategy.
4. Saves each pooled vector to the **flat filesystem cache**:  
   `{OUTPUT_ROOT}/cache/{backbone}/{strategy}/flat/{song_id}.npy`

**DB state required:** `songs` table populated (only for registering new songs mid-run; flat
embed does *not* read songs from DB for its work list — it uses `discover_audio()` directly).

**DB state produced:** Nothing written to DuckDB. All outputs are `.npy` files on disk.

#### Sub-phase 3b — binned embed (segment phase)

**Entry point:** `run.py::_segment_phase` → `common.segment.segment(...)` with
`strategy_ptc/segment_fn.py::make_segment_fn(con)` (PTC) and
`strategy_ctp/segment_fn.py::make_segment_fn(head_sessions, run_in_batches_fn)` (CTP).
There is **no** `strategy_binned._embed` module — binned pooling runs in the segment phase.

**What it does:**

1. Reads song list from `db.load_all_songs(con)` filtered to `song_ids`.
2. For each song × backbone: loads the raw sidecar `{sid}.{backbone}.npy`, runs
   `temporal_segment` for each strategy combo, pools each segment via `_pool_segment`
   (mean, median, medoid, max, min); for CTP only, runs the head ONNX model on the patches to
   obtain the score-stream that drives segmentation.
3. Writes per-song NPZ files to the **filesystem caches**:
   - PTC: `{OUTPUT_ROOT}/cache/binned_ptc/{cache_semantics_tag()}/{backbone}/{bin_mode}/{threshold_key}/{song_id}.npz`
   - CTP: `{OUTPUT_ROOT}/cache/binned_ctp/{cache_semantics_tag()}/{backbone}/{head}/{threshold_key}/{song_id}.npz`
   Each NPZ stores: pooled vec arrays per strategy, weights, outlier counts, indices.

**Filesystem state required:** `songs` table populated and sidecar `.npy` files on disk.

**Filesystem state produced:**

- NPZ files on disk (not in DB).

---

### Phase 4 — `classify`

**Entry point:** `run.py::_classify(con, cfg)` — two sequential sub-phases.

#### Sub-phase 4a — flat classify

**Entry point:** `classify.run_flat(con, song_ids, force, backbones, heads, device)`

**What it does:** For each `(song, backbone, head, strategy)` combination runs the ONNX head on:

- **PTC** pathway: the pre-pooled flat vector from the filesystem cache (pool → classify).
- **CTP** pathway: the raw patches from the sidecar → run head on each patch → pool the
  activations.

Both activation vectors are written to the `flat_classify` DB table via `upsert_head`.

**DB state required:** Flat filesystem cache populated (sub-phase 3a).

**DB state produced:** `flat_classify` table rows `(sid, backbone, head, strategy, pathway, activations)`.

#### Sub-phase 4b — binned classify

**Entry point:** `classify.run_binned(con, song_ids, force, backbones, heads, device, thresholds_by_backbone)`

**What it does:** For each `(song, backbone, head, std_thresh)` combo (there is **no** `bin_mode` axis):

- Loads the raw sidecar patches.
- Runs the ONNX head on patches, computes the per-segment mean head activation per bin, and
  writes the head-activation arrays to the `binned_ctp_heads` filesystem cache via
  `binned_ctp_heads.save(...)` (`{OUTPUT_ROOT}/cache/binned_ctp_heads/**`).

The CTP bin-pooled embedding vectors are **not** produced here — they are written in the **segment
phase** by `strategy_ctp/segment_fn.py` (via `binned_ctp.save`, `{OUTPUT_ROOT}/cache/binned_ctp/`),
using the same segment boundaries from the head score-stream. Sub-phase 4b only extends the
head-activation slice of the CTP write path.

Note: the historical `upsert_binned_classify_ctp_bulk` DB writer is **dead** (0 callers); no
`binned_classify_ctp` table rows are written in sub-phase 4b.

**Filesystem state required:** Sidecar `.npy` files must exist on disk; the CTP segment phase must
have run.

**Filesystem state produced:**

- `binned_ctp_heads` NPZ files in `{OUTPUT_ROOT}/cache/binned_ctp_heads/`.

---

### Phase 5 — `analyze`

**Entry point:** `run.py::_analyze_phase(con, cfg)` — a single shared analysis phase driven by `common.analyze.analyze`.

`run.py::_analyze_phase` first clears `analyze_metrics`, then invokes `common.analyze.analyze` for the primary configurations and, only when the `[archival_ctp]` deferred/archival switch is enabled, the archival CTP configuration:

1. **global-pool (flat)** — `GLOBAL_POOL_ANALYZE_CFG`: analyzes the flat pooled vectors (filesystem `cache/{backbone}/{strategy}/flat/{song_id}.npy`) across the configured flat strategies (shipped default `["medoid"]` — the observed-patch `medoid` baseline). MusicNN is analyzed here only when explicitly configured.
2. **PTC** — `PTC_ANALYZE_CFG`: analyzes the patch-to-centroid binned pooled vectors loaded from the NPZ cache, evaluating the configured `score_variants` (shipped default primary-only `max_per_candidate_segment`).
3. **CTP (archival, opt-in)** — `CTP_ANALYZE_CFG`: analyzes the centroid-to-patch (head-guided) embedding pools loaded from the NPZ cache. This block is gated behind `run.py::_ctp_enabled()` (`[archival_ctp] enabled=true`); by default it does not run, so CTP rows never enter the primary report grid.

Each `common.analyze.analyze` invocation writes aggregate retrieval/discriminability metrics to `analyze_metrics` and per-song retrieval metrics to `song_retrieval_metrics` (via `db.flat.write_analyze_metrics` / `db.flat.write_song_retrieval_metrics`). There are **no** `flat_*`, `binned_*`, `ctp_*`, or `ptc_ctp_metrics` analysis tables — the flat/binned/CTP analyses all share the same `analyze_metrics` + `song_retrieval_metrics` tables, distinguished by `strategy_type` (`global_pool` | `ptc` | `ctp`).

**DB state required:** Tables from phases 3 and 4.

**DB state produced:** `analyze_metrics` + `song_retrieval_metrics`.

---

### Phase 6 — `head` (shared-boundary head pooling)

**Entry point:** `run.py::_head_phase(con, cfg)` — optional, non-blocking.

**What it does:** Pools classifier head outputs over the **shared EffNet PTC boundary**
(`boundary_source="effnet_ptc"`, `head_pool_variant="shared_effnet_ptc_boundary"`) by calling
`classify.run_shared_ptc_head_pooling(...)`. For each `(backbone, head, bin_mode, threshold)` config
tuple it reads the PTC bin cache boundaries (`bin_start_idx` / `bin_end_idx` / `weights`) — never
head-specific segmentation, never the CTP score-stream segmenter — pools the head activations per bin,
and records one additive provenance row in `head_phase_provenance` via
`build_head_phase_provenance_rows` / `write_head_phase_provenance`. The phase result
(`HeadPhaseManifest`) is stored in `cfg["head_phase_manifest"]` for the report phase.

**DB state required:** `songs`, sidecar patches, and the EffNet PTC binned segment caches populated
(phases 3–4).

**DB state produced:** `head_phase_provenance` rows (ADDITIVE — never touches `analyze_metrics`, the
corpus, or the winner grid).

**Non-blocking:** missing PTC caches or heads yield `skipped` / `error` provenance rows and a
`HeadPhaseManifest` with those counts; the pipeline continues to the report phase regardless.

---

### Phase 7 — `truncate` (NOT an active phase)

> **Removed. `run.py::_truncate` and the `--skip-truncation` flag do not exist** — `run.py` `_PHASES`
> has no `truncate` phase (phases are `ingest`, `embed`, `stratify`, `segment`, `classify`,
> `analyze`, `head`, `report`). Truncation robustness analysis is not part of the pipeline; the historical
> `_truncate.py` module and its `truncation` table writes were removed. This block is retained only
> as a stub so the phase numbering reads sequentially; there is no corresponding orchestration.
---

### Phase 8 — `report`

**Entry point:** `run.py::_report(con, cfg)` → `report.run(con, out_path=REPORT_DIR, matching_corpora=cfg.get("matching_corpus"), head_phase_manifest=cfg.get("head_phase_manifest"))`

**What it does:** Reads all result tables and generates an HTML report under `{REPORT_DIR}/`.

**DB state required:** All prior tables populated (report gracefully degrades to empty-message
sections when a table is absent or empty).

**DB state produced:** Report files on disk. No DB writes.

---

## 2. Embed Skip / Existence Check

> **Note:** There is no `embed.py` at the package root. Backbone inference lives in
> `common/embed.py` (invoked by `run.py::_embed()`); flat (global-pool) vector production lives
> in `strategy_global_pool/` (`segment_fn.py`, `_embed.py`) and `pooling.py`; binned pooling runs
> in the **segment phase** via `strategy_ptc/segment_fn.py` and `strategy_ctp/segment_fn.py` (no
> `strategy_binned/_embed.py` exists).

### Flat (global-pool) embed

**Per-song guard in `_embed_song`:**

```python
if not force and all(_is_done(sid, backbone_name, s) for s in _STRATEGIES):
    return False  # → counted as skipped
```

`_is_done` is `cache.flat_vecs.is_done(song_id, backbone, strategy)` which checks:

1. Does `{OUTPUT_ROOT}/cache/{backbone}/{strategy}/flat/{song_id}.npy` exist?
2. Can it be loaded without raising `EOFError / OSError / ValueError`? (corrupt files are
   purged and treated as missing)

The check is **all-or-nothing at song level**: if even one strategy file is missing the entire
song is reprocessed. Only the **actually-missing** strategy files are written (the loop iterates
and calls `pool + save` only when `force or not _is_done(sid, backbone, strategy)`).

**Sidecar guard (raw patches):**

```python
if force or not sidecar.exists():
    np.save(str(sidecar), embeddings.astype(np.float32))
```

The sidecar is **never** read during flat embed — it is written here and consumed by binned
embed and classify phases.

---

### Binned embed (segment phase)

**Pre-scan (bulk, before per-song loop):**

```python
if not force:
    done_by_key = {}  # (song_id, backbone) → set[(bin_mode, std_thresh)]
    for sid_d, bb_d, bm_d, st_d in _list_cache_done():
        done_by_key.setdefault((sid_d, bb_d), set()).add((bm_d, float(st_d)))
else:
    done_by_key = {}
```

`_list_cache_done` is `cache.binned_ptc.list_done_keys()` which scans:
`{OUTPUT_ROOT}/cache/binned_ptc/**/*.npz` and returns one `(song_id, backbone, bin_mode, std_thresh)`
tuple per file found on disk.

**Per-song work list:**

```python
missing = all_combos_set - done_by_key.get((sid, backbone), set())
if missing:
    work.append((song, missing))
```

Only the **missing `(bin_mode, std_thresh)` combos** are computed; already-cached combos are
silently skipped. Songs where the sidecar `.npy` does not exist are counted as `skipped`.

**Patch-features guard:**

```python
if not _db.patch_features_done(con, sid):  # guarded by DB query
    feats = _extract_patch_features(path, n_patches)
    ...
```

---

## 3. Classify Skip / Existence Check

### Flat classify (`classify.run_flat`)

**Bulk pre-scan:**

```python
if not force:
    flat_done_raw = query_classify_done(con)  # all rows from flat_classify table
    fully_done_flat = _build_flat_done_set(flat_done_raw)
    done_strats_by_key = {}  # (sid, backbone, head) → set[strategy]
    for sid_d, bb_d, head_d, strat_d in fully_done_flat:
        done_strats_by_key.setdefault((sid_d, bb_d, head_d), set()).add(strat_d)
else:
    done_strats_by_key = {}
```

`_build_flat_done_set` collapses `(sid, backbone, head, strategy, pathway)` rows into
`(sid, backbone, head, strategy)` tuples where **both** `"ptc"` and `"ctp"` pathways are
present. A strategy is not considered done if only one pathway was written.

**Per-song work list:**

```python
done_strats = done_strats_by_key.get((sid, backbone_name, head_name), set())
missing = all_strategies - done_strats
if missing:
    work_flat.append((p, missing))
```

`_classify_song_missing` is called only for strategies in `missing_strats`; strategies already
present in the DB are never re-run.

**Additional guards inside `_classify_song_missing`:**

- If `missing_strats` is empty → returns `False` (no-op).
- If the sidecar `.npy` does not exist → returns `False` (skipped).
- If the sidecar is empty (`patches.size == 0`) → returns `False`.

---

### Binned classify (`classify.run_binned`)

**Bulk pre-scan (filesystem `binned_ctp_heads` cache):**

```python
if not force:
    ctp_heads_done = _binned_ctp_heads_cache.list_done_keys()  # (sid, backbone, head, std_thresh)
    done_thresholds_by_key = {}  # (sid, backbone, head) → set[std_thresh]
    for sid_d, bb_d, head_d, st_d in ctp_heads_done:
        done_thresholds_by_key.setdefault((sid_d, bb_d, head_d), set()).add(st_d)
else:
    done_thresholds_by_key = {}
```

`binned_ctp_heads.list_done_keys()` scans `{OUTPUT_ROOT}/cache/binned_ctp_heads/**/*.npz` and
returns one `(song_id, backbone, head, std_thresh)` tuple per file found on disk. The historical
`query_binned_classify_done` DB reader is **dead** (0 callers) — no pre-scan reads
`binned_classify_ctp`.

**Per-song work dict:**

```python
for head_name in head_sessions:
    done_c = done_thresholds_by_key.get((sid, backbone_name, head_name), set())
    missing = all_thresholds - done_c if not force else all_thresholds
    if missing:
        heads_missing[head_name] = missing
if heads_missing:
    work[p] = heads_missing
```

Only `std_thresh` values not yet present in the `binned_ctp_heads` cache are reprocessed. If the
sidecar `.npy` does not exist the song is skipped (no error).

---

### Shared-boundary head phase (`classify.run_ptc_heads`, `classify.run_shared_ptc_head_pooling`)

The optional `head` phase (see §7 Phase 6) is driven by two entry points in `classify.py`.

#### `run_ptc_heads(con, *, song_ids=None, force=False, backbones=None, heads=None, device="cpu", head_sessions=None) -> None`

Thin backward-compatible wrapper delegating to `run_shared_ptc_head_pooling` and **discarding** the
returned manifest. The legacy default `backbones=None` runs **every configured backbone**
(`backbones or list(BACKBONES)`).

#### `run_shared_ptc_head_pooling(con, *, song_ids=None, backbones=None, heads=None, bin_modes=None, thresholds=None, force=False, device="cpu", head_sessions=None) -> HeadPhaseManifest`

The canonical **shared PTC boundary** head phase. It consumes ONLY the EffNet PTC bin cache
boundaries (`bin_start_idx` / `bin_end_idx` / `weights`) — never the CTP score-stream segmenter
(`strategy_ctp.segment_fn`), never head-specific bins; CTP cache paths are not repurposed. **Non-blocking:**
missing PTC cache entries or heads produce `skipped` / `error` records with reasons in the manifest
rather than raising; primary EffNet PTC-versus-medoid analysis always completes
(`primary_analysis_succeeded=True`). It never mutates the primary corpus or winner grid.

Defaults:

- `backbones=None` → `["effnet"]`
- `heads=None` → all discovered heads for the backbone
- `bin_modes=None` / `thresholds=None` → all PTC cache bin modes / thresholds
- `song_ids=None` → all songs with EffNet PTC cache entries

Deterministic ordering: backbones, heads, bin modes, thresholds, and song IDs are processed in sorted
order. Each prepared config tuple is persisted as one additive row in `head_phase_provenance`
(`boundary_source="effnet_ptc"`, `head_pool_variant="shared_effnet_ptc_boundary"`) via
`db.head_phase.build_head_phase_provenance_rows` / `write_head_phase_provenance`.

---

## 4. Config Keys

### Source of truth

Config is loaded by `helpers.toml.load_research_config()` which reads
`scripts/embedding_research/research_config.toml`. Parsed in `run.py::main()` into `cfg`.

---

### `[pipeline]` section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `limit` | `int` | `0` (= all) | Number of songs in the working set; 0 means no cap. Applied in `discover_audio(limit=...)`. |
| `force` | `bool` | `false` | When `true`, skip-checks are bypassed in all phases; all work is recomputed and DB rows overwritten. |
| `device` | `str` | `"cpu"` | ONNX execution provider. `"cuda"` or `"gpu"` maps to GPU; anything else maps to `"cpu"`. |
| `backbones` | `list[str]` \| absent | `["effnet"]` (shipped); absent → all `BACKBONES` | Restrict phases to named backbones. The shipped config sets `backbones=["effnet"]`, so the follow-on primary experiment runs EffNet only. MusicNN remains supported by the existing independent backbone machinery but is enabled **only** by explicit selection (e.g. `backbones=["effnet","musicnn"]`); it is never part of default runs. When absent/empty all keys in `BACKBONES` are used. |
| `heads` | `list[str]` \| absent | `null` (= all) | Restrict classify/analyze phases to named heads. When absent/empty all discovered heads are used. |

---

### `[archival_ctp]` section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `enabled` | `bool` | `false` | Deferred/archival CTP (classify-then-pool) switch. When `false` (default), CTP segment functions, caches, and archival loaders remain available and callable but CTP requirements are excluded from the primary corpus and the archival CTP analyze block (and its rows/winners) never runs in the default primary report grid. Set `enabled = true` to include CTP explicitly as archival diagnostics, visibly separated from primary output. Read by `run.py::_ctp_enabled()`, which gates both the CTP requirement labels in `_corpus_requirements` and the archival CTP analyze block in `_analyze_phase`. |

---

### `[binning]` section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `dist_thresholds` | `list[float]` | `[0.3, 0.5, 0.7, 1.0]` (code) | Set of normalized L2 distance thresholds for temporal segmentation. Loaded as `DIST_THRESHOLDS` in `helpers.binning`. Overridden per-backbone by the optimizer when `optimization.enabled = true`. |
| `bin_modes` | `list[str]` | `["temporal_global", "temporal_perdim"]` (code) | Segmentation algorithm variants. `temporal_global` uses global L2 distance to segment centroid; `temporal_perdim` uses Chebyshev distance. Loaded as `BIN_MODES`. |

> **Note:** The TOML file's declared defaults differ from code defaults: TOML ships with
> `dist_thresholds = [0.5 … 1.4]` and `bin_modes = ["temporal_global"]`.
> The code-level defaults in `helpers/binning.py` are the fallback when the section is absent.

---

### `[pooling]` section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `flat_strategies` | `list[str]` \| absent | all known strategies (incl. `medoid`) | Explicit flat (global-pool) strategy list. The benchmark baseline MUST include `medoid` (the observed-patch baseline). Read by `pooling.load_flat_strategy_names` into `cfg["flat_strategies"]`; drives the segment phase and `GLOBAL_POOL_ANALYZE_CFG.strategy_names`. Options: `mean`, `trimmed_10`, `trimmed_20`, `median`, `max_norm`, `l2norm_mean`, `medoid`. Each configured backbone gets its own independently keyed set. |
| `rep_types` | `list[str]` | — | Per-bin segment representation used to build the NxM bin-vs-bin sim matrix in the binned (PTC/CTP) phases. Options: `mean`, `median` (coordinate-wise synthetic), `medoid` (observed segment), `max`, `min`. This does NOT drive the flat strategy list. |
| `score_variants` | `list[str]` \| absent | `["max_per_candidate_segment"]` (shipped primary-only) | Full scoring surface evaluated for the binned analysis phase. Read into `SCORE_VARIANTS` at `strategy_binned/_constants.py:92`; the shipped config sets `score_variants=["max_per_candidate_segment"]`, so the evaluated surface is **primary-only** and the weighted hypotheses run only when explicitly added to this key. Each value must be in `_ALLOWED_SCORE_VARIANTS` (the primary variant plus the three weighted hypotheses); a generic `mean`/`median`/`max`/`min`/`medoid` aggregate is rejected by `validate_score_variant`. When the key is **absent**, the fallback is the full surface `[PRIMARY_SCORE_VARIANT, *AGG_METHODS]` (primary plus all three weighted hypotheses). |

### `[pooling.hypotheses]` sub-section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `weighted_reductions` | `list[str]` | `["target_weighted", "bidirectional_weighted", "normalized_mean_pair_weighted"]` (code) | The legacy weighted hypothesis block, read into `AGG_METHODS` at `strategy_binned/_constants.py:76`. Options: `target_weighted`, `bidirectional_weighted`, `normalized_mean_pair_weighted` (the Part B weighted directional reductions). These are labelled **legacy weighted hypotheses** — opt-in comparison formulas, never default primary semantics; they are evaluated only when their names are explicitly added to `pooling.score_variants`. Legacy generic reductions (`mean`/`median`/`max`/`min`) are rejected, and `agg_method="medoid"` is rejected; `rep_type="medoid"` remains a valid **representation** (observed-patch baseline), not an aggregation method. |

---

### `[similarity]` section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `metrics` | `list[str]` | — | Distance/similarity metrics for retrieval scoring. Currently only `"cosine"` is used in the analysis. |

---

### `[analysis]` section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `k` | `int` | `10` | Retrieval list depth (top-k). Passed to `common.analyze.analyze` via `GLOBAL_POOL_ANALYZE_CFG`, `PTC_ANALYZE_CFG`, and `CTP_ANALYZE_CFG` in `run.py`. |
| `workers` | `int` | `4` | `ThreadPoolExecutor` worker count for the analysis phase (parallel backbone processing). |
| `blas_threads` | `int` | `1` | BLAS thread cap via `threadpoolctl`. `0` = no cap. Passed as `None` when zero. |

---

### `[optimization]` section

| Key | Type | Default (code) | Controls |
| --- | --- | --- | --- |
| `enabled` | `bool` | `false` | Historically gated an in-pipeline optimize phase; the optimizer is now a manual-only utility (no `_PHASES` entry) that reads this section if threaded. Kept for config compatibility; not read by `run.py`. |
| `search_range` | `[float, float]` | `[0.5, 1.25]` | Lower/upper bounds for the threshold search. Stored as `cfg["opt_range"]` (tuple). |
| `method` | `str` | `"grid"` | Optimizer method: `"grid"` (exhaustive grid) or `"gss"` (Golden-Section Search). |
| `grid` | `list[float]` \| absent | `null` | Explicit threshold grid. When present, used instead of `search_range + grid_step`. |
| `grid_step` | `float` | `0.05` | Step size when building the grid from `search_range`. |
| `subsample_size` | `int` | `200` | Songs evaluated per optimizer function call. |
| `objective` | `str` \| `dict` | `"disc_artist"` | Disc metric to maximise. Can be a string name or a dict with `{"name": ..., ...}` for composite objectives. Stored as `cfg["opt_objective"]` (name string) and `cfg["opt_objective_cfg"]` (full dict). |
| `tolerance` | `float` | `0.05` | GSS stopping criterion: stop when the search interval width falls below this. |
| `max_evals` | `int` | `15` | Hard cap on function evaluations regardless of method. |
| `flat_epsilon` | `float` | `1e-8` | Flatness detection threshold for the optimizer curve. |

---

### `[optimization.strategy]` sub-section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `rep_type` | `str` | `"median"` | Pooling strategy used during optimizer evaluation calls. Stored as `cfg["opt_rep_type"]`. |
| `agg_method` | `str` | `"target_weighted"` | Weighted reduction used during optimizer evaluation. Must be one of `target_weighted`, `bidirectional_weighted`, `normalized_mean_pair_weighted`; legacy generic reductions (`mean`/`median`/`max`/`min`) and `agg_method=medoid` are rejected. Stored as `cfg["opt_agg_method"]`. |
| `metric` | `str` | `"cosine"` | Similarity metric used during optimizer evaluation. Stored as `cfg["opt_metric"]`. |

---

### Environment variable override

| Variable | Default | Controls |
| --- | --- | --- |
| `RESEARCH_DB_PATH` | `{OUTPUT_ROOT}/research.duckdb` | Override the DuckDB path, e.g. to a fast local filesystem (`/tmp/research.duckdb`). |

---

## 5. The `HEADS` Constant

**Location:** `config.py`, built at import time by `_discover_heads()`.

**Type:** `dict[str, dict[str, str]]`

**Structure:**

```python
HEADS = {
    "effnet": {
        "timbre":              "/app/models/effnet/heads/softmax/timbre-discogs-effnet-1.onnx",
        "approachability_2c": "/app/models/effnet/heads/softmax/approachability_2c-discogs-effnet-1.onnx",
        # ... one entry per .onnx file in the directory
    },
    "musicnn": {
        "timbre":              "/app/models/musicnn/heads/softmax/timbre-msd-musicnn-1.onnx",
        # ...
    },
}
```

**Population logic:** `_discover_heads()` iterates over every backbone in `BACKBONES` and
globs `{NOMARR_APP}/models/{backbone}/heads/softmax/*.onnx`. The **head name** is derived by
taking the first dash-delimited segment of the filename stem:

```python
head_name = f.stem.split("-")[0]
# e.g. "timbre-discogs-effnet-1".split("-")[0]  →  "timbre"
```

Files are visited in `sorted()` order so the dict is deterministic.

**Depth-1 key (backbone):** Must be a key in `BACKBONES` (`"effnet"`, `"musicnn"`). Backbones
not present in `BACKBONES` are never populated.

**Depth-2 key (head name):** Short identifier extracted from the ONNX filename. Known names:
`timbre`, `approachability_2c`, `engagement_2c`, `danceability`, `gender`, `mood_aggressive`,
`mood_happy`, `mood_party`, `mood_relaxed`, `mood_sad`, `tonal_atonal`, `voice_instrumental`.
(From `HEAD_LABELS` in `config.py`; actual presence depends on files on disk.)

**Depth-2 value (onnx_path):** Absolute string path to the `.onnx` file.

**Label mapping:** `HEAD_LABELS: dict[str, list[str]]` maps each head name to a two-element
list of `[class_0_label, class_1_label]`. Activation output index 1 is the "positive" class
(e.g. `"dark"`, `"aggressive"`, `"danceable"`, etc.).

**VRAM budget:** `HEAD_VRAM_BYTES = 20_761_804` bytes (~19.8 MB). All head sessions are created
with this limit via `create_session(model_path, device=device, vram_limit_bytes=HEAD_VRAM_BYTES)`.

---

## 6. Song ID Source and Propagation

### Derivation

```python
# config.py
def song_id(path: str | Path) -> str:
    """Deterministic 12-char ID from the absolute path."""
    return hashlib.sha256(str(path).encode()).hexdigest()[:12]
```

The ID is the **first 12 hex characters of SHA-256 over the absolute path string**. It is
stable across runs as long as the file path does not change.

### Working-set construction

`main()` builds the working set **once**, after `db.ensure_schema` and before any phase runs:

```python
cfg["song_ids"] = frozenset(
    song_id(p) for p in discover_audio(limit=cfg["limit"])
)
```

`discover_audio(limit)` returns a **stratified** list of audio `Path` objects from `MEDIA_ROOT`
(see `stratify_songs` — guarantees ≥2 songs per artist, album, genre). When `limit=0` all
files are returned in sorted order with no stratification cap.

After building `cfg["song_ids"]`, `main()` proceeds directly to model bootstrap and the
`_PHASES` loop; there is no per-run retrieval-row purge step.

### Propagation to phases

Every phase function receives `cfg["song_ids"]` as `frozenset[str] | None`.

| Phase / sub-phase | How `song_ids` is used |
| --- | --- |
| `ingest` | Passed as `limit` to `discover_audio` (not as a filter; `limit` controls list size; `discover_audio` returns the same stratified list) |
| `optimize` (manual utility, not a phase) | Passed to `optimize_std_threshold` via its `song_ids` parameter as a subsample scope |
| `flat embed` | `[p for p in discover_audio() if song_id(p) in song_ids]` — filters the discover list |
| `binned embed` | `[s for s in db.load_all_songs(con) if str(s["song_id"]) in song_ids]` — filters the DB song list |
| `flat classify` | `[p for p in discover_audio() if song_id(p) in song_ids]` |
| `binned classify` | `[p for p in discover_audio() if song_id(p) in song_ids]` |
| `flat analyze` | Passed as `song_ids` keyword; analysis restricts retrieval to songs in the set |
| `binned analyze` | Same |
| `PTC vs CTP metrics` | Converted to `sorted(song_ids)` as `sid_list` for DB queries |
| `CTP analyze` | Same as binned analyze |
| `truncate` | Passed as `song_ids` |
| `report` | Not used — report reads all rows from DB |

### `song_id` in the DB

The `songs` table primary key is `song_id VARCHAR`. It is written during `ingest` (and
lazily during flat embed when a song is encountered that was not yet ingested). All other tables
reference it as a plain `VARCHAR` foreign key — there is no enforced referential integrity
in DuckDB so phases that write before ingest completes will still work.

### Relationship between `discover_audio()` and DB song list

Flat phases call `discover_audio()` directly (filesystem-first). Binned phases call
`db.load_all_songs(con)` (DB-first). Both produce the same logical set of songs when ingest
has run, but the binned path relies on the DB having `path` populated per song. This is why
`ingest` is always the first phase.

---

## Score-variant identity (follow-on primary experiment — Phase 2)

### Primary vs hypothesis scoring semantics

* The authoritative **primary** scoring semantics is `max_per_candidate_segment`
  (see `scoring_harness.SegmentScoreTrace`). It is routable through PTC analysis
  via `strategy_binned._process.compute_score_variant_mats`.
* The three legacy weighted reductions (`target_weighted`,
  `bidirectional_weighted`, `normalized_mean_pair_weighted`) remain implemented
  and numerically tested, but are **labelled legacy weighted hypothesis**
  comparison formulas — opt-in only, never authoritative primary semantics.
* A generic `mean` / `median` / `max` / `min` / `medoid` aggregate must never
  re-enter as a scoring method. `validate_score_variant` rejects these at the
  request boundary. (`rep_type=medoid` remains a valid *representation*.)

### Allowed score variants

`strategy_binned._constants`:
* `_ALLOWED_SCORE_VARIANTS = ("max_per_candidate_segment", *_ALLOWED_AGG_METHODS)`
* `PRIMARY_SCORE_VARIANT = "max_per_candidate_segment"`
* `SCORE_VARIANTS` — the scoring surface actually evaluated for binned analysis.
  Defaults to `[PRIMARY_SCORE_VARIANT, *AGG_METHODS]`; config
  `pooling.score_variants` (Phase 3) may narrow it. Every entry is validated
  against `_ALLOWED_SCORE_VARIANTS`.
* `validate_score_variant(name) -> str` — raises `ValueError` for unknown names
  and for any generic aggregate.

### Score-variant compute surface (`strategy_binned._process`)

* `ScoreVariantResult` (frozen dataclass) — `score_variant`, `variant`
  (ambiguity variant name), `tie_policy`, `collision_policy`, `matrix` (the
  `[n, n]` float32 scalar retrieval matrix, rows = source), `traces`
  (bounded per-pair `SegmentScoreTrace` records).
* `compute_score_variant_mats(norm_a, norm_b, weights_a, weights_b, metric, *,
  score_variant=PRIMARY_SCORE_VARIANT, tie_policy, collision_policy)` — returns
  `ScoreVariantResult`. Requires `metric == "cosine"`; only the primary variant
  is implemented here (a weighted hypothesis raises `ValueError`). Every ordered
  `(i, j)` pair is scored independently; reverse pairs are computed separately
  from their own arrays — never by transposing/copying the forward matrix.
* `score_variant_trace_summary(result) -> dict[str, float]` — bounded, finite-only
  scalar summary (`trace_n_pairs`, `trace_numerator_sum/mean`,
  `trace_denominator_sum/mean`, `trace_collision_count`, `trace_winner_count`,
  `trace_retained_contributions`, `trace_dropped_contributions`, `trace_finite`).
  Never the raw matrix or per-pair contribution arrays.
* `compute_score_variant_retrieval_rows(result, ...) -> (rows, per_head_rows,
  trace_summary)` — retrieval rows whose DTO `agg_method` carries
  `result.score_variant` (the explicit score-variant identity) plus the bounded
  trace summary.

### Orchestration (`common.analyze`)

* The binned branch iterates the configured `score_variants` (from
  `extra_cfg["score_variants"]`, default `SCORE_VARIANTS`). The primary variant
  uses `compute_score_variant_mats` (matrix + traces); weighted hypotheses use
  `compute_agg_mats`.
* For the primary variant, only `score_variant_trace_summary(...)` (finite
  scalars) is persisted into `analyze_metrics`; the strategy key — whose
  position-6 `agg_method` is `max_per_candidate_segment` — is the trace
  reference. Raw unbounded matrices/contribution arrays are never written to
  scalar metric rows.
* `_build_expected_strategy_keys` iterates `SCORE_VARIANTS` (a superset of
  `AGG_METHODS`), so primary keys participate in done-set checks.

### Score-variant identity end-to-end

* **Strategy key** — position 6 (`agg_method`) of a `ptc:`/`ctp:` key carries the
  score-variant identity (`max_per_candidate_segment` or a weighted name).
* **Retrieval-row DTO** — `_BinnedRetrievalRow.agg_method` carries it.
* **Report decode** — `report._base._decode_strategy_key` round-trips position 6
  into `agg_method`; `agg_label` renders `max_per_candidate_segment` as
  `max-per-candidate` and the weighted names as `target-wtd` / `bidir-wtd` /
  `norm-pair-wtd`.
* **Cache/matrix identity** — `matrix_cache_identity` accepts an optional
  `score_variant` keyword and folds it (validated) into the identity hash, so a
  primary-variant cache can never collide with a different scoring method.

### Invariants preserved (unchanged from the completed repair)

* PTC segmentation is unit-vector; `act[1]` is the class-1 head score everywhere
  (`act[0]` never used); `disc_general` averages only non-zero valid components;
  there is no `disc_album` key anywhere; reverse-direction pair calculations are
  computed separately (never copied from transposes); matching-corpus rejection
  and versioned cache identity are unchanged.
