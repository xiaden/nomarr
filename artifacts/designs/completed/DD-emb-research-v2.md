# Design: Embedding Research Pipeline — Metrics Overhaul (v2)

**Status:** Accepted  
**Date:** 2026-05-28  
**API reference:** `scripts/embedding_research/CONTRACTS.md`

---

## Overview

The embedding research pipeline produces retrieval and discrimination metrics for audio embedding strategies. Four structural gaps in the current pipeline limit the reliability and granularity of those metrics:

1. **Raw bin-pair similarity data is destroyed** — the binned-strategy analyze phase calls `compute_agg_mats`, which immediately collapses the per-bin cosine similarity matrix into scalar aggregates. Any downstream aggregation method must rerun the entire pipeline from scratch.
2. **No stratification** — the corpus used for analysis is the raw ingest output, which may be artist-skewed or genre-skewed. Metrics on unbalanced corpora conflate representation imbalance with embedding quality.
3. **`disc_head` uses coarse fixed bins** — the current formula `np.minimum((h_scores * 10).astype(np.int32), 9)` maps continuous scores to 10 uniform buckets, making the metric insensitive to fine-grained score proximity.
4. **Per-song metric distributions are discarded** — `compute_retrieval_metrics` computes per-song AP@k, MRR, Recall@k, and per-pair discrimination contributions but returns only corpus-level means, discarding all distributional information.

This document describes the four targeted changes that fix these gaps.

---

## Requirements

1. **Raw bin-bin similarity matrix storage** — store the full `n_bins_a × n_bins_b` cosine similarity matrix for every ordered pair `(min_id, max_id)` on disk as `.npz` files. Aggregation (mean, median) becomes a post-hoc operation over these stored matrices.
2. **Stratification phase** — insert a `stratify` phase between `embed` and `segment`. The phase selects a deterministic, balanced subset of songs (by artist, genre, and optionally head scores) and records the selection in DuckDB keyed by a config hash.
3. **`disc_head` window-based rewrite** — replace the fixed-bin histogram with a score-neighborhood approach controlled by `DISC_HEAD_WINDOW` and `DISC_HEAD_GAP` constants.
4. **Per-song metrics storage** — extend `compute_retrieval_metrics` to emit per-song arrays, persist them to a new `song_retrieval_metrics` table, and add variance/kurtosis rows to `analyze_metrics`.

---

## Architecture

### Pipeline Phase Order

Current:
```
ingest → embed → segment → classify → analyze → report
```

After this overhaul:
```
ingest → embed → stratify → segment → classify → analyze → report
```

All phases from `segment` onward receive the stratified song IDs as a `frozenset[str]` filter. The `analyze` phase already accepts `song_ids: frozenset[str] | None` — this parameter is populated from the stratify phase output.

### Layer Mapping

| Component | File | Responsibility |
|---|---|---|
| Stratify phase | `scripts/embedding_research/common/stratify.py` (new) | Config-hash-keyed corpus selection; writes `stratified_corpus` table |
| Stratify DB ops | `scripts/embedding_research/db/stratify.py` (new) | `load_stratified_sids`, `write_stratified_sids`, `clear_stale_stratification` |
| Sim-pair cache | `scripts/embedding_research/cache/sim_pairs.py` (new) | Read/write `.npz` raw bin-pair matrices; key derivation |
| `compute_agg_mats` | `scripts/embedding_research/strategy_binned/_process.py` | Unchanged; analyze phase now calls `store_sim_pairs` before calling this, and can later reload + aggregate |
| `compute_retrieval_metrics` | `scripts/embedding_research/similarity.py` | Extended to return per-song arrays; `disc_head` logic replaced |
| Analyze phase | `scripts/embedding_research/common/analyze.py` | Calls sim-pair cache writer, calls extended `compute_retrieval_metrics`, writes `song_retrieval_metrics` and var/kurt rows |
| Per-song DB ops | `scripts/embedding_research/db/flat.py` | New `write_song_retrieval_metrics`, `clear_song_retrieval_metrics` |
| `ensure_schema` | `scripts/embedding_research/db/_schema.py` | Adds DDL for `stratified_corpus` and `song_retrieval_metrics` |

