# Embedding Research Pipeline — Contracts

> Canonical API and schema reference. Edit this file whenever a function signature,
> return key, or column name changes. Run tests after any change.

## Table of Contents

- [1. Database Schema](#1-database-schema-db_schemapy-db_typespy-db__initpy)
- [2. Database Operations](#2-database-operations-dbflatpy-dbbinnedpy)
- [3. Similarity & Metrics](#3-similarity--metrics-similaritypy)
- [4. Flat Strategy](#4-flat-strategy-strategy_flat)
- [5. Binned Strategy](#5-binned-strategy-strategy_binned)
- [6. Report Sections](#6-report-sections-report)
- [7. Pipeline Orchestration](#7-pipeline-orchestration-runpy-classifypy-embedpy-configpy)

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

## DuckDB Tables (20 total)

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

## Table: `flat_head_labels`

**Primary key:** `(song_id, backbone, head)`

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| song_id | TEXT | NOT NULL |
| backbone | TEXT | NOT NULL |
| head | TEXT | NOT NULL |
| score | DOUBLE | NOT NULL — raw flat PTC activation score in `[0, 1]` |

---

## Table: `retrieval_rows`

**Primary key:** `(backbone, strategy, sim_metric, k)`

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| strategy | TEXT | NOT NULL |
| sim_metric | TEXT | NOT NULL |
| k | INTEGER | NOT NULL |
| map_k | DOUBLE | — |
| mrr | DOUBLE | — |
| ndcg_k | DOUBLE | — |
| recall_k | DOUBLE | — |
| n_songs | INTEGER | — |
| precision_k_genre | DOUBLE | — |
| precision_k_head_mean | DOUBLE | — |
| disc_score | DOUBLE | — |
| mean_within | DOUBLE | — |
| mean_cross | DOUBLE | — |
| disc_artist | DOUBLE | — |
| disc_genre | DOUBLE | — |
| disc_head | DOUBLE | — |
| disc_general | DOUBLE | — |

---

## Table: `ann_rows`

**Primary key:** `(backbone, strategy, ef_search)`

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| strategy | TEXT | NOT NULL |
| ef_search | INTEGER | NOT NULL |
| recall_k | DOUBLE | — |
| backend | TEXT | — |

---

## Table: `ptc_ctp_rows`

**Primary key:** `(backbone, head, strategy)`

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| head | TEXT | NOT NULL |
| strategy | TEXT | NOT NULL |
| ptc_disc | DOUBLE | — |
| ctp_disc | DOUBLE | — |
| delta_disc | DOUBLE | — |
| ptc_map | DOUBLE | — |
| ctp_map | DOUBLE | — |
| delta_map | DOUBLE | — |

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

## Table: `binned_retrieval_rows`

**Primary key:** `(backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)`

`rep_a` / `rep_b`: which pool representation is used for each song (`'mean'` | `'median'` | `'max'` | `'min'`).
`sim_metric`: `'cosine'` | `'l2'`.
`agg_method`: how the `[N_a × N_b]` bin-vs-bin matrix is collapsed (`'mean'` | `'median'` | `'max'` | `'min'`).

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
| disc_score | DOUBLE | — |
| map_k | DOUBLE | — |
| mrr | DOUBLE | — |
| ndcg_k | DOUBLE | — |
| recall_k | DOUBLE | — |
| recall_k_genre | DOUBLE | — |
| n_songs | INTEGER | — |
| precision_k_genre | DOUBLE | — |
| precision_k_head_mean | DOUBLE | — |
| flat_binned_spearman | DOUBLE | — |
| flat_binned_beneficial_reorder_rate | DOUBLE | — |
| mean_within | DOUBLE | — |
| mean_cross | DOUBLE | — |
| disc_artist | DOUBLE | — |
| disc_genre | DOUBLE | — |
| disc_head | DOUBLE | — |
| disc_general | DOUBLE | — |

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

## Table: `binned_ctp_retrieval_rows`

**Primary key:** `(backbone, head, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)`

CTP-derived retrieval metrics. Same metric schema as `binned_retrieval_rows` but keyed on `(backbone, head, ...)` because CTP segment boundaries are head-specific. `head` = the head whose score stream was STD-binned to determine segment indices.

| Column | Type | Constraints |
| -------- | ------ | ------------- |
| backbone | TEXT | NOT NULL |
| head | TEXT | NOT NULL |
| bin_mode | TEXT | NOT NULL |
| std_thresh | DOUBLE | NOT NULL |
| rep_a | TEXT | NOT NULL |
| rep_b | TEXT | NOT NULL |
| sim_metric | TEXT | NOT NULL |
| agg_method | TEXT | NOT NULL |
| k | INTEGER | NOT NULL |
| disc_score | DOUBLE | — |
| map_k | DOUBLE | — |
| mrr | DOUBLE | — |
| ndcg_k | DOUBLE | — |
| recall_k | DOUBLE | — |
| recall_k_genre | DOUBLE | — |
| mean_within | DOUBLE | — |
| mean_cross | DOUBLE | — |
| disc_artist | DOUBLE | — |
| disc_genre | DOUBLE | — |
| disc_head | DOUBLE | — |
| disc_general | DOUBLE | — |
| precision_k_genre | DOUBLE | — |
| precision_k_head_mean | DOUBLE | — |
| flat_binned_spearman | DOUBLE | — |
| flat_binned_beneficial_reorder_rate | DOUBLE | — |
| n_songs | INTEGER | — |

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

## Module: `db/_types.py`

---

## Dataclass: `BinnedRetrievalRow`

**Purpose:** DTO for one row of `binned_retrieval_rows` (PTC pathway).

| Field | Type | Default |
| ------- | ------ | --------- |
| backbone | `str` | — |
| bin_mode | `str` | — |
| std_thresh | `float` | — |
| rep_a | `str` | — |
| rep_b | `str` | — |
| sim_metric | `str` | — |
| agg_method | `str` | — |
| k | `int` | — |
| disc_score | `float \| None` | — |
| map_k | `float \| None` | — |
| mrr | `float \| None` | — |
| ndcg_k | `float \| None` | — |
| recall_k | `float \| None` | — |
| recall_k_genre | `float \| None` | — |
| mean_within | `float \| None` | — |
| mean_cross | `float \| None` | — |
| disc_artist | `float \| None` | — |
| disc_genre | `float \| None` | — |
| disc_head | `float \| None` | — |
| disc_general | `float \| None` | — |
| precision_k_genre | `float \| None` | — |
| precision_k_head_mean | `float \| None` | — |
| flat_binned_spearman | `float \| None` | — |
| flat_binned_beneficial_reorder_rate | `float \| None` | — |
| n_songs | `int \| None` | `None` |

### `as_tuple(self) -> tuple`

Returns all 25 fields in this exact order (for use as positional arguments to the upsert INSERT):

1. `backbone`
2. `bin_mode`
3. `std_thresh`
4. `rep_a`
5. `rep_b`
6. `sim_metric`
7. `agg_method`
8. `k`
9. `disc_score`
10. `map_k`
11. `mrr`
12. `ndcg_k`
13. `recall_k`
14. `recall_k_genre`
15. `mean_within`
16. `mean_cross`
17. `disc_artist`
18. `disc_genre`
19. `disc_head`
20. `disc_general`
21. `precision_k_genre`
22. `precision_k_head_mean`
23. `flat_binned_spearman`
24. `flat_binned_beneficial_reorder_rate`
25. `n_songs`

> **Note:** This order differs from the DDL column order for `binned_retrieval_rows`. Specifically, `n_songs` is last in `as_tuple()` but appears at position 15 in the DDL (after `recall_k_genre`), and the metric columns `mean_within` through `disc_general` appear earlier in `as_tuple()` than `precision_k_genre`, `precision_k_head_mean`, `flat_binned_spearman`, and `flat_binned_beneficial_reorder_rate`. Callers must use named-column INSERT statements, not positional.

### `from_metrics(cls, backbone: str, bin_mode: str, std_thresh: float, rep_a: str, rep_b: str, sim_metric: str, agg_method: str, k: int, metrics: dict) -> BinnedRetrievalRow`

Classmethod factory. Reads the following keys from `metrics` using `dict.get()` (all default to `None` if absent):

| Field assigned | Key read from `metrics` |
| ---------------- | ------------------------- |
| `disc_score` | `"disc_score"` |
| `map_k` | `f"map_{k}"` (interpolated with the `k` parameter) |
| `mrr` | `"mrr"` |
| `ndcg_k` | `f"ndcg_{k}"` (interpolated with the `k` parameter) |
| `recall_k` | `f"recall_{k}"` (interpolated with the `k` parameter) |
| `recall_k_genre` | `f"recall_{k}_genre"` (interpolated with the `k` parameter) |
| `mean_within` | `"mean_within"` |
| `mean_cross` | `"mean_cross"` |
| `disc_artist` | `"disc_artist"` |
| `disc_genre` | `"disc_genre"` |
| `disc_head` | `"disc_head"` |
| `disc_general` | `"disc_general"` |
| `precision_k_genre` | `"precision_k_genre"` |
| `precision_k_head_mean` | `"precision_k_head_mean"` |
| `flat_binned_spearman` | `"flat_binned_spearman"` |
| `flat_binned_beneficial_reorder_rate` | `"flat_binned_beneficial_reorder_rate"` |
| `n_songs` | `"n_songs"` |

---

## Dataclass: `CTPRetrievalRow`

**Purpose:** DTO for one row of `binned_ctp_retrieval_rows` (CTP pathway). Same metric fields as `BinnedRetrievalRow` but the primary key includes `head` between `backbone` and `bin_mode`.

| Field | Type | Default |
| ------- | ------ | --------- |
| backbone | `str` | — |
| head | `str` | — |
| bin_mode | `str` | — |
| std_thresh | `float` | — |
| rep_a | `str` | — |
| rep_b | `str` | — |
| sim_metric | `str` | — |
| agg_method | `str` | — |
| k | `int` | — |
| disc_score | `float \| None` | — |
| map_k | `float \| None` | — |
| mrr | `float \| None` | — |
| ndcg_k | `float \| None` | — |
| recall_k | `float \| None` | — |
| recall_k_genre | `float \| None` | — |
| mean_within | `float \| None` | — |
| mean_cross | `float \| None` | — |
| disc_artist | `float \| None` | — |
| disc_genre | `float \| None` | — |
| disc_head | `float \| None` | — |
| disc_general | `float \| None` | — |
| precision_k_genre | `float \| None` | — |
| precision_k_head_mean | `float \| None` | — |
| flat_binned_spearman | `float \| None` | — |
| flat_binned_beneficial_reorder_rate | `float \| None` | — |
| n_songs | `int \| None` | `None` |

### `as_tuple(self) -> tuple`

Returns all 26 fields in this exact order, which matches the DDL column order for `binned_ctp_retrieval_rows`:

1. `backbone`
2. `head`
3. `bin_mode`
4. `std_thresh`
5. `rep_a`
6. `rep_b`
7. `sim_metric`
8. `agg_method`
9. `k`
10. `disc_score`
11. `map_k`
12. `mrr`
13. `ndcg_k`
14. `recall_k`
15. `recall_k_genre`
16. `mean_within`
17. `mean_cross`
18. `disc_artist`
19. `disc_genre`
20. `disc_head`
21. `disc_general`
22. `precision_k_genre`
23. `precision_k_head_mean`
24. `flat_binned_spearman`
25. `flat_binned_beneficial_reorder_rate`
26. `n_songs`

### `from_binned(cls, row: BinnedRetrievalRow, head: str) -> CTPRetrievalRow`

Classmethod factory. Promotes a `BinnedRetrievalRow` to a `CTPRetrievalRow` by copying all fields verbatim from `row` and injecting `head` as the second positional field. Every field is transferred directly — no metrics are recomputed. Field mapping:

| `CTPRetrievalRow` field | Source |
| ------------------------- | -------- |
| `backbone` | `row.backbone` |
| `head` | `head` parameter |
| `bin_mode` | `row.bin_mode` |
| `std_thresh` | `row.std_thresh` |
| `rep_a` | `row.rep_a` |
| `rep_b` | `row.rep_b` |
| `sim_metric` | `row.sim_metric` |
| `agg_method` | `row.agg_method` |
| `k` | `row.k` |
| `disc_score` | `row.disc_score` |
| `map_k` | `row.map_k` |
| `mrr` | `row.mrr` |
| `ndcg_k` | `row.ndcg_k` |
| `recall_k` | `row.recall_k` |
| `recall_k_genre` | `row.recall_k_genre` |
| `mean_within` | `row.mean_within` |
| `mean_cross` | `row.mean_cross` |
| `disc_artist` | `row.disc_artist` |
| `disc_genre` | `row.disc_genre` |
| `disc_head` | `row.disc_head` |
| `disc_general` | `row.disc_general` |
| `precision_k_genre` | `row.precision_k_genre` |
| `precision_k_head_mean` | `row.precision_k_head_mean` |
| `flat_binned_spearman` | `row.flat_binned_spearman` |
| `flat_binned_beneficial_reorder_rate` | `row.flat_binned_beneficial_reorder_rate` |
| `n_songs` | `row.n_songs` |

---

## Module: `db/__init__.py`

### `__all__` Export List

The 47 public names exported from `scripts.embedding_research.db`, grouped by source submodule:

**From `_schema`:**

- `connect`
- `ensure_schema`
- `upsert_phase_timing`

**From `binned`:**

- `load_binned_sampling_stats`
- `load_calibration`
- `load_classify_ctp_rows`
- `purge_stale_retrieval_rows`
- `query_classify_ctp_sids`
- `query_ctp_analysis_done`
- `retrieval_rows_exist`
- `upsert_binned_classify_ctp_bulk`
- `upsert_binned_ptc_ctp_metrics`
- `upsert_binned_retrieval`
- `upsert_binned_retrieval_bulk`
- `upsert_binned_song_stats`
- `upsert_calibration`
- `upsert_ctp_retrieval_bulk`
- `upsert_head_agreement`
- `upsert_head_sim_corr_batch`
- `upsert_ptc_ctp_metrics_bulk`

**From `flat`:**

- `head_strategy_done`
- `load_head_labels`
- `load_retrieval_binned`
- `load_retrieval_flat`
- `query_flat_head_labels`
- `upsert_ann`
- `upsert_flat_head_labels`
- `upsert_head`
- `upsert_ptc_ctp`
- `upsert_retrieval`

**From `patch`:**

- `patch_features_done`

**From `queries`:**

- `query_analysis_done`
- `query_binned_analysis_done`
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

**From `truncation`:**

- `upsert_truncation_robustness`

---

## 2. Database Operations (db/flat.py, db/binned.py)

## `db/flat.py`

Module docstring: *Flat-embedding pipeline: retrieval_rows, ann_rows, ptc_ctp_rows.*
Pooled vectors and head activations are **not** stored in DuckDB — they live on the filesystem.
Head activations: `cache.flat_heads` (`cache/{backbone}/heads/{head_name}/{strategy}/{pathway}/{song_id}.npy`).
Pooled vectors: `cache.flat_vecs` (`cache/{backbone}/{strategy}/flat/{song_id}.npy`).
This module only handles scalar/metadata tables.

---

### `upsert_head(con, song_id, backbone, head, strategy, pathway, act)`

**Purpose:** Insert or replace a single song's head activation vector for one (song_id, backbone, head, strategy, pathway) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `song_id` | `str` | Unique song identifier |
| `backbone` | `str` | Embedding model backbone name |
| `head` | `str` | Head name (e.g. `"genre"`, `"artist"`) |
| `strategy` | `str` | Pooling/embedding strategy name |
| `pathway` | `str` | `"ptc"` or `"ctp"` |
| `act` | `list[float]` | Activation / class-probability vector |

**Returns:** `None`

**Filesystem write:** `{OUTPUT_ROOT}/cache/{backbone}/heads/{head}/{strategy}/{pathway}/{song_id}.npy`

> `con` is accepted for backward compatibility but ignored. This function is a shim that
> delegates to `cache.flat_heads.save(backbone, head, strategy, pathway, song_id, act)`.

**Missing-data behaviour:** No guards; all values passed directly. `act` may be any list.

---

### `head_strategy_done(con, song_id, backbone, head, strategy)`

**Purpose:** Return `True` when both pathways (ptc **and** ctp) have been written for a given (song_id, backbone, head, strategy) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `song_id` | `str` | Song identifier |
| `backbone` | `str` | Backbone name |
| `head` | `str` | Head name |
| `strategy` | `str` | Strategy name |

**Returns:** `bool` — `True` when both `ptc/` and `ctp/` files exist on disk.

**Filesystem check:** Delegates to `cache.flat_heads.is_done(backbone, head, strategy, song_id)`.

> `con` is accepted for backward compatibility but ignored.

**Missing-data behaviour:** Returns `False` when either pathway file is absent.

---

### `load_head_labels(con, sids, backbone, head, strategy, pathway, label_names)`

**Purpose:** Return a per-song majority-class label string for the given (backbone, head, strategy, pathway); returns `None` if more than 20% of requested songs are absent.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `sids` | `list[str]` | Ordered list of song IDs to label |
| `backbone` | `str` | Backbone name |
| `head` | `str` | Head name |
| `strategy` | `str` | Strategy name |
| `pathway` | `str` | `"ptc"` or `"ctp"` |
| `label_names` | `list[str]` | Mapping from class index → label string |

**Returns:** `list[str] | None` — label list aligned to `sids`, or `None` if >20% missing.

**Filesystem reads:** `cache.flat_heads.load_bulk(backbone, head, strategy, pathway, sids)`
Path pattern: `{OUTPUT_ROOT}/cache/{backbone}/heads/{head}/{strategy}/{pathway}/{song_id}.npy`

> `con` is accepted for backward compatibility but ignored.

**Missing-data behaviour:**

- A song absent from the cache receives label `"unknown"` and increments a missing counter.
- If `missing > 0.2 * len(sids)` the entire result is discarded and `None` is returned.
- A class index `cls` that exceeds `len(label_names)` falls back to the string `f"class_{cls}"`.

---

### `query_flat_head_labels(con, backbone, sids)`

**Purpose:** Return a 2-D matrix of per-head discriminability scores from `flat_head_labels`, shaped `[n_heads][n_sids]`.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `sids` | `list[str]` | Ordered list of song IDs |

**Returns:** `list[list[float]]` — outer list indexed by sorted head name; inner list indexed by `sids` position. Empty list `[]` if no rows exist.

**SQL table read:** `flat_head_labels`

**Columns selected:** `song_id, head, score`

**WHERE clause:** `backbone = ?`

**Missing-data behaviour:**

- No rows for backbone → logs a `WARNING` via `_log` and returns `[]`.
- Some songs absent → logs a `WARNING` listing the count; missing songs default to score `0.0`.
- DB head set differs from config head set → logs a `WARNING`; DB order is used.

---

### `load_retrieval_flat(con)`

**Purpose:** Return all flat retrieval result rows as a `DataFrame`, ordered by `disc_general DESC` (falling back to `disc_score`).

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |

**Returns:** `pd.DataFrame`

**SQL table read:** `retrieval_rows`

**ALTER TABLE guards (executed before SELECT):**

```sql
ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS disc_general DOUBLE
ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_genre DOUBLE
ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS precision_k_genre DOUBLE
ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS precision_k_head_mean DOUBLE
ALTER TABLE retrieval_rows ADD COLUMN IF NOT EXISTS n_songs INTEGER
```

**Columns selected:** `backbone, strategy, sim_metric, k, disc_general, disc_artist, disc_genre, disc_head, disc_score, mean_within, mean_cross, map_k, mrr, ndcg_k, recall_k, recall_k_genre, precision_k_genre, precision_k_head_mean, COALESCE(n_songs, 0) AS n_songs`

**ORDER BY:** `COALESCE(disc_general, disc_score, 0) DESC`

---

### `load_retrieval_binned(con)`

**Purpose:** Return all binned retrieval result rows as a `DataFrame`, ordered by `disc_general DESC` (falling back to `disc_score`).

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |

**Returns:** `pd.DataFrame`

**SQL table read:** `binned_retrieval_rows`

**ALTER TABLE guards (executed before SELECT):**

```sql
ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS disc_general DOUBLE
ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_genre DOUBLE
ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS precision_k_genre DOUBLE
ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS precision_k_head_mean DOUBLE
ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS flat_binned_spearman DOUBLE
ALTER TABLE binned_retrieval_rows ADD COLUMN IF NOT EXISTS flat_binned_beneficial_reorder_rate DOUBLE
```

**Columns selected:** `backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, disc_general, disc_artist, disc_genre, disc_head, disc_score, mean_within, mean_cross, map_k, mrr, ndcg_k, recall_k, recall_k_genre, precision_k_genre, precision_k_head_mean, flat_binned_spearman, flat_binned_beneficial_reorder_rate, COALESCE(n_songs, 0) AS n_songs`

**ORDER BY:** `COALESCE(disc_general, disc_score, 0) DESC`

---

### `upsert_retrieval(con, backbone, strategy, sim_metric, k, metrics, n_songs=0)`

**Purpose:** Insert or update one flat retrieval result row for the given (backbone, strategy, sim_metric, k) combination.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `strategy` | `str` | Strategy name |
| `sim_metric` | `str` | Similarity metric (e.g. `"cosine"`) |
| `k` | `int` | Top-k value for retrieval metrics |
| `metrics` | `dict` | Metric values (see key mapping below) |
| `n_songs` | `int` | Current corpus size; default `0` |

**`metrics` key mapping (all via `dict.get`, absent keys → SQL NULL):**

| Dict key | Column |
| --- | --- |
| `map_{k}` | `map_k` |
| `mrr` | `mrr` |
| `ndcg_{k}` | `ndcg_k` |
| `recall_{k}` | `recall_k` |
| `recall_{k}_genre` | `recall_k_genre` |
| `precision_k_genre` | `precision_k_genre` |
| `precision_k_head_mean` | `precision_k_head_mean` |
| `disc_score` | `disc_score` |
| `mean_within` | `mean_within` |
| `mean_cross` | `mean_cross` |
| `disc_artist` | `disc_artist` |
| `disc_genre` | `disc_genre` |
| `disc_head` | `disc_head` |
| `disc_general` | `disc_general` |

**Returns:** `None`

**SQL table written:** `retrieval_rows`

**Columns in INSERT (19):** `backbone, strategy, sim_metric, k, map_k, mrr, ndcg_k, recall_k, recall_k_genre, precision_k_genre, precision_k_head_mean, disc_score, mean_within, mean_cross, disc_artist, disc_genre, disc_head, disc_general, n_songs`

**Conflict resolution:** `ON CONFLICT (backbone, strategy, sim_metric, k)` — all 14 non-key metric columns updated to `excluded` values.

**Missing-data behaviour:** Any absent `metrics` key becomes SQL `NULL`.

---

### `upsert_ann(con, backbone, strategy, ef_search, recall_k, backend)`

**Purpose:** Insert or update one ANN benchmark row for (backbone, strategy, ef_search).

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `strategy` | `str` | Strategy name |
| `ef_search` | `int` | HNSW `ef_search` parameter value |
| `recall_k` | `float` | Measured recall\@k |
| `backend` | `str` | ANN backend identifier (e.g. `"hnswlib"`) |

**Returns:** `None`

**SQL table written:** `ann_rows`

**Columns in INSERT:** `backbone, strategy, ef_search, recall_k, backend`

**Conflict resolution:** `ON CONFLICT (backbone, strategy, ef_search) DO UPDATE SET recall_k=excluded.recall_k, backend=excluded.backend`

---

### `upsert_ptc_ctp(con, backbone, head, strategy, row)`

**Purpose:** Insert or update a PTC/CTP comparison summary row for a (backbone, head, strategy) combination.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `head` | `str` | Head name |
| `strategy` | `str` | Strategy name |
| `row` | `dict` | Metric values (see key mapping below) |

**`row` key mapping (all via `dict.get`, absent keys → SQL NULL):**

| Dict key | Column |
| --- | --- |
| `ptc_disc` | `ptc_disc` |
| `ctp_disc` | `ctp_disc` |
| `delta_disc` | `delta_disc` |
| `ptc_map` | `ptc_map` |
| `ctp_map` | `ctp_map` |
| `delta_map` | `delta_map` |

**Returns:** `None`

**SQL table written:** `ptc_ctp_rows`

**Columns in INSERT:** `backbone, head, strategy, ptc_disc, ctp_disc, delta_disc, ptc_map, ctp_map, delta_map`

**Conflict resolution:** `ON CONFLICT (backbone, head, strategy) DO UPDATE SET ptc_disc, ctp_disc, delta_disc, ptc_map, ctp_map, delta_map = excluded values`

**Missing-data behaviour:** Any absent key becomes SQL `NULL`.

---

### `upsert_flat_head_labels(con, song_id, backbone, head, score)`

**Purpose:** Insert or update a single flat head discriminability score for one (song_id, backbone, head) combination.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `song_id` | `str` | Song identifier |
| `backbone` | `str` | Backbone name |
| `head` | `str` | Head name |
| `score` | `float` | Discriminability score |

**Returns:** `None`

**SQL table written:** `flat_head_labels`

**Columns in INSERT:** `song_id, backbone, head, score`

**Conflict resolution:** `ON CONFLICT (song_id, backbone, head) DO UPDATE SET score=excluded.score`

---

---

## `db/binned.py`

Module docstring: *Binned-embedding pipeline: calibration, retrieval, stats.*

### Module-level constants

| Constant | Value |
| --- | --- |
| `_DISC_METRIC_COLS` | `disc_score, map_k, mrr, ndcg_k, recall_k, recall_k_genre, mean_within, mean_cross, disc_artist, disc_genre, disc_head, disc_general, precision_k_genre, precision_k_head_mean, flat_binned_spearman, flat_binned_beneficial_reorder_rate` (16 columns) |
| `_DISC_METRIC_SET` | Corresponding `col=excluded.col` SET clause for all 16 columns |

Both constants are shared across `upsert_binned_retrieval`, `upsert_binned_retrieval_bulk`, and `upsert_ctp_retrieval_bulk`.

---

### `upsert_calibration(con, backbone, dist_mode, p10, p25, p50, p75, mean_d, sigma_d, n_patches)`

**Purpose:** Insert or update distance-distribution calibration statistics for a (backbone, dist_mode) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `dist_mode` | `str` | Distance mode (e.g. `"cosine"`, `"euclidean"`) |
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

### `upsert_binned_retrieval(con, backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, metrics)`

**Purpose:** Insert or update one binned retrieval result row for the given (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k) combination.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `bin_mode` | `str` | Binning mode identifier |
| `std_thresh` | `float` | Std-dev threshold for bin creation |
| `rep_a` | `str` | First patch representation |
| `rep_b` | `str` | Second patch representation |
| `sim_metric` | `str` | Similarity metric |
| `agg_method` | `str` | Aggregation method |
| `k` | `int` | Top-k value |
| `metrics` | `dict` | Metric values (see key mapping below) |

**`metrics` key mapping (all via `dict.get`, absent keys → SQL NULL):**

| Dict key | Column |
| --- | --- |
| `disc_score` | `disc_score` |
| `map_{k}` | `map_k` |
| `mrr` | `mrr` |
| `ndcg_{k}` | `ndcg_k` |
| `recall_{k}` | `recall_k` |
| `recall_{k}_genre` | `recall_k_genre` |
| `mean_within` | `mean_within` |
| `mean_cross` | `mean_cross` |
| `disc_artist` | `disc_artist` |
| `disc_genre` | `disc_genre` |
| `disc_head` | `disc_head` |
| `disc_general` | `disc_general` |
| `precision_k_genre` | `precision_k_genre` |
| `precision_k_head_mean` | `precision_k_head_mean` |
| `flat_binned_spearman` | `flat_binned_spearman` |
| `flat_binned_beneficial_reorder_rate` | `flat_binned_beneficial_reorder_rate` |
| `n_songs` | `n_songs` |

**Returns:** `None`

**SQL table written:** `binned_retrieval_rows`

**Columns in INSERT (25):** 8 key columns + 16 from `_DISC_METRIC_COLS` + `n_songs`

**Conflict resolution:** `ON CONFLICT (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)` — `_DISC_METRIC_SET` + `n_songs=excluded.n_songs`

---

### `upsert_binned_retrieval_bulk(con, rows)`

**Purpose:** Bulk-insert/upsert a list of `BinnedRetrievalRow` DTOs into `binned_retrieval_rows`; no-op if `rows` is empty.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `rows` | `list[BinnedRetrievalRow]` | DTOs; `as_tuple()` must return a 25-element tuple matching column order |

**Returns:** `None`

**SQL table written:** `binned_retrieval_rows`

**Columns in INSERT (25):** same as `upsert_binned_retrieval`

**Conflict resolution:** identical to `upsert_binned_retrieval`

**Note:** `BinnedRetrievalRow.as_tuple()` and the SQL column list **must stay in sync** — the DTO is the source of truth for tuple ordering.

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

### `upsert_ptc_ctp_metrics_bulk(con, rows)`

**Purpose:** Bulk-insert/upsert PTC-CTP divergence metric rows; no-op if `rows` is empty.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `rows` | `list[tuple]` | Each tuple: `(backbone, bin_mode, std_thresh, head, divergence_mean, bin_count_var, sim_align_corr)` |

**Returns:** `None`

**SQL table written:** `binned_ptc_ctp_metrics`

**Columns in INSERT:** `backbone, bin_mode, std_thresh, head, divergence_mean, bin_count_var, sim_align_corr`

**Conflict resolution:** `ON CONFLICT (backbone, bin_mode, std_thresh, head) DO UPDATE SET divergence_mean=excluded.divergence_mean, bin_count_var=excluded.bin_count_var, sim_align_corr=excluded.sim_align_corr`

**Note:** Writes to the same table and uses the same conflict key as `upsert_binned_ptc_ctp_metrics`. Use the bulk variant for batch writes from analysis phases.

---

### `retrieval_rows_exist(con, backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric)`

**Purpose:** Return `True` if any `binned_retrieval_rows` exist for the given (backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric) configuration, regardless of `k` or `agg_method`.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `bin_mode` | `str` | Binning mode |
| `std_thresh` | `float` | Std-dev threshold |
| `rep_a` | `str` | First patch representation |
| `rep_b` | `str` | Second patch representation |
| `sim_metric` | `str` | Similarity metric |

**Returns:** `bool`

**SQL table read:** `binned_retrieval_rows`

**Query:** `SELECT 1 ... WHERE backbone=? AND bin_mode=? AND std_thresh=? AND rep_a=? AND rep_b=? AND sim_metric=? LIMIT 1`

**Missing-data behaviour:** Returns `False` when `fetchone()` is `None`.

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

### `upsert_head_agreement(con, backbone, head, bin_mode, std_thresh, agreement_rate, n_songs)`

**Purpose:** Insert or update a per-head bin-label agreement rate for a (backbone, head, bin_mode, std_thresh) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `head` | `str` | Head name |
| `bin_mode` | `str` | Binning mode |
| `std_thresh` | `float` | Std-dev threshold |
| `agreement_rate` | `float` | Fraction of songs where bin label matches overall label |
| `n_songs` | `int` | Number of songs evaluated |

**Returns:** `None`

**SQL table written:** `head_agreement_rows`

**Columns in INSERT:** `backbone, head, bin_mode, std_thresh, agreement_rate, n_songs`

**Conflict resolution:** `ON CONFLICT (backbone, head, bin_mode, std_thresh) DO UPDATE SET agreement_rate=excluded.agreement_rate, n_songs=excluded.n_songs`

---

### `upsert_binned_ptc_ctp_metrics(con, backbone, bin_mode, std_thresh, head, divergence_mean, bin_count_var, sim_align_corr)`

**Purpose:** Insert or update per-head PTC-CTP divergence metrics for a single (backbone, bin_mode, std_thresh, head) key.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `backbone` | `str` | Backbone name |
| `bin_mode` | `str` | Binning mode |
| `std_thresh` | `float` | Std-dev threshold |
| `head` | `str` | Head name |
| `divergence_mean` | `float` | Mean KL/JS divergence between PTC and CTP distributions |
| `bin_count_var` | `float` | Variance in bin-size counts |
| `sim_align_corr` | `float` | Similarity-alignment correlation |

**Returns:** `None`

**SQL table written:** `binned_ptc_ctp_metrics`

**Columns in INSERT:** `backbone, bin_mode, std_thresh, head, divergence_mean, bin_count_var, sim_align_corr`

**Conflict resolution:** `ON CONFLICT (backbone, bin_mode, std_thresh, head) DO UPDATE SET divergence_mean=excluded.divergence_mean, bin_count_var=excluded.bin_count_var, sim_align_corr=excluded.sim_align_corr`

**Note:** Single-row counterpart to `upsert_ptc_ctp_metrics_bulk`; both write to the same table with the same conflict key.

---

### `load_binned_sampling_stats(con)`

**Purpose:** Load one aggregated row per song across all completed binned configs, for deterministic stratified sampling of the library.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |

**Returns:** `list[dict]` — each dict has keys: `song_id, artist, n_configs, avg_n_bins, avg_n_patches, avg_n_outliers, avg_mean_bin_size, avg_bin_div_std`. Empty list if no data.

**SQL tables read:** `binned_song_stats` (aliased `bs`) joined to `songs` via `USING (song_id)`

**Aggregation:** `COUNT(*) AS n_configs`, `AVG(n_bins)`, `AVG(n_patches)`, `AVG(n_outliers)`, `AVG(mean_bin_size)`, `AVG(bin_div_std)` — grouped by `bs.song_id, s.artist`, ordered by `bs.song_id`

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

**Note:** The `bin_div_std` column (read by `load_binned_sampling_stats`) is **not** written by this function. It is absent from both the INSERT list and the ON CONFLICT SET clause.

---

### `query_ctp_analysis_done(con)`

**Purpose:** Return the set of (backbone, head, bin_mode, std_thresh, k, n_songs) tuples already present in `binned_ctp_retrieval_rows`; used to skip already-completed CTP analysis passes.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |

**Returns:** `set[tuple[str, str, str, float, int, int]]` — set of 6-tuples; empty set on any exception.

**SQL table read:** `binned_ctp_retrieval_rows`

**ALTER TABLE guard (before SELECT):** `ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS n_songs INTEGER`

**Query:** `SELECT DISTINCT backbone, head, bin_mode, std_thresh, k, COALESCE(n_songs, 0) AS n_songs FROM binned_ctp_retrieval_rows`

**Missing-data behaviour:**

- Legacy rows written before `n_songs` was added return `0` via `COALESCE`.
- Any exception (e.g. table does not exist) is caught and the function returns an empty `set()`.

---

### `upsert_ctp_retrieval_bulk(con, rows)`

**Purpose:** Bulk-insert/upsert CTP retrieval metric rows into `binned_ctp_retrieval_rows`; no-op if `rows` is empty.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `rows` | `list[CTPRetrievalRow]` | DTOs; `as_tuple()` must return a 26-element tuple matching column order |

**Returns:** `None`

**SQL table written:** `binned_ctp_retrieval_rows`

**ALTER TABLE guards (7, executed before INSERT):**

```sql
ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS disc_general DOUBLE
ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS recall_k_genre DOUBLE
ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS n_songs INTEGER
ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS precision_k_genre DOUBLE
ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS precision_k_head_mean DOUBLE
ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS flat_binned_spearman DOUBLE
ALTER TABLE binned_ctp_retrieval_rows ADD COLUMN IF NOT EXISTS flat_binned_beneficial_reorder_rate DOUBLE
```

**Columns in INSERT (26):** `backbone, head, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k` (9 key columns) + 16 from `_DISC_METRIC_COLS` + `n_songs`

**Conflict resolution:** `ON CONFLICT (backbone, head, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k)` — `_DISC_METRIC_SET` + `n_songs=excluded.n_songs`

**Note:** The conflict key is 9 columns vs. 8 in `binned_retrieval_rows` — `head` is the additional dimension.

---

### `purge_stale_retrieval_rows(con, n_songs)`

**Purpose:** Delete aggregated metric rows from all three retrieval tables where `n_songs` does not match the current corpus size, ensuring stale (wrong-corpus-size or legacy) rows are recomputed on the next analysis pass.

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| `con` | DuckDB connection | Open database connection |
| `n_songs` | `int` | Current corpus size (`len(cfg["song_ids"])`) |

**Returns:** `dict[str, int]` — maps table name to number of rows deleted; value is `0` for any table that raises an exception.

**SQL tables affected:** `retrieval_rows`, `binned_retrieval_rows`, `binned_ctp_retrieval_rows`

**ALTER TABLE guards:** one `ADD COLUMN IF NOT EXISTS n_songs INTEGER` per table, wrapped in `contextlib.suppress(Exception)` so missing-column errors do not abort.

**DELETE:** `WHERE n_songs IS NULL OR n_songs != ?` — catches both legacy rows (NULL) and size-mismatch rows.

**Error handling:** Each table's DELETE block is individually wrapped in `try/except Exception`. Failures log a `WARNING` via a locally-imported `_log` and record `0` deleted; other tables are still processed.

**Tables NOT purged (additive per-song data):** `binned_song_stats`, `binned_classify_ctp`, CTP filesystem cache, pair similarity caches.

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

## `l2_similarity_matrix(vecs: RawTensor) -> np.ndarray`

**Parameters:**

- `vecs`: `RawTensor` — input vectors, shape `(n, d)`

**Returns:** `np.ndarray` dtype `float32`, shape `(n, n)` — similarity derived from Euclidean distance.

Formula: $S_{ij} = \dfrac{1}{1 + \lVert v_i - v_j \rVert_2}$

**Key invariants:**

- Diagonal is exactly `1.0`.
- All values in `(0, 1]`.
- Uses the identity $\|a - b\|^2 = \|a\|^2 + \|b\|^2 - 2 a^\top b$ then clips negative
  squared-distances to `0` before sqrt to suppress floating-point underflow.
- Output is `float32`.

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
| `sim_matrix` | `np.ndarray` shape `(n, n)` | yes | Pairwise similarity matrix. Must be square. Any metric output (cosine, L2-sim, dot) is accepted — values are used as-is. |
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
For `disc_genre`, `disc_album`, and `disc_head` bin-groups it is computed via full matrix masks.

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

### Known Discrepancy: `albums` Parameter

> **Warning:** The function docstring lists `disc_album` as a returned key. It is **not present**
> in the actual `return` dict. The code computes `album_recalls` (a list of per-song album-recall
> values) but **does not include it in the return dict**. Callers passing `albums=` receive no
> album-level output. This is a docstring/implementation gap, not a design decision.

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

Wraps faiss HNSW (cosine) and IVF-Flat/Flat (L2) indices with a numpy brute-force fallback.

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
| `metric` | `str` | `"cosine"` | Distance metric. Must be one of `ANNIndex.SUPPORTED_METRICS = ("cosine", "l2")`. Asserted at construction; `AssertionError` on invalid value. |
| `hnsw_m` | `int` | `32` | HNSW graph connectivity parameter. Higher values improve recall at the cost of index build time and memory. Used only for `metric="cosine"` with faiss. |
| `hnsw_ef_construction` | `int` | `200` | HNSW construction beam width. Affects index quality, not query speed. Used only for cosine+faiss. |
| `hnsw_ef_search` | `int` | `64` | HNSW search beam width. Controls the recall/speed trade-off at query time. Can be updated via `set_ef_search()`. |
| `nlist` | `int` | `100` | Number of IVF clusters. Used only for `metric="l2"` with faiss, and only when `n > 4 * nlist`. Ignored when falling back to `IndexFlatL2`. |

**Backend selection at construction:**

| Condition | Index built |
| ----------- | ------------- |
| faiss available + `metric="cosine"` | `faiss.IndexHNSWFlat` with `METRIC_INNER_PRODUCT` on L2-normalised vectors |
| faiss available + `metric="l2"` + `n > 4 * nlist` | `faiss.IndexIVFFlat` with `nprobe = max(1, nlist // 10)` |
| faiss available + `metric="l2"` + `n <= 4 * nlist` | `faiss.IndexFlatL2` (exact) |
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
- No-op for `metric="l2"` (IVF indices do not use `efSearch`).

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
| faiss + l2 | Calls `self._index.search(qvec_np[None,:], k)`, returns `nn_idx[0]` |
| numpy + cosine | Normalises all stored vectors and query; returns `argsort(-sims)[:k]` |
| numpy + l2 | Computes L2 norms; returns `argsort(dists)[:k]` |

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

## 4. Flat Strategy (strategy_flat/)

## Module-level constants and paths

| Symbol | Value | Owner module |
| --- | --- | --- |
| `OUTPUT_ROOT` | `WORKSPACE / 'scripts/outputs/embedding_research'` | `config.py` |
| `PATCHES_DIR` | `OUTPUT_ROOT / 'patches'` | `config.py` |
| `_CACHE_ROOT` | `OUTPUT_ROOT / 'cache'` | `cache/flat_vecs.py` |
| `flat_ref/` | `OUTPUT_ROOT / 'flat_ref'` | `_analyze.py` (inline) |
| `STRATEGIES` | `{"mean", "trimmed_10", "trimmed_20", "median", "max_norm", "l2norm_mean"}` | `pooling.py` |
| `METRICS` | `{"cosine": cosine_matrix, "l2": l2_similarity_matrix}` | `similarity.py` |
| `HEADS` | `{backbone: {head_name: onnx_path}}` — populated by `_discover_heads()` at import time | `config.py` |
| `HEAD_LABELS` | `{head_name: [label_0, label_1]}` for known binary classifiers | `config.py` |
| `BACKBONES` | `{"effnet": {...}, "musicnn": {...}}` | `config.py` |
| `BIN_MODES` | list of binning modes, e.g. `["temporal_global", "perdim"]` | `helpers/binning.py` |
| `DIST_THRESHOLDS` | list of float thresholds used by default in truncation | `helpers/binning.py` |

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
      {cache_semantics_tag()}/{backbone}/{bin_mode}/{std_thresh:.3f}/{song_id}.npz
    binned_ctp/
      {cache_semantics_tag()}/{backbone}/{head}/{bin_mode}/{std_thresh:.3f}/{song_id}.npz
    sim/
      {cache_semantics_tag()}/{backbone}/{bin_mode}/{std_thresh:.3f}/{rep_a}_{rep_b}_{metric}.npz
  flat_ref/
    {backbone}_{strategy}_upper_tri.npy  # float32 [n*(n-1)/2] — cosine upper triangle
    {backbone}_{strategy}_sids.npy       # str array [n] — matching song IDs
  patches/
    {backbone}/
      {song_id}.npy            # float32 [n_patches, embed_dim] — raw patch embeddings
```

---

## `__init__.py`

Re-exports exactly three symbols:

```python
from ._analyze import analyze
from ._embed import embed
from ._truncate import analyze_truncation

__all__ = ["analyze", "analyze_truncation", "embed"]
```

No logic of its own.

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

## `_analyze.py` — Flat-pool analysis

### `_analyze_strategy(con, backbone, strategy, k=10, *, song_ids=None) -> None`

**Signature:**

```python
_analyze_strategy(
    con,
    backbone: str,
    strategy: str,
    k: int = 10,
    *,
    song_ids: frozenset[str] | None = None,
) -> None
```

| | |
| --- | --- |
| **Reads (FS)** | `cache/{backbone}/{strategy}/flat/*.npy` via `load_matrix` |
| **Reads (DB)** | `songs` table (via `load_matrix` metadata join) |
| **Reads (FS)** | `cache/{backbone}/heads/{head}/{strategy}/ptc/{song_id}.npy` via `flat_heads.load_bulk` (only when `HEADS[backbone]` is non-empty) |
| **Writes (FS)** | `flat_ref/{backbone}_{strategy}_upper_tri.npy` — cosine upper triangle |
| **Writes (FS)** | `flat_ref/{backbone}_{strategy}_sids.npy` — song ID array |
| **Writes (DB)** | `retrieval_rows` via `upsert_retrieval` — once per metric in `METRICS` |
| **Writes (DB)** | `flat_head_label_rows` via `upsert_flat_head_labels` — once per (head, song) pair |
| **Returns** | `None` |

**`song_ids` flow:**

1. `load_matrix` loads all sids present on disk for the (backbone, strategy)
   pair.
2. If `song_ids` is not `None`, a `keep` index list is computed: all positions
   where `sids[i] in song_ids`. `vecs`, `sids`, `artists`, `albums`, `genres`
   are all subset-indexed by this list.
3. The filtered arrays are used for all downstream calculations.

**Where `genres` comes from:**

- Returned as the fifth element of `load_matrix`. Populated from
  `songs.genre` in the DB. Falls back to `"unknown"` per song when `con=None`
  or the song is absent from `songs`.
- Passed to `compute_retrieval_metrics` as the `genres=` keyword argument for
  `disc_genre` computation.

**Where `head_scores` comes from and what `act` contains:**

- Loaded from the filesystem via `flat_heads.load_bulk(backbone, head_name, strategy, "ptc", sids)`.
  Path: `cache/{backbone}/heads/{head_name}/{strategy}/ptc/{song_id}.npy`.
- `act` is a float32 numpy array representing the softmax output of the head classifier.
  For binary heads it is 2-element: `act[0]` = negative class probability, `act[1]` = positive class probability.
- **Only `act[1]` is used** as the `head_score` for a song:

  ```python
  float(act_map[head_name][sid][1])
  ```

- If a song is absent from `act_map` for a given head, `0.0` is used as the
  default score.
- `head_scores` is a `list[list[float]]` — outer index over `head_names`, inner
  index over `sids` (same ordering as the filtered `sids` list).
- `head_scores` is `None` when `HEADS.get(backbone, {})` is empty (backbone has
  no registered heads).
- When `head_scores is not None`, `upsert_flat_head_labels` is called for every
  `(sid, head_name)` pair using `head_scores[h_idx][s_idx]`.

**`flat_ref/` files written (cosine metric only):**

- `_OUTPUT_ROOT / "flat_ref" / f"{backbone}_{strategy}_upper_tri.npy"`
  — upper triangle of the `[n, n]` cosine similarity matrix, extracted with
  `np.triu_indices(n, k=1)`, cast to `float32`. Shape: `[n*(n-1)//2]`.
- `_OUTPUT_ROOT / "flat_ref" / f"{backbone}_{strategy}_sids.npy"`
  — `np.array(sids)` string array, shape `[n]`.
- Directory is created with `parents=True, exist_ok=True`.
- These two files are always written together and are indexed identically:
  `sids[i]` and `sids[j]` (i < j) correspond to
  `upper_tri[k]` where `k = i*n - i*(i+1)//2 + j - i - 1` (standard upper-
  triangle linearisation).

**Key invariants:**

- `vecs`, `sids`, `artists`, `albums`, `genres` are always the same length `n`
  after filtering.
- `head_scores[h_idx]` has the same length `n` as `sids`.
- All metrics in `METRICS` (`"cosine"`, `"l2"`) are computed and upserted in
  a single call; only `"cosine"` triggers the `flat_ref` write.

**Skip conditions:**

- `len(vecs) == 0` after initial load → logs info and returns immediately.
- `len(vecs) == 0` after `song_ids` filtering → returns immediately (no log).

---

### `_analyze_ptc_vs_ctp(con, backbone, strategies, k=10, *, song_ids=None) -> None`

**Signature:**

```python
_analyze_ptc_vs_ctp(
    con,
    backbone: str,
    strategies: list[str],
    k: int = 10,
    *,
    song_ids: frozenset[str] | None = None,
) -> None
```

| | |
| --- | --- |
| **Reads (FS)** | `cache/{backbone}/{strategy}/flat/*.npy` via `load_matrix` |
| **Reads (FS)** | `cache/{backbone}/heads/{head}/{strategy}/{pathway}/{song_id}.npy` via `_load_head_labels` → `flat_heads.load_bulk` |
| **Writes (DB)** | `ptc_ctp_rows` via `upsert_ptc_ctp(con, backbone, head, strategy, row)` |
| **Returns** | `None` |

**Behaviour:**

- Outer loop: every `head_name` in `HEADS.get(backbone, {})`.
- Inner loop: every `strategy` in `strategies`.
- For each `(head, strategy)`: loads the cosine similarity matrix, then for
  each pathway (`"ptc"`, `"ctp"`) computes retrieval metrics using per-song
  class labels from `_load_head_labels`.
- The `row` dict accumulates `ptc_disc`, `ptc_map`, `ctp_disc`, `ctp_map`.
  `delta_disc` and `delta_map` are computed as `ptc - ctp` differences.
  Upserted only when both `ptc_disc` and `ctp_disc` are present.

**`song_ids` flow:**

- Same pattern as `_analyze_strategy`: index-filtered from the loaded sids
  using a `keep` list.
- Applied **after** `load_matrix` but **before** building `cos_mat`.
- When `song_ids` filters sids, `vecs` is wrapped in a new `RawTensor`:
  `RawTensor(vecs.data[keep])`.

**Skip conditions per (head, strategy, pathway):**

- `len(vecs) == 0` after load or filtering.
- `_load_head_labels` returns `None` — meaning >20% of songs are missing
  labels for this (head, strategy, pathway) combination.
- Fewer than 10 songs with known (non-`"unknown"`) labels after `unknown`
  filter.
- Only 1 unique class remains after filtering — logged at DEBUG level.

**Upsert condition:** `upsert_ptc_ctp` is called **only** when both
`"ptc_disc"` and `"ctp_disc"` are present in `row` (i.e. both pathways
completed successfully for this head+strategy pair).

---

### `_analyze_ann(con, backbone, strategy='mean', k=10, n_queries=200, *, song_ids=None, min_corpus_for_sweep=2000) -> None`

**Signature:**

```python
_analyze_ann(
    con,
    backbone: str,
    strategy: str = "mean",
    k: int = 10,
    n_queries: int = 200,
    *,
    song_ids: frozenset[str] | None = None,
    min_corpus_for_sweep: int = 2_000,
) -> None
```

| | |
| --- | --- |
| **Reads (FS)** | `cache/{backbone}/{strategy}/flat/*.npy` via `load_matrix` |
| **Reads (DB)** | `songs` table (via `load_matrix`) |
| **Writes (DB)** | `ann_rows` via `upsert_ann(con, backbone, strategy, ef_search, recall_k, backend)` |
| **Returns** | `None` |

**Skip conditions:**

- `len(vecs) == 0` after load → returns immediately.
- Corpus size `n < min_corpus_for_sweep` (default 2000) after song_id
  filtering → logs info and returns. ANN calibration is skipped for small
  corpora where exact brute-force is fast enough.

**`song_ids` flow:**

- Same index-filter pattern: `keep` list computed, then
  `vecs = RawTensor(vecs.data[keep])` and `artists = [artists[i] for i in keep]`.
- `_albums` and `_genres` are also filtered but discarded (prefix `_`).

**Invocation context:** Called by `analyze()` with `strategy="mean"` only,
regardless of which strategies were actually worked. ANN sweep is intentionally
only calibrated for the `mean` pooling strategy.

**`ann_recall_sweep` return structure:**

```python
{"ef_{ef}": {"recall_k": float, "backend": "faiss"|"numpy", "ef_search": int}}
```

Each row is upserted separately via `upsert_ann`.

---

### `analyze(con, *, k=10, backbones=None, strategies=None, song_ids=None) -> None`

**Signature:**

```python
analyze(
    con,
    *,
    k: int = 10,
    backbones: list[str] | None = None,
    strategies: list[str] | None = None,
    song_ids: frozenset[str] | None = None,
) -> None
```

| | |
| --- | --- |
| **Reads (FS)** | `cache/` tree — `list_configs()` and `list_done_sids()` |
| **Reads (DB)** | `retrieval_rows` via `query_analysis_done(con)` |
| **Writes (DB)** | Via `_analyze_strategy`, `_analyze_ptc_vs_ctp`, `_analyze_ann` |
| **Writes (FS)** | `flat_ref/` files (via `_analyze_strategy`) |
| **Returns** | `None` |

**`query_analysis_done` return shape:**
`set[tuple[str, str, str, int, int]]` — `(backbone, strategy, sim_metric, k, n_songs)`.

**Staleness check:**
A (backbone, strategy) pair is considered **already done** when ALL of the
following hold:

1. All keys of `METRICS` are in `done_by_pair[(backbone, strategy)]`.
2. `done_n_songs[(backbone, strategy)] > 0`.
3. `done_n_songs` ≥ the current `len(list_done_sids(backbone, strategy))`.

If the corpus has grown (more cached vectors than recorded n_songs), the pair
is re-run. Stale pairs are logged.

**Filtering:**

- `backbones` filters the `present` set to only those pairs where
  `pair[0] in backbones`.
- `strategies` filters to `pair[1] in strategies`.
- Both filters applied before the done/todo split.

**Execution order:**

1. For each backbone with work to do: `_analyze_strategy` for each strategy.
2. For each worked backbone: `_analyze_ptc_vs_ctp` if backbone has registered
   heads.
3. For each worked backbone: `_analyze_ann` with `strategy="mean"` (always,
   regardless of which strategies were in `to_do`).

**`song_ids` propagation:** Passed unchanged to `_analyze_strategy`,
`_analyze_ptc_vs_ctp`, and `_analyze_ann`.

**Early exit:** If `to_do` is empty after all filtering, logs
`"No flat analysis work remaining."` and returns.

**Precondition:** `bootstrap_nomarr()` is called before any analysis work
starts.

---

## `_truncate.py` — Truncation robustness analysis

### `_flat_rep(patches_np: FloatArray) -> FloatArray | None`

**Signature:** `_flat_rep(patches_np: FloatArray) -> FloatArray | None`

`FloatArray = npt.NDArray[np.float32]`

| | |
| --- | --- |
| **Reads** | Nothing (pure computation on input array) |
| **Writes** | Nothing |
| **Returns** | `FloatArray` shape `[embed_dim]` L2-normalized, or `None` |

**Algorithm:** `mean(patches_np, axis=0)`, then divide by L2 norm.

**Returns `None` when:** `np.linalg.norm(mean_vector) < 1e-9` (zero or near-zero
vector — pathological input).

**Invariant:** When not `None`, the returned vector has unit L2 norm.

---

### `_binned_rep(patches_np: FloatArray, bin_mode: str, std_thresh: float) -> FloatArray | None`

**Signature:**

```python
_binned_rep(
    patches_np: FloatArray,
    bin_mode: str,
    std_thresh: float,
) -> FloatArray | None
```

| | |
| --- | --- |
| **Reads** | Nothing (pure computation) |
| **Writes** | Nothing |
| **Returns** | `FloatArray` shape `[embed_dim]` L2-normalized, or `None` |

**Algorithm:**

1. L2-normalize each patch row: `patch / (norm + 1e-9)`.
2. Select `dist_fn` based on `bin_mode`:
   - `"temporal_global"` → `global_dist` (L2 distance between patch and
     running centroid)
   - anything else → `perdim_dist` (Chebyshev/per-dimension distance)
3. Call `temporal_segment(norm_patches, std_thresh, dist_fn)` → list of bin
   dicts `{"indices": [...], "outlier_count": int}`.
4. For each bin: mean-pool the indexed (normalized) patches; L2-normalize the
   bin mean; collect valid bin reps (skip if norm < 1e-9).
5. Stack all bin reps → `mean(axis=0)` → L2-normalize.

**Returns `None` when:**

- `temporal_segment` returns empty list.
- Fewer than 1 valid bin rep survived pooling.
- Final mean of bin reps has norm < 1e-9.

**Invariant:** When not `None`, returned vector has unit L2 norm.

---

### `_cosine(a: FloatArray, b: FloatArray) -> float`

**Signature:** `_cosine(a: FloatArray, b: FloatArray) -> float`

| | |
| --- | --- |
| **Reads** | Nothing |
| **Writes** | Nothing |
| **Returns** | `float` in `[-1.0, 1.0]` |

**Algorithm:** `np.dot(a, b)` — valid cosine similarity **only when both
vectors have unit norm**. Callers must guarantee unit-norm inputs.

---

### `analyze_truncation(con, *, backbones=None, song_ids=None, thresholds_by_backbone_mode=None) -> None`

**Signature:**

```python
analyze_truncation(
    con,
    *,
    backbones: list[str] | None = None,
    song_ids: frozenset[str] | None = None,
    thresholds_by_backbone_mode: dict[tuple[str, str], list[float]] | None = None,
) -> None
```

| | |
| --- | --- |
| **Reads (FS)** | `PATCHES_DIR / backbone / {song_id}.npy` for each song |
| **Reads (DB)** | `songs` table — `SELECT song_id FROM songs` (fallback sid discovery only) |
| **Writes (DB)** | `truncation_robustness_rows` via `upsert_truncation_robustness(con, backbone, bin_mode, std_thresh, flat_mean, binned_mean, delta)` |
| **Returns** | `None` |

**`song_ids` flow:**

- When `song_ids` is provided: `candidate_sids = list(song_ids)`. No FS
  discovery needed.
- When `song_ids=None`: discovers candidate sids by globbing
  `PATCHES_DIR / backbone / *.npy` (excludes files whose stem ends in `_sids`).
  Fallback: queries `songs` table for all `song_id` values if the directory is
  empty or absent.

**`thresholds_by_backbone_mode` flow:**

- `None` → uses `DIST_THRESHOLDS` for all bin modes.
- Non-`None` → `thresholds_by_backbone_mode[(backbone, bin_mode)]` for each
  combination; falls back to `DIST_THRESHOLDS` if the key is absent.

**Truncation scheme:**

```
n = len(patches)
drop_first = patches[n // 4 :]   # drops first 25% of patches
drop_last  = patches[: 3*n // 4] # drops last 25% of patches
```

Both truncated variants are compared against the full patch sequence using
`_flat_rep` and `_binned_rep`. The reported similarity for each configuration
is the **average** of the two comparisons:

```python
sim = (_cosine(full_rep, drop_first_rep) + _cosine(full_rep, drop_last_rep)) / 2.0
```

**Accumulators:**

- `flat_sims: list[float]` — one entry per valid song (flat strategy).
- `binned_sims: dict[(bin_mode, std_thresh), list[float]]` — one entry per
  valid (song, config) combination.

**Upserted values:**

- `flat_mean = mean(flat_sims)` — single value per backbone, shared across all
  binned configs.
- `binned_mean = mean(binned_sims[(bin_mode, std_thresh)])` — per
  `(bin_mode, std_thresh)` config.
- `delta = binned_mean - flat_mean`.

**Skip conditions per song:**

- Patch file `PATCHES_DIR / backbone / {song_id}.npy` does not exist → debug
  log, song skipped.
- `np.load` raises any exception → warning log, song skipped.
- `n_patches < 4` → cannot produce valid truncated halves, song skipped
  (debug log).
- Any of `full_flat`, `df_flat`, `dl_flat` is `None` (near-zero norm) → song
  skipped (no log).

**Skip conditions per (backbone) upsert:**

- `flat_sims` is empty after processing all songs → warning log, no DB writes
  for this backbone.
- `binned_sims[(bin_mode, std_thresh)]` is empty → that specific config is
  skipped (no upsert for it).

**Preconditions:** `bootstrap_nomarr()` is **not** called here; the caller is
responsible for ensuring nomarr is importable if needed.

---

## Cross-cutting invariants

1. **`song_id` is always a 12-character hash** derived from the absolute
   filesystem path via `config.song_id(path)`. It is used as the filename stem
   in every cache file and as the primary key in the `songs` DB table.

2. **All pooled vectors are stored as `float32`** regardless of the dtype
   produced by the pooling function or ONNX session output.

3. **`flat_ref/` key pattern:** `{backbone}_{strategy}` — e.g.
   `effnet_mean_upper_tri.npy`. The strategy name uses the exact key from
   `STRATEGIES` (one of `mean`, `trimmed_10`, `trimmed_20`, `median`,
   `max_norm`, `l2norm_mean`).

4. **`flat_ref/` always contains paired files:** for every
   `{backbone}_{strategy}_upper_tri.npy` there is a corresponding
   `{backbone}_{strategy}_sids.npy` of the same `n` in `sids`. The i-th
   element of `sids` corresponds to row/column `i` in the original `[n, n]`
   cosine matrix.

5. **`act[1]` is the head score used throughout `strategy_flat`.** `act[0]`
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

- **Source:** `research_config.toml` → `pooling.agg_methods`; default `["mean", "median", "max", "min"]`.
- **Validation:** each value must be in `("mean", "median", "medoid", "max", "min")`; `medoid` is explicitly forbidden at module load (`ValueError` raised).
- **Invariant:** `"medoid"` is never present; agg_mats are keyed by this list.

### `REP_TYPES: list[str]`

- **Source:** `research_config.toml` → `pooling.rep_types`; default `["mean", "median", "max", "min"]`.
- **Validation:** same allowed set as `AGG_METHODS`.
- **Invariant:** `"medoid"` is *allowed* here (it is a pool strategy, not an aggregation strategy).

### `SIM_METRICS: list[str]`

- **Source:** `research_config.toml` → `similarity.metrics`; default `["cosine", "l2"]`.

### `_EXPECTED_ROWS_PER_CONFIG: int`

- `len(REP_TYPES) × len(REP_TYPES) × len(SIM_METRICS) × len(AGG_METHODS)` — used as a completeness sentinel when logging DB write counts.

### `_BIN_POOL_STRATEGIES: dict[str, Callable[[np.ndarray], np.ndarray]]`

- Maps `"mean"`, `"median"`, `"max"`, `"min"` to their numpy axis-0 reductions over a `[n_seg, D]` float32 array. **Medoid is absent** — it is handled separately via `_build_medoid_payload`.

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
- **Returns:** `{strategy_name: payload_dict}` for every key in `_BIN_POOL_STRATEGIES` plus `"medoid"`. All payloads are for the same `indices`.
- **Invariant:** key set is fixed: `{"mean", "median", "max", "min", "medoid"}` (or fewer if `AGG_METHODS` subset is configured, but pool strategies are from `_BIN_POOL_STRATEGIES` + medoid).

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
{OUTPUT_ROOT}/cache/binned_ptc/{cache_semantics_tag()}/{backbone}/{bin_mode}/{std_thresh:.3f}/{song_id}.npz
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
{OUTPUT_ROOT}/cache/binned_ctp/{cache_semantics_tag()}/{backbone}/{head}/{bin_mode}/{std_thresh:.3f}/{song_id}.npz
```

Adds one extra `{head}` path segment relative to the PTC layout.

### `cache_path(backbone, head, bin_mode, std_thresh, song_id) -> Path`

- Pure path construction; no I/O.

### `config_dir(backbone, head, bin_mode, std_thresh) -> Path`

- Pure path construction; no I/O.

### `is_done(backbone, head, bin_mode, std_thresh, song_id) -> bool`

- **Reads:** filesystem — opens `.npz` to verify readability.
- **Writes:** may delete corrupt `.npz`.
- **Returns:** `True` iff the file exists and `np.load` succeeds without exception.

### `query_ctp_configs() -> set[tuple[str, str, str, float]]`

- **Reads:** filesystem — walks `CACHE_BASE` four levels deep.
- **Returns:** `(backbone, head, bin_mode, std_thresh)` for every non-empty config directory.

### `list_done_keys() -> set[tuple[str, str, str, str, float]]`

- **Reads:** filesystem.
- **Returns:** `(song_id, backbone, head, bin_mode, std_thresh)` for every `.npz` file.

### `save(backbone, head, bin_mode, std_thresh, song_id, bulk_vecs) -> None`

**`bulk_vecs` row schema** (16-element tuple — same as PTC but with `head` inserted at position 2):

```
(sid, backbone, head, bin_mode, std_thresh, bin_id, pool_strategy,
 vec_raw_bytes, vec_norm_bytes, weight, outlier_count,
 selected_global_idx, selected_local_idx, medoid_centrality,
 bin_start_idx, bin_end_idx)
```

- **Reads:** nothing.
- **Writes:** one `.npz` file at `cache_path(...)`.
- **npz arrays:** same pool strategy arrays as PTC cache; **no** `head_*` activation arrays (CTP cache does not store head activations).

### `load_all_reps(con, backbone, head, bin_mode, std_thresh, song_ids=None) -> tuple[list[str], list[str], list[list[dict]]]`

**Signature:**

```python
def load_all_reps(
    con,
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    song_ids: frozenset[str] | None = None,
) -> tuple[list[str], list[str], list[list[dict]]]
```

- **Reads:**
  - Filesystem: all `.npz` files in `config_dir(backbone, head, bin_mode, std_thresh)`.
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

## `cache/sim.py`

### Path layout

```
{OUTPUT_ROOT}/cache/sim/{cache_semantics_tag()}/{backbone}/{bin_mode}/{std_thresh:.3f}/{rep_a}_{rep_b}_{metric}.npz
```

### `sim_cache_path(backbone, bin_mode, std_thresh, rep_a, rep_b, metric) -> Path`

- Pure path construction; no I/O.

### `load_sim(backbone, bin_mode, std_thresh, rep_a, rep_b, metric) -> tuple[list[str], dict[str, np.ndarray]] | None`

- **Reads:** one `.npz` file.
- **Writes:** nothing.
- **Returns:** `(sids, mats)` where `mats` maps each `AGG_METHODS` name to an `[n, n] float32` matrix, or `None` on missing/corrupt file or empty mats.
- **Staleness check:** the caller in `_analyze.py` compares the returned `sids` against the current `sids` list; a mismatch means the cache is stale and must be recomputed.

### `save_sim(backbone, bin_mode, std_thresh, rep_a, rep_b, metric, sids, mats) -> None`

- **Reads:** nothing.
- **Writes:** one `.npz` (compressed) at `sim_cache_path(...)`.
- **npz arrays:** `song_ids [n] str`, `sim_{agg} [n, n] float32` per agg method.

---

## `_process.py`

### `_compute_song_stats(sid, bins_list, backbone, bin_mode, std_thresh, con) -> None`

- **Reads:** `bins_list` in memory (list of bin dicts from `load_bin_stats`).
- **Writes:** DB — upserts `binned_song_stats` row via `_db.upsert_binned_song_stats`.
- **Stats written:** `n_bins`, `n_patches`, `n_outliers`, `min_bin_size`, `max_bin_size`, `mean_bin_size`.

### `compute_agg_mats(norm_a, norm_b, bin_counts, metric, *, progress=None) -> dict[str, np.ndarray]`

**Signature:**

```python
def compute_agg_mats(
    norm_a: list[UnitTensor],   # [n_songs], each [n_bins_i, D]
    norm_b: list[UnitTensor],   # [n_songs], each [n_bins_i, D]
    bin_counts: np.ndarray,     # [n_songs] float32
    metric: str,                # "cosine" | "l2"
    *,
    progress=None,              # optional tqdm progress object
) -> dict[str, np.ndarray]     # AGG_METHODS -> [n, n] float32
```

- **Reads:** nothing external.
- **Writes:** nothing.
- **Returns:** one `[n_songs, n_songs] float32` matrix per agg method.
- **Cosine/mean fast path:** for `metric="cosine"` and `agg="mean"`, uses the batched outer-product formula `(sum_a @ sum_b.T) / outer(bin_counts, bin_counts)` — O(n²·D) but no per-pair loop.
- **All other combinations:** upper-triangular per-pair loop with batched matrix multiplication; symmetric copy applied after.
- **Diagonal** is set to `1.0` for all matrices.
- **Invariant:** `norm_a[i].data` rows are guaranteed unit-normalised by the `UnitTensor` setter before this function is called.

### `compute_retrieval_rows(agg_mats, artists, backbone, bin_mode, std_thresh, rep_a, rep_b, metric, k, n_songs, *, albums, genres, flat_upper_tri, flat_sids, current_sids, head_scores, head_names) -> tuple[list[BinnedRetrievalRow], list[tuple]]`

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
    head_scores: list[list[float]] | None = None, # from query_flat_head_labels
    head_names: list[str] | None = None,
) -> tuple[list[BinnedRetrievalRow], list[tuple]]
```

- **Reads:** `flat_upper_tri` and `flat_sids` from `.npy` files (pre-loaded by caller).
- **Writes:** nothing.
- **Returns:** `(rows, per_head_rows)` where `rows` has one `BinnedRetrievalRow` per `AGG_METHODS` entry, and `per_head_rows` has one tuple `(backbone, bin_mode, std_thresh, rep_a, rep_b, metric, agg, k, h_name, corr)` per head per agg.
- **Spearman computation:** performed only when `flat_upper_tri is not None and flat_sids is not None and current_sids is not None`. Requires `len(common) >= 2` where `common` is the intersection of `current_sids` and `flat_sids` — **this is the "no overlap" skip condition**: when fewer than 2 songs appear in both lists, `flat_binned_spearman` and `flat_binned_beneficial_reorder_rate` are set to `None` rather than skipping the entire function.
- **`head_scores` here** is `head_scores_for_retrieval` from the caller — sourced from `_db.query_flat_head_labels(con, backbone, sids)`, not from `_db.load_song_head_scores`. It is passed directly to `_compute_retrieval_metrics`.

### `_process_group(norm_a, norm_b, bin_counts, artists, rep_a, rep_b, metric, backbone, bin_mode, std_thresh, k, progress, albums, genres, head_scores, head_names, n_songs) -> tuple[list[BinnedRetrievalRow], list[tuple]]`

- **Legacy wrapper** used by `analyze_ctp`; delegates to `compute_agg_mats` + `compute_retrieval_rows`.
- `head_scores` passed as `None` from `analyze_ctp` (not meaningful for CTP pathway).
- `progress` is always passed as `None` from `analyze_ctp` — stdout/stderr are no longer tee'd to the log file, so tqdm progress objects are not threaded through the CTP pathway.

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

- **Reads:** DB — `_db.load_binned_sampling_stats(con)` — rows with `{song_id, avg_n_bins, avg_bin_div_std, artist}`.
- **Writes:** nothing.
- **Returns:** list of `song_id` strings, deterministically sampled.
- **Strategy:** each song is bucketed on three axes (bin-count quantile × bin-diversity-std quantile × artist-popularity bucket), then a proportional allocation with largest-remainder rounding fills strata. Within each stratum, a per-stratum BLAKE2b-seeded RNG shuffles before selection.
- **Invariant:** returns all rows when `sample_size <= 0` or `sample_size >= total`.

---

## `_analyze.py`

### `_blas_ctx(blas_threads: int | None) -> contextmanager`

- Returns `threadpool_limits(limits=blas_threads)` if `threadpoolctl` is available and `blas_threads is not None`, otherwise `contextlib.nullcontext()`.
- Emits a warning when `blas_threads` is requested but `threadpoolctl` is unavailable.

### `_build_ctp_rep_tensors(*, song_data: list[list[dict]], rep_types: list[str]) -> tuple[dict[str, list[RawTensor]], dict[str, list[UnitTensor]]]`

**Signature:**

```python
def _build_ctp_rep_tensors(
    *,
    song_data: list[list[dict]],  # per-song bin dicts from load_all_reps
    rep_types: list[str],
) -> tuple[
    dict[str, list[RawTensor]],    # rep -> [n_songs] each [n_bins, D]
    dict[str, list[UnitTensor]],   # rep -> [n_songs] each [n_bins, D]
]
```

- **Reads:** nothing external — operates on in-memory `song_data`.
- **Writes:** nothing.
- **Raw vectors:** uses `vec_{rep}_raw` key if present, otherwise falls back to legacy `vec_{rep}` key.
- **Norm vectors:** uses pre-stored `vec_{rep}_norm` keys when present for all bins; otherwise derives by L2-normalising the raw stack. This means norm vectors for legacy cache files are recomputed rather than loaded.
- **Alignment:** `raw_reps[rep][i]` and `norm_reps[rep][i]` always correspond to song `i` of `song_data`.

### `_compute_head_agreement(con, sids, backbone, bin_mode, std_thresh, head_scores, head_names) -> None`

**Signature:**

```python
def _compute_head_agreement(
    con,
    sids: list[str],
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    head_scores: np.ndarray,  # [n_songs, n_heads] from load_song_head_scores
    head_names: list[str],
) -> None
```

- **Reads:**
  - Filesystem (PTC cache): calls `_load_head_acts(backbone, bin_mode, std_thresh, sid)` for each `sid` in `sids`.
- **Writes:** DB — upserts `head_agreement_rows` via `_db.upsert_head_agreement` for each head with valid data.
- **head_scores source:** the `head_scores` parameter here comes from `_db.load_song_head_scores(con, backbone, sids)`, which returns flat (non-binned) per-song head scores. These are the **PTC pathway flat predictions**.
- **Computation:**
  - Flat PTC prediction: `head_scores[song, h] >= 0.5` → class 1.
  - Binned prediction: weighted-mean positive-class probability across bins (`_load_head_acts`) >= 0.5.
  - Agreement rate = fraction of songs where both agree, counting only songs with valid cache data.
- **Alignment invariant:** `sids[i]` and `head_scores[i, :]` are aligned; `head_names[h]` and column `h` of `head_scores` are aligned.

### `analyze(con, *, k, backbones, workers, blas_threads, song_ids, thresholds_by_backbone_mode) -> None`

**Signature:**

```python
def analyze(
    con,
    *,
    k: int = 10,
    backbones: list[str] | None = None,
    workers: int = 6,            # kept for signature compatibility; UNUSED
    blas_threads: int | None = None,
    song_ids: frozenset[str] | None = None,
    thresholds_by_backbone_mode: dict[tuple[str, str], list[float]] | None = None,
) -> None
```

- **Reads:**
  - DB:
    - `_db.query_binned_configs()` — set of `(backbone, bin_mode, std_thresh)` with any cache data.
    - `_db.query_binned_analysis_done(con)` — rows with `(backbone, bin_mode, thresh, rep_a, rep_b, sim_metric, agg, k, n_songs)`.
    - `_db.query_head_sim_corr_done(con)` — set of already-computed head correlation configs.
    - `_db.load_sids_and_artists(con, backbone, bin_mode, std_thresh)` — per config.
    - `_db.load_song_albums(con, sids)`, `_db.load_song_genres(con, sids)` — per config.
    - `_db.load_song_head_scores(con, backbone, sids)` → `head_scores [n_songs, n_heads]` + `head_names`.
    - `_db.query_flat_head_labels(con, backbone, sids)` → `head_scores_for_retrieval` (list of per-song head score lists).
    - `_db.retrieval_rows_exist(con, backbone, bin_mode, std_thresh, rep_a, rep_b, metric)` — sim-cache hit guard.
  - Filesystem (PTC cache): `_load_bin_stats` per song per config; `_load_norm_pair` per song per `(rep_a, rep_b)` pair when sim cache misses; `_load_head_acts` per song for head agreement.
  - Filesystem (sim cache): `_load_sim` per `(rep_a, rep_b, metric)` pair.
  - Filesystem (flat_ref): `{OUTPUT_ROOT}/flat_ref/{backbone}_{rep_a}_upper_tri.npy` and `{OUTPUT_ROOT}/flat_ref/{backbone}_{rep_a}_sids.npy` — loaded per `(rep_a, rep_b, metric)` pair.
- **Writes:**
  - Filesystem (sim cache): `_save_sim` when sim cache misses.
  - DB:
    - `_db.upsert_binned_song_stats` per song.
    - `_db.upsert_head_agreement` per head per config.
    - `_db.upsert_binned_retrieval_bulk(con, rows)` — batch write of all `BinnedRetrievalRow` objects.
    - `_db.upsert_head_sim_corr_batch` — per-head correlation rows.
- **Returns:** `None`.

#### Song ID flow (PTC pathway)

1. `sids, artists` ← `_db.load_sids_and_artists(con, backbone, bin_mode, std_thresh)` (DB + cache cross-reference).
2. Optionally filtered: `sids = [s for s, a in zip(sids, artists) if s in song_ids]`.
3. `head_scores, head_names` ← `_db.load_song_head_scores(con, backbone, sids)` — aligned to `sids` order.
4. `head_scores_for_retrieval` ← `_db.query_flat_head_labels(con, backbone, sids)` — aligned to `sids` order.
5. For each `sid` in `sids`: `_load_bin_stats(backbone, bin_mode, std_thresh, sid)` → `_compute_song_stats`.
6. For each `(rep_a, rep_b)` pair: `_load_norm_pair(backbone, bin_mode, std_thresh, sid, rep_a, rep_b)` for each `sid`.
7. `head_scores` (flat PTC) and `head_scores_for_retrieval` (flat labels) are passed separately: the former goes to `_compute_head_agreement`, the latter goes to `compute_retrieval_rows` → `_compute_retrieval_metrics`.

#### PTC/CTP song list alignment

- PTC and CTP song lists are **independent** — there is **no guarantee** that the songs in `analyze()` and `analyze_ctp()` for the same backbone and bin_mode match.
- PTC list comes from the PTC cache (`cache/binned_ptc`) + DB cross-reference.
- CTP list comes from the CTP cache (`cache/binned_ctp`) per head.

#### "No overlap" skip condition (Spearman)

- **Not a whole-function skip.** When `flat_tri_path` and `flat_sids_path` both exist, `flat_upper_tri` and `flat_sids_ref` are loaded. Then `common = [s for s in current_sids if s in flat_idx]`.
- **Skip condition:** `len(common) < 2` → `flat_binned_spearman = None`, `flat_binned_beneficial_reorder_rate = None`.
- **Cause:** the flat reference corpus was built on a different (possibly larger or earlier) song set; the current binned corpus has fewer than 2 songs in common with it.
- **Scope:** only `flat_binned_spearman` and `flat_binned_beneficial_reorder_rate` fields are None; all other retrieval metrics still computed normally.

#### `head_scores` loading path

- `_db.load_song_head_scores(con, backbone, sids)` → `(np.ndarray [n_songs, n_heads], list[str])` from the flat (non-binned) head scores stored in the DB. Used only for `_compute_head_agreement`.
- `_db.query_flat_head_labels(con, backbone, sids)` → `list[list[float]]` — separate query returning flat head label predictions aligned to `sids`. This is `head_scores_for_retrieval`, which flows into `compute_retrieval_rows(head_scores=head_scores_for_retrieval, ...)` → `_compute_retrieval_metrics`.
- Both are in-memory DB queries; no filesystem reads.

#### Flat ref file location (Spearman)

- **Upper triangle:** `{OUTPUT_ROOT}/flat_ref/{backbone}_{rep_a}_upper_tri.npy`
- **Song ID list:** `{OUTPUT_ROOT}/flat_ref/{backbone}_{rep_a}_sids.npy`
- Filenames use `rep_a` only (not `rep_b`) — the flat reference is a symmetric matrix built from a single rep type.
- Only loaded when both files exist (`Path.exists()`); missing files → Spearman fields set to `None`.

#### Staleness / head-only backfill logic

- A config is considered **done** when DB has rows for it **and** `n_songs` recorded matches the current cache size.
- `n_songs == 0` (legacy rows before tracking was added) → treated as **stale**.
- `head_only_gap`: configs that are retrieval-done but have no `head_sim_corr` rows yet. These re-enter the analysis loop but skip writing new `binned_retrieval_rows`.
- `stale = True` → forces full retrieval row recompute even on sim-cache hit.

### `analyze_ctp(con, *, k, backbones, workers, blas_threads, song_ids, thresholds_by_backbone_mode) -> None`

**Signature:**

```python
def analyze_ctp(
    con,
    *,
    k: int = 10,
    backbones: list[str] | None = None,
    workers: int = 6,
    blas_threads: int | None = None,
    song_ids: frozenset[str] | None = None,
    thresholds_by_backbone_mode: dict[tuple[str, str], list[float]] | None = None,
) -> None
```

- **Reads:**
  - DB:
    - `_query_ctp_configs()` (from `_ctp_cache`) — set of `(backbone, head, bin_mode, std_thresh)` present in the CTP filesystem cache.
    - `_db.query_ctp_analysis_done(con)` — done set.
    - `_db.load_song_albums(con, sids)`, `_db.load_song_genres(con, sids)` per config.
  - Filesystem (CTP cache): `_load_ctp_all_reps(con, backbone, head, bin_mode, std_thresh)` — loads all pool-strategy vectors for all songs for one config.
- **Writes:**
  - DB: `_db.upsert_ctp_retrieval_bulk(con, rows)` — batch write of `CTPRetrievalRow` objects.
- **Returns:** `None`.

#### Song ID flow (CTP pathway)

1. `sids, artists, song_data` ← `_load_ctp_all_reps(con, backbone, head, bin_mode, std_thresh, song_ids=song_ids)`.
   - All three are co-indexed and built from the same `.npz` scan.
2. `albums = _db.load_song_albums(con, sids)`, `genres = _db.load_song_genres(con, sids)` — aligned to `sids`.
3. `bin_counts = [len(sd) for sd in song_data]` — number of bins per song.
4. `norm_reps` built via `_build_ctp_rep_tensors(song_data=song_data, rep_types=REP_TYPES)`.
5. Parallelised over `all_groups` (up to `workers` threads) via `ThreadPoolExecutor` → `_process_group`.
   - `head_scores = None` is explicitly passed (no head-score weighting in CTP retrieval metrics).
6. Rows converted to `CTPRetrievalRow.from_binned(row, head)` — adds the head dimension.

- **Note:** `head_scores` and `head_names` are `None` throughout the CTP pathway; no flat-vs-binned agreement or head correlation is computed here.

#### PTC/CTP alignment (no-overlap detail)

- CTP iterates over `(backbone, head, bin_mode, std_thresh)` tuples; PTC iterates over `(backbone, bin_mode, std_thresh)`. The song lists for the same `(backbone, bin_mode, std_thresh)` may differ because:
  - A song may be in the PTC cache but not the CTP cache (classify not run).
  - CTP cache contents depend on which heads were used during classify.
- No code enforces list alignment; callers comparing PTC and CTP results must join on `song_id` themselves.

---

## `_embed.py`

### `embed(con, *, song_ids, force, backbones, device, thresholds_by_backbone_mode) -> None`

**Signature:**

```python
def embed(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    device: str = "cpu",
    thresholds_by_backbone_mode: dict[tuple[str, str], list[float]] | None = None,
) -> None
```

- **Reads:**
  - DB:
    - `_db.load_all_songs(con)` — all songs with `song_id`, `path`, `artist`.
    - `_db.patch_features_done(con, sid)` — per song, scalar check.
  - Filesystem:
    - Sidecar `.npy` files at `_patches_path(sid, backbone)` — backbone patch embeddings.
    - Cached calibration (DB) or computes fresh via `_calibrate`.
  - Filesystem (PTC cache): `_list_cache_done()` — scan of existing `.npz` files (skipped when `force=True`).
- **Writes:**
  - DB:
    - `patch_features` table — bulk upsert of `(song_id, patch_idx, rms, spectral_centroid, onset_strength, chroma_key)` when `librosa` is available and features not yet stored.
    - Calibration rows via `_calibrate` (upserted into DB).
  - Filesystem (PTC cache): `_cache_save(backbone, bin_mode, std_thresh, sid, vecs, heads)` — one `.npz` per `(backbone, bin_mode, std_thresh, song_id)` combination.
- **Returns:** `None`.

#### Vectors: DB vs filesystem

- **Vectors are stored to filesystem only.** The PTC cache `.npz` files are the canonical store for all bin-level vector data.
- The DB receives only **scalar data** from `embed()`: `patch_features` (acoustic scalars) and calibration stats.
- This is the documented performance fix: the old `binned_vecs` DB table was removed; `cache/binned_ptc.py` module docstring states explicitly: *"The DB is no longer used for binned vec / head data; it only stores scalar analysis results and song metadata."*

#### Per-song processing flow

1. Load sidecar: `np.load(patches_path(sid, backbone))` → `raw_all [n_patches, D]`.
2. Skip if `len(raw_all) < 2`.
3. Normalise: `unit_all = raw_all.normalize()`.
4. Extract patch features (librosa) → write to DB `patch_features`.
5. For each `(bin_mode, std_thresh)` in `missing_combos`:
   a. `temporal_segment(unit_all.data, std_thresh, dist_fn)` → segments.
   b. For each segment: `_pool_segment(raw_all, unit_all, seg["indices"])` → all pool strategies.
   c. Head inference: `_run_head_batch(session, mean_vec)` across all combos × segments in one ONNX call per head.
6. Batch by `(bin_mode, std_thresh)` combo → `_cache_save` writes one `.npz` per combo.

#### Head source for inference

- `head_source = pooled.get("mean") or pooled.get("medoid") or next(iter(pooled.values()))` — the `mean` pool strategy is preferred; `medoid` is the fallback; any strategy is the last resort.
- ONNX inference uses the raw vector (`head_source["vec_raw"].data`), **not** the normalised one.

#### Song-level filtering

1. Only songs present in `_db.load_all_songs(con)` are candidates.
2. Further filtered by `song_ids` if provided.
3. Songs without a sidecar file are skipped (counted as `skipped`).
4. Songs with `< 2` patches are skipped.

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
    agg_method: str,          # agg method for reading rows
    metric: str,              # "cosine" | "l2"
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
- **Early return** with all-zero metrics when `n < 2` valid songs remain after segmentation.
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
    agg_method: str = "median",
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
- Valid values: `"disc_artist"`, `"disc_album"`, `"disc_genre"`, `"disc_general"`, `"disc_head"`.

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
| Pairwise sim matrices (`sim_*`) | **Filesystem only** — `cache/sim/**/*.npz` |
| Scalar analysis results (`binned_retrieval_rows`, `binned_ctp_retrieval_rows`) | **DB only** |
| Song stats (`binned_song_stats`) | **DB only** |
| Head agreement (`head_agreement_rows`) | **DB only** |
| Calibration stats | **DB only** |
| Patch-level acoustic features (`patch_features`) | **DB only** |
| Head sim correlations (`head_sim_corr`) | **DB only** |

### Song ID alignment rules

- Within `analyze()`: `sids`, `artists`, `albums`, `genres`, `head_scores[i,:]`, `head_scores_for_retrieval[i]` are all aligned to the same index `i`.
- Within `analyze_ctp()`: `sids[i]`, `artists[i]`, `song_data[i]` are co-indexed by construction in `load_all_reps`.
- PTC and CTP song lists for the same `(backbone, bin_mode, std_thresh)` are **not guaranteed to match** — they come from independent cache scans.
- The `flat_ref` song set (for Spearman) is a third independent set; `analyze()` computes intersection with `current_sids` at call time and skips Spearman when `len(common) < 2`.

### `cache_semantics_tag()` and cache invalidation

- `CACHE_BASE` in `cache/binned_ptc.py` and `cache/binned_ctp.py`, and `SIM_CACHE_BASE` in `cache/sim.py`, all embed `cache_semantics_tag()` at module import time.
- Changing the tag invalidates all caches by using a different root directory; old directories are orphaned, not deleted.

### `agg_method=medoid` prohibition

- `medoid` is blocked at three levels: `_constants.py` at import time (for `AGG_METHODS`), `optimize_std_threshold` (explicit ValueError), and `compute_agg_mats` inner loop (explicit ValueError). `rep_type=medoid` is allowed and uses the observed patch row rather than a synthetic aggregate.

---

## 6. Report Sections (

eport/)

## Table of Contents

1. [_base.py — shared primitives](#_basepy--shared-primitives)
2. [_corpus.py](#_corpuspy)
3. [_efficiency.py](#_efficiencypy)
4. [_optimizer.py](#_optimizerpy)
5. [_retrieval.py](#_retrievalpy)
6. [_binned.py](#_binnedpy)
7. [_heads.py](#_headspy)
8. [_summary.py](#_summarypy)
9. [_truncation.py](#_truncationpy)
10. [V2 Section Dict Shape Reference](#v2-section-dict-shape-reference)

---

## _base.py — shared primitives

### Constants

#### `FLAT_COLUMNS` (18 items, in order)

```python
FLAT_COLUMNS = [
    "backbone",
    "strategy",
    "sim_metric",
    "k",
    "disc_general",
    "disc_artist",
    "disc_genre",
    "disc_head",
    "disc_score",
    "mean_within",
    "mean_cross",
    "map_k",
    "mrr",
    "ndcg_k",
    "recall_k",
    "recall_k_genre",
    "precision_k_genre",
    "precision_k_head_mean",
]
```

#### `BINNED_COLUMNS` (24 items, in order)

```python
BINNED_COLUMNS = [
    "backbone",
    "bin_mode",
    "std_thresh",
    "rep_a",
    "rep_b",
    "sim_metric",
    "agg_method",
    "k",
    "disc_general",
    "disc_artist",
    "disc_genre",
    "disc_head",
    "disc_score",
    "mean_within",
    "mean_cross",
    "map_k",
    "mrr",
    "ndcg_k",
    "recall_k",
    "recall_k_genre",
    "precision_k_genre",
    "precision_k_head_mean",
    "flat_binned_spearman",
    "flat_binned_beneficial_reorder_rate",
]
```

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

### `query_flat(con) -> pd.DataFrame`

**Signature:** `(con) -> pd.DataFrame`

**DB reads:**

| Table | Columns selected | Order |
| --- | --- | --- |
| `flat_results` | All `FLAT_COLUMNS` (18 columns) | `disc_score DESC` |

**Return value:** `pd.DataFrame` with columns matching `FLAT_COLUMNS`.

**Empty/stub behaviour:** Returns `empty_df(FLAT_COLUMNS)` (0-row DataFrame
with all 18 column headers) if:

- `flat_results` table does not exist, or
- the SELECT query raises any exception.

---

### `query_binned(con) -> pd.DataFrame`

**Signature:** `(con) -> pd.DataFrame`

**DB reads:**

| Table | Columns selected | Order |
| --- | --- | --- |
| `binned_results` | All `BINNED_COLUMNS` (24 columns) | `disc_score DESC` |

**Return value:** `pd.DataFrame` with columns matching `BINNED_COLUMNS`.

**Empty/stub behaviour:** Returns `empty_df(BINNED_COLUMNS)` (0-row DataFrame
with all 24 column headers) if:

- `binned_results` table does not exist, or
- the SELECT query raises any exception.

---

### `section_unified_table(flat_df, binned_df) -> dict`

**Signature:** `(flat_df: pd.DataFrame, binned_df: pd.DataFrame) -> dict`

**DataFrame inputs:**

| Argument | Expected columns (all from FLAT/BINNED_COLUMNS) |
| --- | --- |
| `flat_df` | `backbone`, `strategy`, `sim_metric`, `k`, `disc_general`, `disc_artist`, `disc_genre`, `disc_head`, `disc_score`, `mean_within`, `mean_cross`, `map_k`, `mrr`, `ndcg_k`, `recall_k`, `recall_k_genre`, `precision_k_genre`, `precision_k_head_mean` |
| `binned_df` | All flat columns above, plus `bin_mode`, `std_thresh`, `rep_a`, `rep_b`, `agg_method`, `flat_binned_spearman`, `flat_binned_beneficial_reorder_rate` |

Missing columns are filled with `None` via `reindex(fill_value=None)`.

**Processing:**

1. Flat rows get synthetic columns: `type="flat"`, `config="flat"`
2. Binned rows get `type="binned"`, `config=binned_config_label(...)`
3. Combined, sorted by `disc_genre DESC, disc_artist DESC` (`na_position="last"`)
4. Top 20 rows emitted as table
5. Per-backbone best flat vs best binned bar chart built

**Return value:** v2 section dict with `id="unified-ranking"`, `title="Unified Ranking"`.

**Populated fields when data is present:**

- `charts`: one grouped bar chart comparing best flat vs best binned disc_genre per backbone
- `tables`: one collapsible top-20 table (`id="top20"`) with columns:
  `backbone`, `config`, `type`, `disc_general`, `disc_artist`, `disc_genre`,
  `disc_head`, `disc_score`, `map_k`, `mrr`, `ndcg_k`, `recall_k`,
  `recall_k_genre`, `precision_k_genre`, `precision_k_head_mean`,
  `flat_binned_spearman`, `flat_binned_beneficial_reorder_rate`
- `panels`, `subsections`, `stats`, `warnings`, `headline`: all `[]` / `None`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| Both inputs empty | `"No retrieval results yet. Run the eval phase first."` |
| `combined_parts` empty after concat | `"No results could be ranked."` |

---

### `section_per_backbone(flat_df, binned_df) -> dict`

**Signature:** `(flat_df: pd.DataFrame, binned_df: pd.DataFrame) -> dict`

**DataFrame inputs:** Same column sets as `section_unified_table`.

**Disc column selection (applied independently to flat and binned):**
Uses `disc_general` if that column exists and has at least one non-null value;
otherwise falls back to `disc_score`.

**Per-backbone content built:**

- **Scatter chart** (`disc` vs `map_k`): flat points + top-`_TOP_N` (15) binned
  points, Pareto-optimal points marked as stars.
- **Delta bar chart** (binned Δ vs flat baseline): top-15 binned configs ranked
  by `(best_binned_disc - flat_median_disc)`, green/red coloured.
- **Top-N table** (`id=f"top_configs_{backbone}"`): top-5 flat rows + top-15
  binned rows, columns `type`, `backbone`, `config`, plus metric columns
  (`disc_col`, `map_k`, `mrr`, `ndcg_k`, `recall_k`).

**Return value:** v2 section dict with `id="per-backbone"`,
`title="Per-Backbone Analysis"`, `subsections` list where each entry is an
inline v2 dict (all 11 keys present) with `id=f"backbone-{backbone}"`.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| Both inputs produce no backbone names | `"No backbone data yet."` |

---

## _binned.py

### `section_threshold_sweep(binned_df, flat_df=None) -> dict`

**Signature:** `(binned_df: pd.DataFrame, flat_df: pd.DataFrame | None = None) -> dict`

**DataFrame inputs:**

| Argument | Required columns |
| --- | --- |
| `binned_df` | `backbone`, `bin_mode`, `std_thresh`, and disc column (`disc_general` if present+non-null, else `disc_score`) |
| `flat_df` | `backbone`, same disc column |

**Processing:**

- Optionally filters `binned_df` to `DIST_THRESHOLDS` from
  `scripts.embedding_research.helpers.binning` (silently skipped on `ImportError`).
- Groups by `(bin_mode, std_thresh)`, takes `max(disc_col)` per group.
- One line per `bin_mode`, x-axis = `std_thresh`, y-axis = best disc.
- If `flat_df` provided: adds amber dashed horizontal line at `max(flat_disc)` per backbone.

**Return value:** v2 section dict with `id="threshold-sweep"`,
`title="Threshold Sweep"`. Each backbone becomes an inline v2 subsection dict
(all 11 keys present) with `id=f"sweep-{backbone}"`.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| `binned_df.empty` | `"No binned results yet."` |

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

### `section_bin_mode_comparison(binned_df, flat_df=None) -> dict`

**Signature:** `(binned_df: pd.DataFrame, flat_df: pd.DataFrame | None = None) -> dict`

**DataFrame inputs:**

| Argument | Required columns |
| --- | --- |
| `binned_df` | `backbone`, `bin_mode`, `std_thresh`, disc column (`disc_general` if present+non-null, else `disc_score`) |
| `flat_df` | `backbone`, same disc column |

**Processing:**

- Optionally filters to `DIST_THRESHOLDS` (same as `section_threshold_sweep`).
- Requires `len(binned_df["bin_mode"].unique()) >= 2`; returns early if only one mode found.
- Groups by `(backbone, bin_mode, std_thresh)`, takes max disc.
- Per backbone: counts threshold-level wins for `temporal_global` vs `temporal_perdim`.
- If `flat_df` provided: counts how many thresholds beat flat for each mode.
- Verdict: `"temporal_global wins"` / `"temporal_perdim wins"` / `"Both equivalent"`.

**Return value:** v2 section dict with `id="bin-mode-comparison"`,
`title="Bin Mode Comparison: global vs perdim"`, per-backbone subsections.
Each subsection is an inline v2 dict (all 11 keys) with `id=f"bmc-{backbone}"`.

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| `binned_df.empty` | `"No binned results yet."` |
| `< 2` distinct bin modes | `"Only one bin mode found — need both temporal_global and temporal_perdim."` |

---

## _heads.py

### `section_head_sim_corr(con) -> dict`

**Signature:** `(con) -> dict`

**DB reads:**

| Table | Columns read | Order |
| --- | --- | --- |
| `head_sim_corr_rows` | `backbone`, `head`, `strategy`, `spearman_r` (rounded 4dp), `p_value` (rounded 4dp) | `backbone, head, strategy` |

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

**Signature:** `(con, flat_df: pd.DataFrame | None = None) -> dict`

**DB reads:**

| Table | Columns read | Required |
| --- | --- | --- |
| `ptc_ctp_rows` | `backbone`, `head`, `strategy`, `ptc_disc` (4dp), `ctp_disc` (4dp), `delta_disc` (4dp) | Yes |
| `binned_ptc_ctp_metrics` | `backbone`, `head`, `std_thresh`, `bin_mode`, `sim_align_corr` | Optional (structural alignment panel) |

**`flat_df` columns used (if provided):**

`backbone`, disc column (`disc_general` if present+non-null, else `disc_score`).
Used to draw a flat baseline reference line on per-backbone bar charts.

**Processing:**

- Aggregates `ptc_ctp_rows` by `(backbone, head)`: `median_delta`, `dominance_rate`.
- Two global heatmaps (head × backbone): median Δdisc and dominance rate.
- Per-backbone panel: grouped bar chart of median PTC/CTP disc per head + Δdisc bar.
- If `binned_ptc_ctp_metrics` exists: structural alignment heatmap
  (mean `sim_align_corr`, filtered to `_THRESH_SQL` and `_BIN_MODE_SQL`).

`_THRESH_SQL` and `_BIN_MODE_SQL` are derived at module load time from
`scripts.embedding_research.helpers.binning.DIST_THRESHOLDS` and `BIN_MODES`
(fallback to `"1.0"` / `"'temporal_global'"` on `ImportError`).

**Return value:** v2 section dict with `id="head-value"`, `title="Head Value"`.

**Populated fields:**

- `charts`: `[median_delta_heatmap, dominance_rate_heatmap]`
- `panels`: `[per_backbone_breakdown_panel]` + optional `[structural_alignment_panel]`
- `description`, `stats`, `tables`, `subsections`, `warnings`, `headline`: all `[]` / `None`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| `ptc_ctp_rows` table missing | `"Run the classify and analyze phases to populate this section."` |
| Query exception | `f"Query error: {exc}"` |
| Table exists but empty | `"No head comparison data yet."` |

---

## _summary.py

### `_dominance_rate(binned_df, flat_df, backbone, col='disc_genre') -> tuple[float, float, float]`

**Signature:** `(binned_df, flat_df, backbone, col='disc_genre') -> tuple[float, float, float]`

Private helper. Returns `(dominance_rate, flat_best, binned_best)` where:

- `dominance_rate` = fraction of unique binned configs (deduplicated by
  `_BINNED_CONFIG_COLS`) whose `col` score exceeds `flat_best`.
- `flat_best` = max of `col` in flat rows for this backbone.
- `binned_best` = max of `col` in deduplicated binned rows.

**DataFrame columns required:**

| Argument | Columns |
| --- | --- |
| `binned_df` | `backbone`, `bin_mode`, `std_thresh`, `rep_a`, `rep_b`, `agg_method`, `{col}` |
| `flat_df` | `backbone`, `{col}` |

`_BINNED_CONFIG_COLS = ["bin_mode", "std_thresh", "rep_a", "rep_b", "agg_method"]`

**Returns `(0.0, 0.0, 0.0)` if:**

- `binned_df` is empty or missing any `_BINNED_CONFIG_COLS`
- `flat_df` or `binned_df` subsets are empty after filtering for `backbone`
- Either `col` is absent from either input
- Either score series is all-NaN after `dropna()`

---

### `section_summary(flat_df, binned_df) -> dict`

**Signature:** `(flat_df: pd.DataFrame, binned_df: pd.DataFrame) -> dict`

**DataFrame inputs:**

| Argument | Required columns | Optional columns |
| --- | --- | --- |
| `flat_df` | `backbone`, `disc_genre` | `n_songs` |
| `binned_df` | `backbone`, `bin_mode`, `std_thresh`, `rep_a`, `rep_b`, `agg_method`, `disc_genre` | `n_songs` |

**Processing:**

1. Collects all backbone names from both inputs.
2. For each backbone, checks for `n_songs` mismatch between flat and binned
   (emits a `"warning"` dict if mismatch found).
3. Calls `_dominance_rate` to get `(dominance_rate, flat_best, binned_best)`.
4. Computes `flat_composite_tuning_sens = median(disc_genre) - 0.5 * IQR(disc_genre)` for flat.
5. Computes same composite for binned (using deduplicated config rows).
6. Selects `best_binned_config` as `binned_config_label(...)` of the row with max `disc_genre`.
7. Assigns per-backbone `verdict`:
   - `dominance_rate > 0.66` → `"consistently better"`
   - `dominance_rate > 0.33` → `"sometimes better"`
   - otherwise → `"not better"`
8. Sets top-level `headline` dict based on best verdict across all backbones.

**Return value:** v2 section dict with `id="summary"`, `title="Summary"`.

**Populated fields:**

- `tables`: one table (`id="backbone_summary"`) with per-row columns:
  `backbone`, `dominance_rate`, `verdict`, `flat_best_disc_genre`,
  `binned_best_disc_genre`, `flat_composite_tuning_sens`,
  `binned_composite_tuning_sens`, `best_binned_config`
- `warnings`: list of `n_songs`-mismatch warning dicts (may be `[]`)
- `headline`: `{color: str, icon: str, text: str}`
  - `#22c55e` / `"✓"` if any backbone is `"consistently better"`
  - `#f59e0b` / `"⚠"` if any backbone is `"sometimes better"`
  - `#f87171` / `"✕"` otherwise
- `stats`, `charts`, `panels`, `subsections`: all `[]`
- `empty_message`: `""`

**Empty/stub behaviour:**

| Condition | `empty_message` |
| --- | --- |
| Both inputs produce no backbone names | `"No retrieval data yet. Run the eval phase first."` |

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
`section_head_sim_corr`) carry all 11 keys. The exception is
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

## 7. Pipeline Orchestration (

un.py, classify.py, mbed.py, config.py)

## 1. Pipeline Phases

All phases are registered in `run.py`'s `_PHASES` ordered dict and executed by `main()` in the
order shown. Each phase receives the shared `cfg` dict built from `research_config.toml`.

```
ingest → optimize → embed → classify → analyze → truncate → report
```

### Phase 1 — `ingest`

**Entry point:** `strategy_meta.ingest(con, limit, force)`

**What it does:** Walks `MEDIA_ROOT` for all audio files (stratified to `limit` songs), extracts
full metadata via `path_to_meta` (nomarr tag normaliser), and writes each song to the `songs`
table with columns `(song_id, path, artist, album, title, genre)`.

**DB state required:** `songs` table must exist (created by `db.ensure_schema`).

**DB state produced:** `songs` table populated. Every subsequent phase reads `song_id` and `path`
from this table (binned sub-phases) or derives them from `discover_audio()` (flat sub-phases).

---

### Phase 2 — `optimize` (optional)

**Entry point:** `run.py::_optimize_phase(con, cfg)`

**Enabled by:** `cfg["optimize_threshold"]` (from `[optimization] enabled`). When `false`, this
phase logs a skip message and returns immediately.

**What it does:** For every `(backbone, bin_mode)` pair:

1. Checks whether `{OUTPUT_ROOT}/optimizer/threshold_curve_{backbone}_{bin_mode}.csv` already
   exists on disk. If it does **and** `cfg["force"]` is `false`, reads the best threshold from
   the CSV (highest `objective_total` row) via `_load_optimizer_result_from_csv` and skips the
   grid search entirely.
2. If no cached CSV is found (or `cfg["force"]` is `true`), calls
   `strategy_binned._optimize.optimize_std_threshold`, which grid-searches (or runs GSS) over the
   `search_range` to find the distance threshold that maximises the chosen disc metric on a
   `subsample_size` sample of songs. Writes the full per-threshold diagnostics table to the CSV.

**DB state required:** `songs` table populated and the binned embed cache must contain enough
data for the optimizer to evaluate; in practice the optimizer is designed to run after ingest but
before a full embed so it can steer the threshold grid.

**DB state produced:** Nothing written to the DB. The optimal threshold for each
`(backbone, bin_mode)` is stored **in memory only** in `cfg["thresholds_by_backbone_mode"]`,
a `dict[tuple[str,str], list[float]]`. Every subsequent phase reads this key from `cfg`.

The final threshold plan merges the optimizer's optimum with any explicit `opt_grid` values so
the grid always contains at least the grid thresholds plus the discovered optimum.

**Filesystem reads/writes:**
- Reads: `{OUTPUT_ROOT}/optimizer/threshold_curve_{backbone}_{bin_mode}.csv` (skip-guard check)
- Writes: same path (only when re-running or no cached result exists)

---

### Phase 3 — `embed`

**Entry point:** `run.py::_embed(con, cfg)` — two sequential sub-phases.

#### Sub-phase 3a — flat embed

**Entry point:** `strategy_flat._embed.embed(con, song_ids, force, backbones, device)`

**What it does:**

1. For each backbone × audio file: runs the backbone ONNX model on mel-spectrogram patches to
   produce a `[n_patches, embed_dim]` float32 array.
2. Saves the raw patches as a **sidecar** file:  
   `{PATCHES_DIR}/{song_id}.{backbone}.npy`  
   (skipped if file already exists and `force=False`).
3. Applies every pooling strategy in `STRATEGIES` (mean, median, medoid, max, min) to produce a
   `[embed_dim]` flat vector per strategy.
4. Saves each pooled vector to the **flat filesystem cache**:  
   `{OUTPUT_ROOT}/cache/{backbone}/{strategy}/flat/{song_id}.npy`

**DB state required:** `songs` table populated (only for registering new songs mid-run; flat
embed does *not* read songs from DB for its work list — it uses `discover_audio()` directly).

**DB state produced:** Nothing written to DuckDB. All outputs are `.npy` files on disk.

#### Sub-phase 3b — binned embed

**Entry point:** `strategy_binned._embed.embed(con, song_ids, force, backbones, device, thresholds_by_backbone_mode)`

**What it does:**

1. Reads song list from `db.load_all_songs(con)` filtered to `song_ids`.
2. For each song × backbone: loads the raw sidecar `{sid}.{backbone}.npy`, runs
   `temporal_segment` for each `(bin_mode, std_thresh)` combo, pools each segment four ways
   (mean, median, medoid, min/max), runs all head ONNX models on the segment mean vectors.
3. Writes per-song NPZ files to the **binned ptc cache**:  
   `{OUTPUT_ROOT}/cache/binned_ptc/{cache_semantics_tag()}/{backbone}/{bin_mode}/{threshold_key}/{song_id}.npz`  
   Each NPZ stores: pooled vec arrays per strategy, head activation arrays, weights,
   outlier counts, indices.
4. Inserts per-patch acoustic features (`rms`, `spectral_centroid`, `onset_strength`,
   `chroma_key`) into the `patch_features` DB table (once per song, guarded by
   `db.patch_features_done`).

**DB state required:** `songs` table populated.

**DB state produced:**

- `patch_features` table rows for each song × patch index.
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

**Entry point:** `classify.run_binned(con, song_ids, force, backbones, heads, device, thresholds_by_backbone_mode)`

**What it does:** For each `(song, backbone, head, bin_mode, std_thresh)` combo:

- Loads the raw sidecar patches.
- Runs `temporal_segment` to get segment boundaries.
- Runs the ONNX head on patches, computes per-segment mean activation → `binned_classify_ctp`.
- Pools the embedding patches at the same segment indices → `binned_ctp_vecs` (written as NPZ
  files via `_ctp_cache.save`).

**DB state required:** Sidecar `.npy` files must exist on disk.

**DB state produced:**

- `binned_classify_ctp` table rows.
- `binned_ctp_vecs` NPZ files in `{OUTPUT_ROOT}/cache/binned_ctp/`.

---

### Phase 5 — `analyze`

**Entry point:** `run.py::_analyze(con, cfg)` — four sequential sub-phases.

1. **flat analyze** — `strategy_flat.analyze`: builds per-song retrieval lists from flat pooled
   vectors and writes results to the `flat_retrieval` / `flat_disc` tables.
2. **binned analyze (PTC)** — `strategy_binned.analyze`: same for binned pooled vectors from the
   NPZ cache, writes to `binned_retrieval` / `binned_disc` tables.
3. **PTC vs CTP metrics** — `classify.compute_metrics`: compares PTC scores (read from NPZ head
   activations via `cache.binned_ptc.load_head_acts`) against CTP scores (from `binned_classify_ctp`
   table), writes Pearson correlation + divergence metrics to `ptc_ctp_metrics`.
4. **CTP analyze** — `strategy_binned.analyze_ctp`: runs retrieval analysis on the CTP-derived
   embedding pools, writes to `ctp_retrieval` / `ctp_disc` tables.

**DB state required:** Tables from phases 3 and 4.

**DB state produced:** Retrieval, disc, and metrics tables.

---

### Phase 6 — `truncate`

**Entry point:** `run.py::_truncate(con, cfg)`

**What it does:** Truncation robustness analysis — tests how retrieval quality degrades as
embedding dimensions are progressively removed. Writes results to the `truncation` table.

**Gating:** Skipped entirely when `--skip-truncation` CLI flag is passed (sets
`cfg["skip_truncation"] = True`).

**DB state required:** Flat filesystem cache and retrieval tables from phase 5.

**DB state produced:** `truncation` table rows.

---

### Phase 7 — `report`

**Entry point:** `run.py::_report(con, cfg)` → `report.run(con)`

**What it does:** Reads all result tables and generates an HTML report under `{REPORT_DIR}/`.

**DB state required:** All prior tables populated (report gracefully degrades to empty-message
sections when a table is absent or empty).

**DB state produced:** Report files on disk. No DB writes.

---

## 2. Embed Skip / Existence Check

> **Note:** There is no `embed.py` at the package root. Embedding is split across
> `strategy_flat/_embed.py` and `strategy_binned/_embed.py`, both invoked by
> `run.py::_embed()`.

### Flat embed (`strategy_flat._embed`)

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

### Binned embed (`strategy_binned._embed`)

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

**Bulk pre-scan:**

```python
if not force:
    binned_done_raw = query_binned_classify_done(con)
    done_combos_by_key = {}  # (sid, backbone, head) → set[(bin_mode, std_thresh)]
    for sid_d, bb_d, head_d, bm_d, st_d, _bin_id in binned_done_raw:
        done_combos_by_key.setdefault((sid_d, bb_d, head_d), set()).add((bm_d, float(st_d)))
else:
    done_combos_by_key = {}
```

`query_binned_classify_done(con)` reads distinct `(sid, backbone, head_name, bin_mode, std_thresh, bin_id)`
from the `binned_classify_ctp` table.

**Per-song work dict:**

```python
for head_name in head_sessions:
    done_c = done_combos_by_key.get((sid, backbone_name, head_name), set())
    missing = all_combos_binned - done_c if not force else all_combos_binned
    if missing:
        heads_missing[head_name] = missing
if heads_missing:
    work[p] = heads_missing
```

Only `(bin_mode, std_thresh)` combos not yet in `binned_classify_ctp` are reprocessed. If the
sidecar `.npy` does not exist the song is skipped (no error).

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
| `backbones` | `list[str]` \| absent | `null` (= all) | Restrict phases to named backbones. When absent/empty all keys in `BACKBONES` are used. |
| `heads` | `list[str]` \| absent | `null` (= all) | Restrict classify/analyze phases to named heads. When absent/empty all discovered heads are used. |

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
| `rep_types` | `list[str]` \| absent | `null` (= all cached) | Pooling strategies passed as `cfg["flat_strategies"]` to `strategy_flat.analyze`. Options: `mean`, `median`, `medoid`, `max`, `min`. |
| `agg_methods` | `list[str]` | — | How the NxM per-bin similarity matrix is collapsed to a song-pair score. Used in the binned analysis phase. Options: `mean`, `median`, `max`, `min`. (`medoid` is intentionally rejected.) |

---

### `[similarity]` section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `metrics` | `list[str]` | — | Distance/similarity metrics for retrieval scoring. Currently only `"cosine"` is used in the analysis. |

---

### `[analysis]` section

| Key | Type | Default | Controls |
| --- | --- | --- | --- |
| `k` | `int` | `10` | Retrieval list depth (top-k). Passed to `flat_analyze`, `binned_analyze`, and `ctp_analyze`. |
| `workers` | `int` | `4` | `ThreadPoolExecutor` worker count for the analysis phase (parallel backbone processing). |
| `blas_threads` | `int` | `1` | BLAS thread cap via `threadpoolctl`. `0` = no cap. Passed as `None` when zero. |

---

### `[optimization]` section

| Key | Type | Default (code) | Controls |
| --- | --- | --- | --- |
| `enabled` | `bool` | `false` | Activate the optimize phase. When `false`, `_optimize_phase` is a no-op. |
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
| `agg_method` | `str` | `"median"` | Aggregation method used during optimizer evaluation. Stored as `cfg["opt_agg_method"]`. |
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

After building `song_ids`, `main()` also calls:

```python
db.purge_stale_retrieval_rows(con, len(cfg["song_ids"]))
```

which removes retrieval rows that belong to a prior run with a different working-set size.

### Propagation to phases

Every phase function receives `cfg["song_ids"]` as `frozenset[str] | None`.

| Phase / sub-phase | How `song_ids` is used |
| --- | --- |
| `ingest` | Passed as `limit` to `discover_audio` (not as a filter; `limit` controls list size; `discover_audio` returns the same stratified list) |
| `optimize` | Passed directly to `optimize_std_threshold` as a subsample scope |
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
