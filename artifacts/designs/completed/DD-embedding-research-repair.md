# Embedding Research Pipeline Repair — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-05-25  

**Related Documents:**
- [Pooling Research Findings](artifacts/designs/pooling-research-findings.md) — 

---

## Scope

scripts/embedding_research/ only. This is a standalone research pipeline under scripts/ — not part of nomarr's production codebase. No layer enforcement, no migration system, no production impact. Files touched: db/_schema.py, db/flat.py, db/binned.py, similarity.py, strategy_flat/_analyze.py, strategy_binned/_analyze.py, strategy_binned/_process.py, report/_summary.py, report/_retrieval.py, research_config.toml, run.py, FINDINGS.md. New files: strategy_flat/_truncate.py, report/_truncation.py.

---

## Problem Statement

The embedding research pipeline produces untrustworthy flat-vs-binned comparison results due to eight confirmed defects:

1. **Threshold data pollution** — The DB contains results measured under two incompatible threshold systems (old: corpus-relative std multiplier ~1.6–2.4; new: normalized L2 distance on unit vectors ~0.5–1.4). These are numerically incompatible; old results at threshold~1.55 sit in the DB alongside new runs at 0.2–1.0 and the report mixes them silently.

2. **Meaningless summary verdict** — `_summary.py` computes `median(disc_scores_across_all_configs) - 0.5 * IQR`. This mechanically penalizes binned for having 32 configs (IQR is real) while flat with ~2 configs has IQR ≈ 0, making flat appear more "reliable" by construction. The formula answers a distributional question instead of asking "does binned actually beat flat?"

3. **Broken `disc_head`** — Current implementation uses dominant head index (argmax of head_scores per song) as pseudo-group labels, measuring whether the embedding clusters songs by head consensus. The intended semantics are: use flat PTC class labels as fixed ground-truth groups, then compute discrimination exactly like `disc_artist`/`disc_genre`. This answers whether binned similarity clusters songs by their semantic head labels.

4. **`disc_album` is redundant** — Album and artist are correlated by construction. Album-level discrimination is not an independent signal for music similarity quality.

5. **`disc_general` composition is wrong** — Currently averages `(disc_artist, disc_album, disc_genre, disc_head)`: two redundant components (artist/album), one broken (disc_head). Should be `mean(disc_artist, disc_genre, disc_head)`.

6. **`bin_div_std` is noise** — Measures intra-song bin spread. High values confirm threshold creates distinct windows but do not confirm semantic meaningfulness. Random segmentation achieves equally high values.

7. **`bin_flat_dist` is uninterpretable** — Maximum cosine distance of any bin from the flat pooled vector. Large deviation is equally consistent with musical signal and segmentation noise. Without ground truth, magnitude cannot be interpreted.

8. **Primary sort metric is wrong** — Unified Ranking sorts by `disc_score` (= `disc_artist`). Genre discrimination is a better proxy for "sounds musically similar" than artist identity.

---

## Architecture

### Repair Area 1 — DB Reset and Threshold Re-anchoring

**Files**: `research_config.toml`

Run `python run.py reset` to clear polluted DB. Update `dist_thresholds` in `[binning]` to cover the productive normalized L2 distance range with uniform step:

```toml
dist_thresholds = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]
```

Current values `[0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]` are retained at the lower end but the upper range is extended to cover the geometric center (L2 dist ≈ 1.0 on unit sphere ≈ 60°) and beyond.

---

### Repair Area 2 — Schema Changes (BUG 4, BUG 6, BUG 7, NEW 1, NEW 2, NEW 3)

**Files**: `db/_schema.py`

**Remove** these columns from DDL and all forward migrations:
- `disc_album` from `retrieval_rows` and `binned_retrieval_rows`
- `recall_k_album` from `binned_retrieval_rows` and `binned_ctp_retrieval_rows`
- `bin_div_std` from `binned_song_stats`
- `bin_flat_dist` from `binned_song_stats` (currently added via `ALTER TABLE` migration in `ensure_schema`)