---

## Data Flow

### Stratify Phase

```
Input:
  songs table  →  song_id, artist, genre
  flat_head_labels table  →  song_id, backbone, head, score  (conditional)
  research_config.toml  →  limit (N), full file bytes for hash

Processing:
  1. config_hash = sha256(toml_bytes).hexdigest()[:16]
  2. Check stratified_corpus for rows with this config_hash
     - If rows exist: return frozenset(existing song_ids)
     - If no rows:  clear all rows from stratified_corpus; run balancing; write new rows

  Balancing algorithm:
    a. Artist pass:
       cap_per_artist = ceil(N / n_distinct_artists)
       For each artist: keep at most cap_per_artist songs (deterministic shuffle seeded by config_hash)

    b. Genre pass (secondary):
       Within the artist-capped pool, equalise genre counts:
       genres_sorted = sorted by frequency descending
       target_per_genre = floor(N / n_distinct_genres)
       Trim over-represented genres; if pool still > N, trim smallest genres last

    c. Head score pass (tertiary, conditional):
       If flat_head_labels rows exist for any backbone:
         For each head: bin scores into 10 decile buckets
         Compute per-song decile vote (mode across heads)
         Ensure each decile is represented proportionally in the final corpus
       If absent: skip silently

    d. Final truncation: take the first N songs (after deterministic sort by song_id)

Output:
  stratified_corpus rows: (config_hash, song_id)
  Return value: frozenset[str] of selected song_ids
```

`run.py` passes this frozenset to all downstream phases via the existing `song_ids` parameter on `segment`, `classify`, and `analyze`.

### Analyze Phase — Raw Sim-Pair Cache (binned strategies only)

```
For each (backbone, strategy_name, rep_a, rep_b) combination:

  For each song pair (i, j) where i < j:
    cache_path = OUTPUT_ROOT / "cache/sim_pairs" / backbone / strategy_name
                 / f"{min(sid_i, sid_j)}_{max(sid_i, sid_j)}.npz"

    If cache_path exists: skip
    Else:
      raw_sim = norm_a[i] @ norm_b[j].T           # shape: (n_bins_i, n_bins_j), float32
      np.savez(cache_path,
               sim=raw_sim.ravel(),               # 1D, row-major
               shape=np.array(raw_sim.shape, dtype=np.int32))

  Aggregation (for each agg_method):
    Load raw_sim from cache for each pair
    Reconstruct matrix: raw_sim.reshape(shape)
    Apply: mean / median of all elements → scalar
    Populate (n, n) sim matrix entry
```

**Note:** `compute_agg_mats` continues to exist and is used for the computation path when building the sim matrix. The new cache layer sits between `_normalise_binned_pairs` and `compute_retrieval_metrics`: it materialises the per-pair raw matrices to disk, then the existing aggregation logic reads them back (or recomputes if the cache is cold).

The key ordering rule — `min(id_a, id_b)_max(id_a, id_b)` — ensures order-independence since cosine similarity is symmetric.

### Analyze Phase — Per-Song Metrics

`compute_retrieval_metrics` is extended with a new return key `"per_song"` containing a dict of per-song arrays:

```python
# New return keys added to the existing return dict:
{
    ...,                                          # all existing keys unchanged
    "per_song": {
        "ap_k":               list[float],        # len = n songs with ≥1 relevant
        "mrr":                list[float],
        "recall_k":           list[float],
        "disc_artist_contrib": list[float],       # per-song contribution to disc_artist
        "disc_genre_contrib":  list[float],       # per-song contribution to disc_genre
        "disc_head_contrib":   list[float],       # per-song mean disc_head contribution
        "song_ids":           list[str],          # parallel index
    }
}
```

The caller (`analyze.py`) uses the `"per_song"` dict to:
1. Write one row per song to `song_retrieval_metrics` via `write_song_retrieval_metrics`.
2. Compute `scipy.stats.kurtosis` (or numpy equivalent) and `np.var` for each per-song distribution.
3. Write variance/kurtosis as new metric rows to `analyze_metrics` via the existing `write_analyze_metrics` mechanism (no DDL change — new metric names only).

