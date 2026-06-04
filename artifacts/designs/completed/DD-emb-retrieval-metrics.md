# Design: Embedding Research — Retrieval-Primary Metrics

**Status:** Draft  
**Date:** 2026-05-28  
**Author:** Lucian Hardy  
**Slug:** `emb-retrieval-metrics`

---

## Overview

The v2 embedding research pipeline (DD-emb-research-v2) added raw sim-pair storage, stratification, disc_head window-based scoring, and per-song metric persistence. Those four changes are complete. This document describes the fifth change: replacing disc metrics as the primary ranking signal with proper retrieval metrics (MAP@k, MRR, NDCG@k, Recall@k) computed per label type (artist, genre, head), plus the structural diagnostic metrics (mean/var within/cross per label type) that give confidence weighting to the retrieval signal.

Additionally, a pre-existing naming bug (`map_10` stored in DB vs `map_k` referenced in report) is fixed in this change because it silently nullifies all existing retrieval metrics in the current report output.

---

## Problem Statement

**1. Wrong primary signal.** The current pipeline sorts and ranks embedding strategies by `disc_general` — the average of `disc_artist`, `disc_genre`, and `disc_head`. Discrimination measures embedding space structure (within-group mean similarity minus cross-group mean similarity). This is a proxy. It does not answer the research question: *does similarity search return relevant results?* A strategy can have high disc and mediocre retrieval precision, or vice versa.

**2. Naming bug breaks MAP@k entirely.** `compute_retrieval_metrics` returns keys like `"map_10"` (f-string: `f"map_{k}"`). The DB stores `metric="map_10"`. The PIVOT query in the report produces a column named `map_10`. The report code references `"map_k"` — a literal that never exists. All MAP@k, NDCG@k, and Recall@k columns in every report are silently NaN. The disc scatter charts vs MAP@k all have y=0. The system appears to measure retrieval but does not.

**3. Retrieval computed for artist labels only.** Genre recall (`recall_k_genre`) exists, but there is no MAP@k or NDCG@k for genre. Head retrieval metrics do not exist at all. There is no composite across label types.

**4. Space structure diagnostics are incomplete.** `mean_within` and `mean_cross` are computed artist-only. Variance of within/cross similarities (which bounds the confidence of the MAP interpretation) does not exist for any label type.

---

## Requirements

1. **Fix naming bug** — rename all k-indexed metric keys to static names (`map_k_artist`, `ndcg_k_artist`, `recall_k_artist`) so the k value is captured in the DB `k` column, not in the metric name.
2. **MAP@k, MRR, NDCG@k, Recall@k per label type** — computed for artist, genre, and head label definitions; stored as `*_artist`, `*_genre`, `*_head` variants.
3. **`map_k_general` composite** — mean of non-null `{map_k_artist, map_k_genre, map_k_head}`; computed in `analyze.py` after the three label-type metrics are available.
4. **Space structure diagnostics per label type** — `mean_within_artist`, `var_within_artist`, `mean_cross_artist`, `var_cross_artist` (and `_genre`, `_head` variants).
5. **Report: flip primary sort** — `map_k_general` replaces `disc_general` as the primary sort column in all ranking tables and charts.
6. **Report: MAP-based threshold sweep** — `section_threshold_sweep` in `_binned.py` uses `map_k_general` as the primary y-axis; disc metrics are moved to a secondary/diagnostic section.
7. **Backward compatibility** — `mean_within` and `mean_cross` (artist, no suffix) are preserved. `disc_*` metrics continue to be computed and stored; they are demoted in the report only.

---

## Architecture

### Files Changed

| File | Change |
|---|---|
| `scripts/embedding_research/similarity.py` | Add per-label-type MAP@k family; fix naming bug; add within/cross/var per label type; add `ap_k_genre`/`ap_k_head` to `per_song` dict |
| `scripts/embedding_research/common/analyze.py` | Add new `(flat_name, src_key)` tuples to var/kurt loop; compute and pass `map_k_general` |
| `scripts/embedding_research/report/_base.py` | Extend `ANALYZE_METRICS_COLUMNS` with all new metric names |
| `scripts/embedding_research/report/_retrieval.py` | Add new columns to `flat_columns`/`binned_columns`/table display; flip sort key to `map_k_general` |
| `scripts/embedding_research/report/_binned.py` | Add `map_k_general`-based threshold sweep chart; demote disc to diagnostic |