**Add** to `retrieval_rows` and `binned_retrieval_rows`:
- `precision_k_genre DOUBLE` — fraction of top-K neighbors sharing genre tag with query
- `precision_k_head_mean DOUBLE` — mean fraction of top-K neighbors matching dominant flat PTC class per head

**Add** to `binned_retrieval_rows`:
- `flat_binned_spearman DOUBLE` — Spearman ρ of flat vs binned pairwise similarity ordering
- `flat_binned_beneficial_reorder_rate DOUBLE` — fraction of top-200 divergent pairs that are within-genre in binned but cross-genre in flat

**New table** `flat_head_labels`:
```sql
CREATE TABLE IF NOT EXISTS flat_head_labels (
    song_id     TEXT NOT NULL,
    backbone    TEXT NOT NULL,
    head        TEXT NOT NULL,
    score       DOUBLE NOT NULL,  -- raw flat PTC activation score for this head, in [0, 1]
    PRIMARY KEY (song_id, backbone, head)
);
```

Score bins are computed on-the-fly during analysis; only the raw scores are persisted.

**New table** `truncation_robustness_rows`:
```sql
CREATE TABLE IF NOT EXISTS truncation_robustness_rows (
    backbone                   TEXT NOT NULL,
    bin_mode                   TEXT NOT NULL,
    std_thresh                 DOUBLE NOT NULL,
    flat_mean_sim              DOUBLE,
    binned_mean_sim            DOUBLE,
    truncation_robustness_delta DOUBLE,  -- binned - flat; positive = binning more robust
    PRIMARY KEY (backbone, bin_mode, std_thresh)
);
```

---

### Repair Area 3 — `similarity.py` (BUG 3, BUG 5, NEW 2)

**File**: `similarity.py`

**`compute_retrieval_metrics()` signature change**:

Add parameter `head_scores: list[list[float]] | None = None` — for each head, a per-song raw PTC activation score in [0, 1]. Shape: `[n_heads, n_songs]` or `None`.

**Fix `disc_head`** (BUG 3):

Remove current dominant-head-index pseudo-grouping. Replace with: for each PTC head `h`, each song has a continuous score in [0, 1]. Partition songs into fixed-width score bins of width 0.1 (i.e., [0.0, 0.1), [0.1, 0.2), ..., [0.9, 1.0]). Bin assignment: `bin_idx[i] = min(int(score * 10), 9)`. Compute discrimination using these score bins as the grouping variable: `disc_head_per_head[h] = _disc_from_groups(groups=score_bin_assignments[h])`. `disc_head = mean(per-head values)`. This answers: "do songs with similar head activation levels cluster together in similarity space?" — independent of argmax label assignment.

**Fix `disc_general`** (BUG 5):

Change `_disc_components` to include only `[disc_artist, disc_genre, disc_head]` (remove `disc_album`). The `disc_general` computation stays as `mean(non-zero components)`.

**Remove `disc_album`** from return dict, or set it always to `None`/omit. Callers in flat.py and binned.py must stop passing `albums` or ignore the returned value.

**Add `precision_k_genre`** (NEW 2):

```python
# In compute_retrieval_metrics, after rankings:
genre_precision: list[float] = []
if genres is not None and len(genres) == n:
    genre_arr = np.array(genres)
    for i in range(n):
        genre_set = {j for j in range(n) if j != i and genre_arr[j] == genre_arr[i]}
        if not genre_set:
            continue
        top_k = set(rankings[i][:k].tolist())
        genre_precision.append(len(top_k & genre_set) / k)
```

Return `precision_k_genre: float(np.mean(genre_precision)) if genre_precision else 0.0`.

**Add `precision_k_head_mean`** (NEW 2):

For each head `h`, relevant set for song `i` = `{j : bin_idx[j] == bin_idx[i] and j != i}` where `bin_idx[i] = min(int(score * 10), 9)`. Compute precision@K and average across heads.