`analyze` clears `song_retrieval_metrics` for the current `(strategy_key, sim_metric, k)` at the top of each strategy loop, before writing new rows (same lifecycle as `analyze_metrics`).

### Analyze Phase — `disc_head` Window-Based Scoring

**Old code (removed from production):**
```python
bin_idx = np.minimum((h_scores * 10).astype(np.int32), 9)
per_head_disc_values.append(_disc_from_groups([str(b) for b in bin_idx.tolist()]))
```

**New code:**
```python
# Hyperparameters defined at module top level in similarity.py
DISC_HEAD_WINDOW: float = 0.1   # half-width of the in-set score neighborhood
DISC_HEAD_GAP: float = 0.1      # minimum score gap before a song enters the out-set

# Per-song contribution (vectorised over songs for one head)
contribs: list[float] = []
for i in range(n):
    in_mask  = np.abs(h_scores - h_scores[i]) <= DISC_HEAD_WINDOW
    out_mask = np.abs(h_scores - h_scores[i]) >  DISC_HEAD_WINDOW + DISC_HEAD_GAP
    in_mask[i]  = False   # exclude self
    out_mask[i] = False
    if not in_mask.any() or not out_mask.any():
        continue          # edge case at score extremes — skip, not an error
    contrib = sim_matrix[i, in_mask].mean() - sim_matrix[i, out_mask].mean()
    contribs.append(float(contrib))

if contribs:
    per_head_disc_values.append(float(np.mean(contribs)))
    # store per-song contribs for the "per_song" dict
    # (averaged across heads at the end)
```

`disc_head` for the corpus = `np.mean(per_head_disc_values)` — same aggregation structure as before, different per-song contribution formula.

---

## Schema Additions

All additions go into the `_DDL` string in `scripts/embedding_research/db/_schema.py`. `ensure_schema` uses `CREATE TABLE IF NOT EXISTS` throughout — additions are safe to apply to existing databases.

### New table: `stratified_corpus`

```sql
CREATE TABLE IF NOT EXISTS stratified_corpus (
    config_hash  TEXT NOT NULL,
    song_id      TEXT NOT NULL,
    PRIMARY KEY (config_hash, song_id)
);
```

- `config_hash`: first 16 hex chars of SHA-256 of the raw `research_config.toml` bytes.
- One row per song in the current selection. Rows for prior config hashes are cleared on recompute.
- Queried by `run.py` to detect whether stratification is already done for the current config.

### New table: `song_retrieval_metrics`

```sql
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
```

- Cleared at the start of each analyze phase run for the given `(strategy_key, sim_metric, k)` tuple (same lifecycle as `analyze_metrics`).
- `disc_artist_contrib` / `disc_genre_contrib`: per-song contribution = `mean(sim[i, within]) - mean(sim[i, cross])` for that song.
- `disc_head_contrib`: per-song `disc_head` contribution = mean across all heads of that song's window-based contribution.
- Songs without any relevant neighbour (singletons in their artist/genre group) receive `NULL` for those columns.

### Extended `analyze_metrics` row types

No DDL change. The existing narrow-format table `(strategy_key, strategy_type, sim_metric, k, metric, value)` gains new `metric` name values written by `write_analyze_metrics`:

| New metric name | Definition |
|---|---|
| `var_ap_k` | `np.var(per_song["ap_k"])` |
| `kurt_ap_k` | `scipy.stats.kurtosis(per_song["ap_k"], fisher=True)` |
| `var_disc_artist` | `np.var(per_song["disc_artist_contrib"])` |
| `kurt_disc_artist` | kurtosis of `disc_artist_contrib` |
| `var_disc_genre` | `np.var(per_song["disc_genre_contrib"])` |
| `kurt_disc_genre` | kurtosis of `disc_genre_contrib` |
| `var_disc_head` | `np.var(per_song["disc_head_contrib"])` |
| `kurt_disc_head` | kurtosis of `disc_head_contrib` |

All variance/kurtosis rows are only written when the underlying per-song list has ≥ 2 elements. `scipy.stats.kurtosis` degrades gracefully for small arrays; if `scipy` is unavailable, the kurtosis rows are skipped (not a blocking error).