No schema changes. The `analyze_metrics` table uses an EAV long-format schema `(strategy_key, sim_metric, k, metric, value)` — new metric names flow through automatically.

---

## Metric Definitions

### Naming Convention Fix

Old keys (removed): `f"map_{k}"`, `f"ndcg_{k}"`, `f"recall_{k}"`, `f"recall_{k}_genre"`, `"precision_k_genre"`, `"precision_k_head_mean"` (the last was hardcoded `0.0`).

New key pattern: `{metric}_{label_type}` where label_type ∈ `{artist, genre, head}`.

Backward-compat aliases kept as-is: `mean_within`, `mean_cross` (artist-only, no suffix).

### MAP@k per Label Type

**Artist (`map_k_artist`)**: Existing logic, renamed. Relevance: `label[j] == label[i]`.

**Genre (`map_k_genre`)**: New. Relevance: `genres[j] == genres[i]` (any shared genre tag — the `genres` list is one-tag-per-song; if multi-tag genre strings are stored as comma-separated, treat the entire string as the label for simplicity). AP@k loop mirrors artist logic.

**Head (`map_k_head`)**: New. For each head h, relevance for query song i is defined as `|head_scores[h][j] - head_scores[h][i]| ≤ DISC_HEAD_WINDOW` (reusing the existing constant). AP@k is computed using this per-head window relevance set. AP@k is averaged across all heads → `map_k_head`. If `head_scores` is None, `map_k_head = None`.

**Composite (`map_k_general`)**: Computed in `analyze.py` (not in `similarity.py`), after all label-type metrics are available.

```python
vals = [v for v in [map_k_artist, map_k_genre, map_k_head] if v is not None]
map_k_general = float(np.mean(vals)) if vals else None
```

### MRR, NDCG@k, Recall@k per Label Type

Mirrors the MAP@k structure. Each uses the same label-type relevance definition. MRR and NDCG@k loops already exist for artist — replicate with `_genre` and `_head` suffixes.

### Space Structure Diagnostics per Label Type

For each label type, compute corpus-level mean and variance of pairwise similarities (upper triangle) split by whether the pair is within-group or cross-group:

**Artist**: `mean_within_artist`, `var_within_artist`, `mean_cross_artist`, `var_cross_artist` — same computation as existing `mean_within`/`mean_cross`, with variance added.

**Genre**: Same computation, groups defined by `genres[i] == genres[j]`.

**Head**: For head, "within-group" is defined as: at least one head h where `|score_h[i] - score_h[j]| ≤ DISC_HEAD_WINDOW`. "Cross-group" is defined as: all heads h where `|score_h[i] - score_h[j]| > DISC_HEAD_WINDOW + DISC_HEAD_GAP` (reusing `DISC_HEAD_GAP`). Pairs in neither set (gap zone) are excluded from head within/cross.

**Back-compat**: `mean_within` and `mean_cross` continue to be written (artist-only, no suffix).

---

## Data Flow

### `compute_retrieval_metrics` Return Dict Changes

**Keys removed (replaced):**
- `f"map_{k}"` → `"map_k_artist"`
- `f"ndcg_{k}"` → `"ndcg_k_artist"`  
- `f"recall_{k}"` → `"recall_k_artist"`
- `f"recall_{k}_genre"` → `"recall_k_genre"` (already correct name — this one is kept as-is)
- `"precision_k_genre"` → kept but note it was always computed
- `"precision_k_head_mean"` → **removed** (was hardcoded `0.0`)

**Keys added:**
```
map_k_artist, mrr_artist, ndcg_k_artist, recall_k_artist    (renamed/new)
map_k_genre, mrr_genre, ndcg_k_genre                        (new)
map_k_head, mrr_head, ndcg_k_head, recall_k_head            (new, conditional on head_scores)
mean_within_artist, var_within_artist                        (mean_within preserved as alias)
mean_cross_artist, var_cross_artist                          (mean_cross preserved as alias)
mean_within_genre, var_within_genre, mean_cross_genre, var_cross_genre
mean_within_head, var_within_head, mean_cross_head, var_cross_head  (conditional)
```

**`per_song` dict additions:**
```
ap_k_genre, mrr_genre, recall_k_genre    (per-song arrays for genre)
ap_k_head, mrr_head, recall_k_head       (per-song arrays for head, if head_scores present)
```

### `analyze.py` Additions