```python
head_prec_per_head: list[float] = []
if head_scores is not None:
    for h_scores in head_scores:
        h_arr = np.array(h_scores)
        bin_idx = np.minimum((h_arr * 10).astype(int), 9)
        prec_h: list[float] = []
        for i in range(n):
            rel = {j for j in range(n) if j != i and bin_idx[j] == bin_idx[i]}
            if not rel:
                continue
            top_k = set(rankings[i][:k].tolist())
            prec_h.append(len(top_k & rel) / k)
        if prec_h:
            head_prec_per_head.append(float(np.mean(prec_h)))
```

Return `precision_k_head_mean: float(np.mean(head_prec_per_head)) if head_prec_per_head else 0.0`.

**Remove `disc_album` entirely from return dict** — `db/flat.py` and `db/binned.py` must stop writing this column.

---

### Repair Area 4 — Flat Analysis (BUG 3 support, NEW 1)

**File**: `strategy_flat/_analyze.py`

**After computing retrieval metrics**, before returning:

1. **Save flat PTC raw scores to `flat_head_labels` table** — for each song, for each head `h`, store `score = flat_ptc_softmax_for_that_head[h]` (the raw activation value, in [0, 1]) into `flat_head_labels`. Score bins are derived from these scores during analysis.

2. **Serialize flat upper-triangle similarity matrix to filesystem** (NEW 1):

   ```python
   flat_ref_dir = OUTPUT_ROOT / "flat_ref"
   flat_ref_dir.mkdir(parents=True, exist_ok=True)
   tri = sim_matrix[np.triu_indices(n, k=1)].astype(np.float32)
   np.save(flat_ref_dir / f"{backbone}_{strategy}_upper_tri.npy", tri)
   np.save(flat_ref_dir / f"{backbone}_{strategy}_sids.npy", np.array(song_ids))
   ```

   This enables binned analysis to load the flat reference and compute Spearman rank correlation.

---

### Repair Area 5 — Binned Analysis (BUG 1, BUG 3, BUG 6, BUG 7, NEW 1, NEW 2, BUG 8)

**Files**: `strategy_binned/_analyze.py`, `strategy_binned/_process.py`

**Load flat PTC head labels from DB** before computing retrieval metrics:

```python
# In _analyze.py, per (backbone, bin_mode, std_thresh) loop:
head_label_rows = con.execute(
    "SELECT song_id, head, dom_class FROM flat_head_labels WHERE backbone = ?",
    [backbone]
).fetchall()
# Build head_labels: list[list[int]], one list per head, indexed by song position
```

Pass assembled `head_labels` to `compute_retrieval_metrics()`.

**Compute flat↔binned Spearman correlation** (NEW 1):

After building the binned similarity matrix:

```python
flat_tri_path = OUTPUT_ROOT / "flat_ref" / f"{backbone}_{strategy}_upper_tri.npy"
flat_sids_path = OUTPUT_ROOT / "flat_ref" / f"{backbone}_{strategy}_sids.npy"
if flat_tri_path.exists():
    flat_tri = np.load(flat_tri_path)
    flat_sids = np.load(flat_sids_path)
    # Align by song ID → reindex binned_tri to match flat ordering
    # Compute Spearman ρ between flat_tri and binned_tri
    # Compute beneficial_reorder_rate on top-200 most divergent pairs
```

Spearman computation: `scipy.stats.spearmanr(flat_tri_aligned, binned_tri_aligned).statistic`. Beneficial reorder: sort pairs by `|flat_rank - binned_rank|` descending, take top 200; for each, check if binned reordering moved a within-genre pair up (beneficial) or a cross-genre pair up (harmful). `beneficial_reorder_rate = beneficial / 200`.

**Remove `bin_div_std` and `bin_flat_dist` writes** — remove calls to `upsert_binned_song_stats()` for these fields (or stop passing them). Do not compute them.

**Update primary sort** — in Unified Ranking construction, sort by `disc_genre DESC, disc_artist DESC` instead of `disc_score DESC`.