### New disk cache: `sim_pairs/`

```
scripts/outputs/embedding_research/
  cache/
    sim_pairs/
      <backbone>/
        <strategy_name>/
          <min_song_id>_<max_song_id>.npz
```

Each `.npz` contains two arrays:

| Array key | dtype | shape | Content |
|---|---|---|---|
| `sim` | `float32` | `(n_bins_a * n_bins_b,)` | Row-major flattened cosine similarities |
| `shape` | `int32` | `(2,)` | `[n_bins_a, n_bins_b]` |

Reconstruct the matrix via `sim.reshape(shape)`.

Key derivation: `min(song_id_a, song_id_b) + "_" + max(song_id_a, song_id_b)` — order-independent because cosine similarity is symmetric.

The `<strategy_name>` path component follows the same naming convention already used by the existing flat-vecs cache under `OUTPUT_ROOT / "cache"`. Consult `scripts/embedding_research/CONTRACTS.md` §7 for the strategy key format.

---

## Constraints

- **Schema**: `ensure_schema` in `db/_schema.py` is the only place to add new tables/columns for the research DB. No migration files; `CREATE TABLE IF NOT EXISTS` makes it idempotent.
- **Layer rules do not apply** to `scripts/embedding_research/` (research scripts, not the main app). Module boundary within the pipeline must be respected: `db/` handles persistence, `common/` handles shared phase logic, `cache/` handles filesystem caching, `similarity.py` contains metrics.
- **`disc_album` does not exist** in this codebase. Do not add or reference it.
- **`act[1]` is the positive-class score** in all head activation arrays. Never use `act[0]`.
- **Tests** in `scripts/embedding_research/tests/` must remain green. The `disc_head_constant_bin_skipped` test behavior changes: the skip condition now depends on all songs falling in the same score neighborhood (i.e., window-based in/out sets are empty for all songs) rather than all songs mapping to the same fixed bin index.
- **`compute_agg_mats`** continues to exist in `strategy_binned/_process.py` — the raw-matrix cache sits around it, not inside it.
- **`research_config.toml` `[pipeline].limit`**: if `null`, use the full balanced corpus (no hard cap after balancing).

---

## Backward Compatibility

### Preserved

| Item | Status |
|---|---|
| All existing DuckDB tables | Unchanged (DDL is additive) |
| `disc_general` formula | Unchanged: mean of non-zero `{disc_artist, disc_genre, disc_head}` |
| `disc_artist` and `disc_genre` formulas | Unchanged: `_disc_from_groups` logic |
| `per_head_corr` Spearman correlations | Unchanged: computed independently of disc_head |
| `analyze_metrics` table format | Unchanged: long/narrow `(strategy_key, strategy_type, sim_metric, k, metric, value)` |
| `write_analyze_metrics` signature | Unchanged: new metrics passed as additional dict keys |
| `analyze()` signature | Unchanged: `song_ids` parameter was already present |
| Flat (global pool) strategy analyze path | Unchanged: no bin-pair cache, no disc_head path change since head_scores are loaded from `flat_head_labels` |
| `compute_agg_mats` function | Unchanged; still exported from `strategy_binned._process` |

### Replaced

| Item | Replacement |
|---|---|
| `disc_head` 10-bin histogram (`np.minimum((h_scores * 10).astype(np.int32), 9)`) | Window-based per-song contribution using `DISC_HEAD_WINDOW` / `DISC_HEAD_GAP` constants |
| Corpus selection in analyze phase | Replaced by stratified corpus from `stratified_corpus` table |
| Immediate `compute_agg_mats` call (binned path) | Preceded by raw sim-pair cache write; aggregation still calls the same `compute_agg_mats` logic but can now be rerun without recomputing raw similarities |
| Discard of per-song metric arrays | Written to `song_retrieval_metrics` before corpus-level aggregates |

---

## Appendix: Research Findings

### `compute_agg_mats` location and signature