New `(flat_name, src_key)` pairs added to the existing var/kurt loop:
```python
("var_ap_k_genre",  "ap_k_genre"),
("var_ap_k_head",   "ap_k_head"),
("var_mrr_genre",   "mrr_genre"),
("var_mrr_head",    "mrr_head"),
```

`map_k_general` is computed after calling `compute_retrieval_metrics` and added to the `metrics` dict before the DB write:
```python
_vals = [metrics.get(k) for k in ("map_k_artist", "map_k_genre", "map_k_head") if metrics.get(k) is not None]
metrics["map_k_general"] = float(np.mean(_vals)) if _vals else None
```

---

## Report Changes

### `_base.py::ANALYZE_METRICS_COLUMNS`

Add all new metric names. Remove `precision_k_head_mean` (was always `0.0`). Keep `disc_*` columns (demoted but still present).

### `_retrieval.py`

- `flat_columns` and `binned_columns`: add `map_k_general`, `map_k_artist`, `map_k_genre`, `map_k_head`, `mrr_artist`, `mrr_genre`, `mrr_head`, `ndcg_k_artist`, `ndcg_k_genre`, `ndcg_k_head`, `recall_k_artist`, `recall_k_genre`, `recall_k_head`, `mean_within_artist`, `var_within_artist`, `mean_cross_artist`, `var_cross_artist`, `mean_within_genre`, `var_within_genre`, `mean_cross_genre`, `var_cross_genre`, `mean_within_head`, `var_within_head`, `mean_cross_head`, `var_cross_head`.
- `section_unified_table`: flip sort key from `disc_genre DESC` / `disc_artist DESC` to `map_k_general DESC NULLS LAST`.
- `table_columns` in `section_unified_table`: move `map_k_general` to the front; demote `disc_general` to a later column.
- `section_per_backbone` scatter: update `metric_cols` to use `map_k_general` and `map_k_artist` as primary y-axes.

### `_binned.py`

- `section_threshold_sweep`: add a `map_k_general`-based chart group alongside the existing disc chart group. The MAP chart is the primary chart (rendered first). Disc charts are rendered in a collapsible "Discrimination Diagnostics" subsection.
- The groupby and aggregation already have the right structure (`_COMBO_COLS` groupby, mean/var per group). Add `mean_map=(map_k_general, "mean")`, `var_map=(map_k_general, "var")` to the `.agg()` call.
- `section_bin_mode_comparison`: compare by `map_k_general` (or `map_k_artist` if general is unavailable).

---

## Constraints

- `compute_agg_mats` and the raw sim-pair cache are not touched by this change.
- `DISC_HEAD_WINDOW` and `DISC_HEAD_GAP` constants defined in Change 4 (already in `similarity.py`) are reused — do not duplicate.
- `ensure_schema` is not modified — no DDL changes.
- `disc_*` metrics continue to be computed and stored. Only the report ordering changes.
- All new per-label metrics are conditional: `_genre` variants require non-null `genres`; `_head` variants require non-null `head_scores`. Missing → `None` → skipped by `write_analyze_metrics`.
- `map_k_general` requires at least one non-null label-type MAP. If all three are null (edge case: no labels at all), it is `None`.
- Existing tests that assert `map_10` key in return dict must be updated to `map_k_artist`.

---

## Backward Compatibility

| Item | Status |
|---|---|
| `analyze_metrics` DDL | Unchanged (EAV model) |
| `disc_general`, `disc_artist`, `disc_genre`, `disc_head` | Computed and stored; demoted in report only |
| `mean_within`, `mean_cross` | Preserved (artist without suffix) |
| `recall_k_genre`, `precision_k_genre` | Preserved under same key names |
| `per_head_corr` | Unchanged |
| `analyze()` signature | Unchanged |
| `compute_retrieval_metrics` signature | Unchanged — only return dict keys change |
| `write_analyze_metrics` | Unchanged |

| Item | Breaking change |
|---|---|
| `f"map_{k}"` return key | Renamed to `"map_k_artist"` — any existing DB rows with `metric="map_10"` are stale and will coexist with new rows; since `analyze_metrics` is cleared at run start (per v2), this is fine on next run |
| `f"ndcg_{k}"`, `f"recall_{k}"` | Same rename treatment |
| `precision_k_head_mean` | Removed — was always `0.0` |
| Report sort key | `disc_general` → `map_k_general` — report output changes |
