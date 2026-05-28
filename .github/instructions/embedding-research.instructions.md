---
name: Embedding Research Pipeline
description: Auto-applied when working with scripts/embedding_research/ - rules, column contracts, and change protocol
applyTo: scripts/embedding_research/**
---

# Embedding Research Pipeline

## Purpose and Research Goal

This pipeline exists to find a **replacement for two things nomarr currently does**:

1. **Similarity search** — nomarr uses a single mean-pooled, L2-normalised embedding vector per song with cosine distance. This is the `"mean"` flat strategy. It is the baseline everything must be compared against.
2. **Tag authoring** — nomarr runs a head classifier on the single mean-pooled embedding (PTC pathway). We are testing whether better pooling strategies or segment-aware approaches produce higher-quality tag predictions.

**All research questions must be framed as: "does this beat flat/mean/cosine?"** If a strategy cannot demonstrably improve on the baseline, it is not a candidate for adoption.

---

## Vocabulary

### Backbones
ONNX audio feature extractors. Currently: `effnet`, `musicnn`. Each produces a sequence of patch vectors (typically 128-D or 1280-D) for a given audio file.

### Flat strategies
Each patch sequence is pooled into a **single embedding vector** per song. Available strategies: `mean`, `trimmed_10`, `trimmed_20`, `median`, `max_norm`, `l2norm_mean`. The single vector is L2-normalised before storage and similarity computation.

- **`mean` is nomarr's production strategy.** It is the mandatory comparison baseline.
- Flat strategies are indexed in `strategy_flat/`. Metrics land in `retrieval_rows`.

### Binned (PTC) strategies
The patch sequence is **temporally segmented** into bins using an L2-distance threshold. Each bin is independently pooled into a representative vector (`mean`, `median`, `medoid`, `max`, `min`). Similarity between two songs is the aggregated score across all bin-vs-bin comparisons.

- Segmentation algorithm: `temporal_global` (one shared threshold) or `temporal_perdim` (per-dimension Chebyshev). Configured in `research_config.toml → [binning]`.
- Metrics land in `binned_retrieval_rows`.

### PTC — Pool-Then-Classify
The **standard** head inference pathway:
1. Pool all patches into one vector (using the pooling strategy).
2. Run the ONNX head on that single vector.
3. Result: one activation `[p0, p1]` per song per head.

This is what nomarr does today for tag authoring. PTC scores are stored in `head_results` with `pathway = 'ptc'`.

### CTP — Classify-Then-Pool
The **experimental** pathway:
1. Run the ONNX head on every individual patch to get `[n_patches, 2]` activations.
2. Pool those per-patch activations into one vector using the same pooling strategy.
3. Result: one pooled activation `[p0, p1]` per song per head.

CTP scores are stored in `head_results` with `pathway = 'ctp'`. The `ptc_ctp_rows` table records which pathway produces better discriminability per `(backbone, head, strategy)`. The `binned_ptc_ctp_metrics` table records alignment between PTC and CTP scoring on binned segments.

CTP is **experimental** — if it does not outperform PTC on discriminability, it is not worth the computational cost.

### Heads
Binary ONNX classifiers attached to a backbone. Each head takes a backbone embedding vector and returns `[p_class0, p_class1]`. Examples: `mood_happy`, `genre_electronic`, `tonal_atonal`. `act[1]` is always the positive-class score. Never use `act[0]`.

---

## What to Compare Against

| Research question | Baseline |
|---|---|
| Better sim search? | `retrieval_rows` where `strategy="mean"` and `sim_metric="cosine"` |
| Better pooling strategy? | Same — `mean/cosine` is the floor |
| Binned vs flat? | `binned_retrieval_rows` vs `retrieval_rows` for the same backbone |
| CTP vs PTC? | `ptc_ctp_rows.ptc_disc` vs `ctp_disc` per head |
| Binned segmentation threshold? | Row with same backbone/rep/metric at the numerically adjacent threshold |

A strategy is a **candidate replacement** only if it beats `mean/cosine` on `disc_general` **and** maintains comparable `map_k`. `disc_score` alone is insufficient — `disc_general` incorporates artist, genre, and head discriminability and is the single summary metric used for ranking.

---

## Metrics

### Primary (used for candidate ranking)

| Metric | Meaning | Useful? |
|---|---|---|
| `disc_general` | Mean of non-zero `(disc_artist, disc_genre, disc_head)` | **Primary ranking metric** |
| `disc_artist` | Pairwise sim gap: same-artist pairs vs cross-artist | Required |
| `disc_genre` | Pairwise sim gap: same-genre pairs vs cross-genre | Required |
| `disc_head` | Head discriminability via 10-bin histogram overlap | Required |
| `map_k` | Mean Average Precision at k | Required |
| `ndcg_k` | NDCG at k | Secondary |
| `precision_k_genre` | Precision@k for genre-matching | Secondary |
| `precision_k_head_mean` | Precision@k averaged over all heads | Secondary |

### Present but advisory

| Metric | Notes |
|---|---|
| `disc_score` | Raw pairwise sim gap (artist only, not genre/head). Less informative than `disc_general`. |
| `mrr` | Mean Reciprocal Rank. Useful for top-1 analysis, not primary. |
| `recall_k` | Recall@k. Use alongside MAP, not standalone. |
| `mean_within` / `mean_cross` | Raw within-group and cross-group cosine means. Useful for diagnosing collapse. |
| `per_head_corr` | Spearman correlation between pairwise cosine sim and mean head-score difference. Measures whether embedding geometry tracks head predictions. |
| `flat_binned_spearman` | Rank correlation between flat and binned similarity rankings for same song pairs. High value = binned adds no ordering information. |
| `flat_binned_beneficial_reorder_rate` | Fraction of pairs where binned ranking moves a same-artist pair higher than flat did. Positive = useful reordering. |

### Forbidden / do not add

| Column | Reason |
|---|---|
| `disc_album` | Removed from schema. Does not exist. |
| `recall_k_album` | Removed from schema. Does not exist. |
| `bin_div_std` | Removed — mean pairwise bin distance has no semantic quality signal (see FINDINGS.md). |

---

Read [CONTRACTS.md](../../scripts/embedding_research/CONTRACTS.md) for the full API reference before any edit. Run the test baseline before and after every change.

---

## Before Any Edit

```
python -m pytest scripts/embedding_research/tests/ -x -q
```

All tests must be green before you start. If they are not, fix that first.

Read the contracts section for **every file you will touch**:

| Contract section | Covers |
| --- | --- |
| Section 1 | `db/_schema.py`, `db/_types.py`, `db/__init__.py`, all 20 DuckDB table schemas |
| Section 2 | `db/flat.py` — upsert/load functions, SQL column lists, conflict clauses |
| Section 3 | `similarity.py` — `compute_retrieval_metrics()` return dict, `ANNIndex` |
| Section 4 | `strategy_flat/_cache.py`, `_embed.py`, `_analyze.py`, `_truncate.py` |
| Section 5 | `strategy_binned/` — all 13 modules |
| Section 6 | `report/` — section functions, v2 section dict shape, `_base.py` constants |
| Section 7 | `run.py` pipeline phases, embed/classify skip logic, ID flow |

---

## Hard Invariants

### `compute_retrieval_metrics()` — all 15 return keys

Every key is always present. Missing optional data degrades to `0.0` or `{}`.

```
map_{k}  mrr  ndcg_{k}  recall_{k}  recall_{k}_genre
precision_k_genre  precision_k_head_mean
disc_artist  disc_score  disc_genre  disc_head  disc_general
mean_within  mean_cross  per_head_corr
```

`disc_album` does **not** exist. Never SELECT or upsert it.

### `disc_general` — intentional zero-exclusion

Computed as mean of whichever components in `(disc_artist, disc_genre, disc_head)` are **non-zero**. A WARNING is logged for each excluded zero component. Do not change this to include zeroes.

### `act[1]` is always the head score

`act = [p0, p1]`. Use `act[1]` for discriminability, binning, and `disc_head`. Never `act[0]`.

### `bin_idx` formula — exact, do not alter

```python
bin_idx = np.minimum((h_scores * 10).astype(np.int32), 9)
```

10 bins `{0..9}`. Score `1.0` maps to bin 9.

### `head_scores` shape into `compute_retrieval_metrics()`

Accepted: `(n_heads, n_songs)` or `(n_songs, n_heads)` — auto-transposed. When square, first branch wins.

---

## Cross-File Change Protocol

Adding or removing a metric from `compute_retrieval_metrics()` requires **all five** of these to be updated atomically:

1. `db/_types.py` — dataclass field
2. `db/_schema.py` — DDL column
3. `db/flat.py` — `upsert_retrieval` INSERT + `load_retrieval_flat` SELECT + guard
4. `db/binned.py` — `upsert_binned_retrieval` INSERT + `load_retrieval_binned` SELECT + guard
5. `report/_base.py` — `FLAT_COLUMNS` and/or `BINNED_COLUMNS`

For any rename, grep these 7 files before committing:

```
db/_schema.py  db/_types.py  db/flat.py  db/binned.py
report/_base.py  similarity.py  run.py
```

### `FLAT_COLUMNS` — 18 items, in order

```python
["backbone", "strategy", "sim_metric", "k",
 "disc_general", "disc_artist", "disc_genre", "disc_head", "disc_score",
 "mean_within", "mean_cross",
 "map_k", "mrr", "ndcg_k", "recall_k", "recall_k_genre",
 "precision_k_genre", "precision_k_head_mean"]
```

### `BINNED_COLUMNS` — 24 items, in order

```python
["backbone", "bin_mode", "std_thresh", "rep_a", "rep_b", "sim_metric", "agg_method", "k",
 "disc_general", "disc_artist", "disc_genre", "disc_head", "disc_score",
 "mean_within", "mean_cross",
 "map_k", "mrr", "ndcg_k", "recall_k", "recall_k_genre",
 "precision_k_genre", "precision_k_head_mean",
 "flat_binned_spearman", "flat_binned_beneficial_reorder_rate"]
```

---

## Storage Architecture

**DuckDB stores metrics and scalar summaries only.** Raw vectors, pooled embedding tensors, and head activation streams are **never** written to DuckDB. They live on the filesystem.

**Canonical cache layout:** `{OUTPUT_ROOT}/cache/{backbone}/{strategy}/{threshold}/{song_id}`

| Data type | `{strategy}` | `{threshold}` | `{song_id}` |
|---|---|---|---|
| Flat pooled vec | `{pool_strategy}` (e.g. `mean`) | `flat` | `{id}.npy` |
| Flat PTC head act | `heads/{head_name}/{pool_strategy}` | `ptc` | `{id}.npy` |
| Flat CTP head act | `heads/{head_name}/{pool_strategy}` | `ctp` | `{id}.npy` |
| Binned PTC vec | `{bin_mode}` (e.g. `temporal_global`) | `{thresh:.3f}` | `{id}/` (directory) |
| Binned CTP head act | `heads/{head_name}/{bin_mode}` | `{thresh:.3f}` | `{id}.npy` |

**Existence check = file/directory exists.** Never query the DB to check whether vector or head data exists. Use `Path(...).exists()`.

**One file per song.** Do not aggregate multiple songs into a single file. Load multiple files when needed.

**Module owners:**
- Flat pooled vecs → `strategy_flat._cache` (paths: `cache/{backbone}/{pool_strategy}/flat/{id}.npy`)
- Flat head acts → `cache.flat_heads` (paths: `cache/{backbone}/heads/{head}/{strat}/{pathway}/{id}.npy`)
- Binned PTC vecs → `strategy_binned._cache` (legacy `binned_ptc_cache/`; migration pending)
- Binned CTP acts → DB violation — `binned_classify_ctp` table; migration to `cache/` pending

**Known DB violations (do not add more):**
- `binned_classify_ctp` — stores CTP per-bin activations as BLOBs; pending migration to filesystem
- `binned_ctp_vecs` — stores CTP per-bin vectors as BLOBs; pending migration to filesystem

**Legacy paths:** `flat_cache/` is the old flat-vec root. Run `strategy_flat._cache.migrate_flat_cache()` to move existing data to `cache/{backbone}/{strategy}/flat/`. Code reads both paths transparently during transition.

---

## DB Layer Rules

- Never SELECT a column not in the schema. Verify in CONTRACTS.md Section 1 before adding any SELECT.
- `as_tuple()` order in `db/_types.py` must exactly match the INSERT column order in the upsert function. Divergence silently inserts values into wrong columns.
- ALTER TABLE guards (`ADD COLUMN IF NOT EXISTS`) are required only for columns added after the baseline schema. Columns already in `ensure_schema()` do not need guards.
- New columns require: DDL in `_schema.py` + guard in both `load_retrieval_flat` and `load_retrieval_binned`.

---

## Report Section Rules

Every `section_*` function must return a v2 dict with all 11 keys:

```
id  title  description  stats  charts  tables  panels
subsections  warnings  headline  empty_message
```

- `empty_message` is a non-empty string when no data is present; `None` or `""` when data exists.
- Never return early with a partial dict — callers check all 11 keys.
- Pass values to `make_table` unformatted; `make_table` calls `fmt()` internally.
- `disc_score_warning` must return `[]` on exception — never raise from it.

---

## Cache Rules

**Flat vecs:** `{OUTPUT_ROOT}/cache/{backbone}/{strategy}/flat/{song_id}.npy`
- Not in DuckDB. Never add a DB write for pooled vectors.
- `save_pooled` always casts to `float32`.
- `is_done` may delete corrupt files as a side effect.
- Legacy root `flat_cache/` is still supported for reads; call `migrate_flat_cache()` to upgrade.

**Flat head acts:** `{OUTPUT_ROOT}/cache/{backbone}/heads/{head_name}/{strategy}/{pathway}/{song_id}.npy`
- Not in DuckDB. `head_results` table is effectively dead — shims in `db/flat.py` redirect to `cache.flat_heads`.
- Done signal: both `ptc/` and `ctp/` files exist → `cache.flat_heads.is_done()`.

**Binned PTC:** `{OUTPUT_ROOT}/binned_ptc_cache/{cache_semantics_tag()}/{backbone}/{bin_mode}/{threshold:.3f}/{song_id}.npz`
- Bump `cache_semantics_tag()` when algorithm semantics change.
- `medoid` is excluded from `AGG_METHODS` — handled by `_build_medoid_payload`, not `_BIN_POOL_STRATEGIES`.
- `load_norm_pair` returns unit-normalised tensors. Do not pass raw tensors where unit tensors are expected.

**Binned CTP (DB violation — pending migration):** `binned_classify_ctp` and `binned_ctp_vecs` tables in DuckDB.
- These are known violations of the storage boundary rule.
- Do not add more code that writes vectors or activations to these tables.
- Target migration: `cache/{backbone}/heads/{head_name}/{bin_mode}/{threshold:.3f}/{song_id}.npy`

---

## Never Do

- Fix a crash in one layer without checking all connected layers. A metric change touches at minimum 5 files.
- Read a partial file range and assume the rest is clean. Read the whole relevant section.
- Remove a metric because it looks unused. Check `FLAT_COLUMNS`, `BINNED_COLUMNS`, and all report sections first.
- Return a plausible-looking value derived from wrong data. Log a WARNING and use `0.0` / `None` explicitly.
- SELECT `disc_album` or `recall_k_album`. These columns do not exist.
- Use `act[0]` for head scores. Always `act[1]`.
- Alter the `bin_idx` formula.
- Add `medoid` to `AGG_METHODS`. The validator raises `ValueError` on startup.
- Change `disc_general` to include zero-valued components. The WARNING is intentional.

---

## After Every Edit

```
python -m pytest scripts/embedding_research/tests/ -x -q
```

All tests must pass before submitting. No exceptions.