- File: `scripts/embedding_research/strategy_binned/_process.py:L123`
- Signature: `compute_agg_mats(norm_a, norm_b, bin_counts, metric, *, progress=None) -> dict[str, np.ndarray]`
- Returns a dict mapping each `agg_method` name to an `[n, n] float32` matrix.
- The inner loop already computes `sim = va @ vb.T` for each pair — the raw per-pair matrix before any aggregation — making the cache insertion point straightforward.

### `analyze` phase existing `song_ids` parameter

- `analyze(con, cfg, *, song_ids: frozenset[str] | None, ...)` in `common/analyze.py:L212`
- Already filters `sids`, `artists`, `albums`, `genres`, and `vecs` when `song_ids` is not `None`.
- The stratify phase simply populates this parameter; no signature change required.

### `write_analyze_metrics` long-format pattern

- `db/flat.py:L131` — iterates `metrics.items()`, skips `None`, flattens nested dicts with underscore joining.
- Variance and kurtosis rows are passed as top-level keys in the `metrics` dict: `{"var_ap_k": 0.023, "kurt_ap_k": 1.4, ...}`.
- No DDL change required.

### `flat_head_labels` availability detection

- `db/songs.py` has `load_song_head_scores(con, backbone, sids)` which queries `flat_head_labels`.
- `_load_head_scores_and_names` in `common/analyze.py` already handles the "no scores" case by returning `(None, None)`.
- The stratify phase uses the same pattern: attempt `load_song_head_scores`; if the result is empty, skip the head score balancing tier silently.

### `research_config.toml` config hash

- The config file is read as raw bytes at pipeline startup by `load_research_config` in `helpers/toml.py`.
- `hashlib.sha256(raw_bytes).hexdigest()[:16]` produces a 16-char deterministic hash.
- This hash is the `config_hash` column key in `stratified_corpus`.
- `hashlib` is already imported in `config.py`.

---

## Change 5: Retrieval-Primary Metrics (MAP@k per label type)

### Problem

The current pipeline's primary analysis signal is `disc_general` — an average of `disc_artist`, `disc_genre`, and `disc_head`. These disc metrics measure *embedding space structure* (within-group similarity minus cross-group similarity). They are proxies. They answer "is the space shaped correctly," not "does the similarity search actually return relevant results." A strategy can have high disc and mediocre MAP@k, or the reverse.

The research question is: **which (backbone × strategy_type × bin_mode × std_thresh × rep_a × rep_b × agg_method) combinatorial is best for similarity search?** The answer is retrieval precision, not space structure.

The original pipeline measured MAP@k against artist labels only. Disc metrics were added to extend coverage to genre and head signals, but in doing so the retrieval frame was abandoned entirely.

### Design

Compute the full set of retrieval metrics (MAP@k, MRR, NDCG@k, Recall@k) **three times** — once per relevance definition:

| Label type | Relevance definition | Metric suffix |
|---|---|---|
| Artist | `artist_a == artist_b` | `_artist` |
| Genre | `genre_a == genre_b` (any shared genre tag) | `_genre` |
| Head | `|score_a - score_b| ≤ DISC_HEAD_WINDOW` per head, averaged across heads | `_head` |

This yields: `map_k_artist`, `map_k_genre`, `map_k_head`, `mrr_artist`, `mrr_genre`, `mrr_head`, `ndcg_k_artist`, `ndcg_k_genre`, `ndcg_k_head`, `recall_k_artist`, `recall_k_genre`, `recall_k_head`.

**Composite**: `map_k_general = mean(map_k_artist, map_k_genre, map_k_head)`, with graceful degradation (average whichever are non-null). This replaces `disc_general` as the single-number headline for a combinatorial.

**Space structure diagnostics**: Retain `mean_within` and `mean_cross` (and add `var_within`, `var_cross`) per label type — six diagnostic values per combinatorial. These are not ranking metrics. They provide a confidence weight: a large within/cross gap with low variance indicates the space is cleanly structured and the MAP@k is trustworthy; wide variance with a small gap indicates MAP@k results are fragile. The Cohen's d signal:

$$d = \frac{\mu_{\text{within}} - \mu_{\text{cross}}}{\sigma_{\text{pooled}}}$$

is the correct interpretive frame. High MAP@k paired with low d is a flag; high MAP@k paired with high d is a strong result.