---

### Repair Area 6 — DB Upsert Modules (BUG 4, BUG 6, BUG 7, NEW 1, NEW 2, NEW 3)

**Files**: `db/flat.py`, `db/binned.py`

- Remove `disc_album` from all INSERT/UPSERT statements
- Remove `recall_k_album` from all INSERT/UPSERT statements
- Remove `bin_div_std` and `bin_flat_dist` from `upsert_binned_song_stats()`
- Add `flat_head_labels` upsert function in `db/flat.py`
- Add `truncation_robustness_rows` upsert function in `db/flat.py` or a new `db/truncation.py`
- Add columns `flat_binned_spearman`, `flat_binned_beneficial_reorder_rate`, `precision_k_genre`, `precision_k_head_mean` to binned upsert

---

### Repair Area 7 — Summary Report (BUG 2)

**File**: `report/_summary.py`

**Replace composite-based verdict with dominance-rate verdict**:

The primary verdict question is: "what fraction of valid binned configs beat flat's best `disc_genre` for this backbone?"

```python
# For each backbone:
flat_best_disc_genre = flat_df[flat_df["backbone"] == backbone]["disc_genre"].max()
binned_sub = binned_df[binned_df["backbone"] == backbone]["disc_genre"].dropna()
dominance_rate = float((binned_sub > flat_best_disc_genre).mean())
```

Verdict thresholds:
- `dominance_rate > 0.66` → "consistently better" (green)
- `dominance_rate > 0.33` → "sometimes better" (amber)
- else → "not better" (red)

Keep `composite = median - 0.5 * IQR` as a secondary **tuning sensitivity** column in the table — it measures how sensitive the strategy is to configuration choice, not whether it wins. Label the column "tuning sensitivity (composite)" to clarify its role.

Columns in summary table:
- `backbone`, `flat n`, `binned n` (corpus validity)
- `dominance rate` (primary verdict metric, primary sort)
- `verdict` (derived string)
- `flat best disc_genre`, `binned best disc_genre`
- `flat composite (tuning sens.)`, `binned composite (tuning sens.)`
- `best binned config`

> **Report v2 format constraint:** All section functions (`section_*`) must return a dict with these exact top-level keys: `id`, `title`, `description`, `stats`, `charts`, `tables`, `panels`, `subsections`, `warnings`, `headline`, `empty_message`. The existing sections in `_corpus.py`, `_efficiency.py`, `_optimizer.py`, and `_retrieval.py` already conform. The rewritten `section_summary()` in Repair Area 7 must also return a v2-compliant dict. Plan C implementors must read the existing sections as reference for the required dict structure before rewriting `section_summary()`.

---

### Repair Area 8 — Retrieval Report (BUG 4, BUG 8, NEW 1, NEW 2)

**File**: `report/_retrieval.py`

- Remove `disc_album` column
- Add `precision_k_genre`, `precision_k_head_mean` columns
- Add `flat_binned_spearman`, `flat_binned_beneficial_reorder_rate` columns
- Change primary sort to `disc_genre DESC, disc_artist DESC`
- `disc_score` column kept for back-compat display but not used as sort key

---

### Repair Area 9 — Truncation Robustness (NEW 3)

**New files**: `strategy_flat/_truncate.py`, `report/_truncation.py`

**New pipeline step** `truncate` in `run.py`.

**`strategy_flat/_truncate.py`** logic:

For each song with patches on disk:
1. Load full patch tensor `[n_patches, embed_dim]`
2. Produce two truncated variants:
   - `drop_first`: patches `[n_patches//4 :]`
   - `drop_last`: patches `[: 3*n_patches//4]`
3. For each variant, compute flat-pooled vector (mean pooling over patches)
4. For each (backbone, bin_mode, std_thresh), compute binned pooling on truncated patches using existing `_pool.py` infrastructure
5. Compute `cosine_sim(full_flat_vec, truncated_flat_vec)` and `cosine_sim(full_binned_rep, truncated_binned_rep)` — use representative vector (e.g., mean of bin vectors weighted by bin size)
6. Average over songs and over the two truncation variants

```python
truncation_robustness_delta = mean_binned_sim - mean_flat_sim
```

Store per `(backbone, bin_mode, std_thresh)` in `truncation_robustness_rows`.

**`report/_truncation.py`**: Render a table per backbone with columns `bin_mode`, `std_thresh`, `flat_mean_sim`, `binned_mean_sim`, `delta`. Include interpretation guide:
- δ > 0: binning more robust to temporal truncation
- δ < 0: binning more sensitive to temporal position (segmentation instability)

---

### Repair Area 10 — FINDINGS.md

**File**: `FINDINGS.md`

Add findings log entries:
- `bin_div_std` — Measured intra-song bin spread. Removed: high values are equally achievable by random segmentation. Provides no signal about semantic meaningfulness of bins.
- `bin_flat_dist` — Measured maximum cosine distance of any bin from flat pooled vector. Removed: large deviation is equally consistent with musical signal and segmentation noise. Uninterpretable without ground truth.

---

## Design Goals

1. **Clean flat-vs-binned verdict** — primary comparison uses `dominance_rate` on `disc_genre`: fraction of valid binned configs that beat flat's best disc_genre per backbone. Verdict categories: consistently better / sometimes better / not better.

2. **`disc_genre` as primary quality metric** — genre discrimination replaces `disc_score` (=`disc_artist`) as the primary sort and verdict metric throughout. Genre is a better proxy for "sounds musically similar" than artist identity.

3. **Semantically independent disc components** — `disc_general = mean(disc_artist, disc_genre, disc_head)` — three components, all independent. `disc_album` removed everywhere.

4. **Correct `disc_head` semantics** — uses flat PTC dominant-head class labels as fixed ground truth (saved during flat analysis, consumed during binned analysis). Answers "does binned similarity cluster songs by semantic head labels?" not "does binned agree with flat?"

5. **Remove noise metrics** — `bin_div_std` and `bin_flat_dist` removed from all DB tables, computation, and reports. Logged in FINDINGS.md.

6. **Add analytical depth** — three new metric families: flat↔binned Spearman correlation (structural similarity of retrieval orderings), Precision@K (genre + head oracle), temporal truncation robustness (Δ robustness per config).

7. **Clean threshold sweep** — DB reset before run; `dist_thresholds` covers [0.5, 1.4] with uniform 0.1 step, anchored to the normalized L2 distance coordinate system.

---

## Constraints

- **Not production code** — no layer enforcement (interfaces/services/workflows), no nomarr migration system, no import-linter. This is a standalone research pipeline.
- **DuckDB only** — all persistence via DuckDB in `db/_schema.py`. No ArangoDB. DB path configured via `RESEARCH_DB_PATH` env var or defaults to `OUTPUT_ROOT/research.duckdb`.
- **DB reset required** — threshold data pollution from old threshold system cannot be patched around. A clean reset is mandatory before the repair run. Old `ensure_schema` ALTER TABLE migrations for `disc_album`, `bin_flat_dist` etc. become DROP COLUMN migrations (or the DDL is simply updated since the DB is being reset).
- **Filesystem outputs** — flat reference matrices stored at `OUTPUT_ROOT/flat_ref/{backbone}_{strategy}_upper_tri.npy` and `_sids.npy`. These must exist before binned analysis runs (flat → binned ordering is already the pipeline's natural order).
- **No GPU requirement for truncation** — truncation uses existing patch tensors on disk (already embedded). No re-embedding is needed; it only recomputes pooling over truncated patch windows.
- **scipy available** — `scipy.stats.spearmanr` for Spearman computation. Already in the research virtualenv (check `requirements.txt`; add if absent).

---

## Open Questions

None. All design decisions are resolved from confirmed audit findings. No ambiguities remain about intended behavior, metric semantics, or implementation approach.

---