**Disc metrics removed as primary signals**: `disc_artist`, `disc_genre`, `disc_head`, `disc_general`, `disc_score` are demoted to the diagnostic section of the report. They are not used in any ranking, composite, or threshold sweep chart. They are kept in the database for reference.

### `compute_retrieval_metrics` changes

The function is extended to accept a `relevance_mode` parameter (or called three times — implementation decision for the executor). The existing `artists` parameter drives `_artist` mode. A new `genres: list[str] | None` parameter drives `_genre` mode. The existing `head_scores: np.ndarray | None` parameter (already present for `disc_head`) drives `_head` mode, using `DISC_HEAD_WINDOW` from the same constants added in Change 4.

All three label types produce the same shape of output — per-song AP, MRR, Recall arrays — which feed into both the per-song storage (Change 4) and the corpus-level aggregates.

### New `analyze_metrics` rows

| New metric name | Definition |
|---|---|
| `map_k_artist` | corpus mean of per-song AP@k (artist relevance) |
| `mrr_artist` | corpus mean of per-song MRR (artist relevance) |
| `ndcg_k_artist` | corpus mean of per-song NDCG@k (artist relevance) |
| `recall_k_artist` | corpus mean of per-song Recall@k (artist relevance) |
| `map_k_genre` | same, genre relevance |
| `mrr_genre` | same |
| `ndcg_k_genre` | same |
| `recall_k_genre` | same |
| `map_k_head` | same, head-score window relevance |
| `mrr_head` | same |
| `ndcg_k_head` | same |
| `recall_k_head` | same |
| `map_k_general` | mean of non-null `{map_k_artist, map_k_genre, map_k_head}` |
| `mean_within_artist` | mean pairwise sim within same-artist pairs |
| `mean_cross_artist` | mean pairwise sim across different-artist pairs |
| `var_within_artist` | variance of pairwise sim within same-artist pairs |
| `var_cross_artist` | variance of pairwise sim across different-artist pairs |
| `mean_within_genre` | same, genre pairs |
| `mean_cross_genre` | same |
| `var_within_genre` | same |
| `var_cross_genre` | same |
| `mean_within_head` | mean pairwise sim within head-window in-set pairs |
| `mean_cross_head` | mean pairwise sim outside head-window out-set pairs |
| `var_within_head` | variance of in-set pairwise sims |
| `var_cross_head` | variance of out-set pairwise sims |

All rows use the existing long-format `analyze_metrics` schema — no DDL change.

### Existing metric names retained

The existing `map_k`, `mrr`, `ndcg_k`, `recall_k`, `mean_within`, `mean_cross` rows continue to be written for backward compatibility (they correspond to artist-relevance, the original and still default). They are not removed.

### Report implications

- **Primary sort key** in unified ranking: `map_k_general` (or `map_k_artist` as fallback).
- **Threshold sweep chart**: x-axis = `std_thresh`, y-axis = `map_k_general` per combinatorial (mean disc secondary chart, in diagnostic section).
- **Bin mode comparison**: compared by `map_k_general`, not disc.
- **New diagnostic section**: `mean_within_*` / `mean_cross_*` / `var_within_*` / `var_cross_*` per label type — displayed as grouped bar charts (gap = within − cross, with variance error bars).
- **Robustness section** (stub until Change 4 per-song storage lands): per-song `ap_k_artist` distribution per combinatorial — box plots or violin plots.
- **Disc section**: moved to collapsible diagnostic group, not top-level navigation.

### Constraints

- Head-based retrieval metrics (`map_k_head`, etc.) are only computed when `flat_head_labels` rows exist for the current backbone. If absent, these columns are `NULL` and `map_k_general` degrades to `mean(map_k_artist, map_k_genre)`.
- Genre-based retrieval metrics are only computed when `genres` data is non-null and non-empty. If absent, they are `NULL`.
- The `_head` relevance mode reuses the `DISC_HEAD_WINDOW` constant defined in Change 4. These are the same hyperparameter — do not duplicate the constant.
- `disc_head` (the existing space-structure metric) continues to be computed independently of `map_k_head`. They measure different things and both are stored.
