---
name: embedding-research
description: Use when working on any file in scripts/embedding_research/. Covers contracts, change protocols, test baselines, and pipeline architecture for the embedding research scripts.
---

# Skill: Embedding Research Pipeline

## When to use this skill
Use when working on any file in `scripts/embedding_research/`. Load before reading any source file or making any edit.

## Current storage state (2026-09-02 audit — supersedes stale details below)

Vectors/segments/head outputs are **filesystem-only**; DuckDB holds scalars, metadata, and provenance. The follow-on repair (commits 72f4bc1c, 927ef544) did NOT move vectors into DuckDB — it deleted the sim-matrix caches, added `db/head_phase.py` (head_phase_provenance), and made FS caches canonical.

**DuckDB — written by the pipeline:** `songs`, `analyze_metrics` (incl. `trace_*` scalars), `song_retrieval_metrics`, `binned_calibration`, `binned_song_stats`, `stratified_corpus`, `phase_timings`, `head_phase_provenance`.
**DuckDB — DDL'd but unwritten (vestigial):** `pooled_vecs`, `head_results` (DEAD), `head_agreement_rows`, `binned_pair_sims`, `patch_features`, `truncation_robustness_rows`, `binned_ctp_vecs`, `binned_ptc_ctp_metrics`, `binned_classify_ctp`, `head_sim_corr_rows` (upsert fns for the last two exist but zero production callers).

**Filesystem (OUTPUT_ROOT=scripts/outputs/embedding_research):** `patches/{sid}.{bb}.npy` raw patch embeddings (config.py deliberately keeps out of DB); `cache/{bb}/{strategy}/flat/{sid}.npy` flat pooled incl. **medoid** (pooling.STRATEGIES now includes medoid — old note claiming it didn't is stale); `cache/{bb}/heads/{head}/{strategy}/{ptc|ctp}/{sid}.npy`; `cache/binned_ptc/{tag}/{bb}/{bin_mode}/{thresh}/{sid}.npz` (pool_*_raw/norm, weights, outliers, bin_start/end_idx, medoid idx/centrality, head_*); `cache/binned_ctp/...` (archival); `cache/binned_ptc_heads/...` and `cache/binned_ctp_heads/...` (head-phase pools with provenance fields). `cache/sim.py` + `cache/sim_pairs.py` were **deleted** (Plan C) — pairwise sim/scoring matrices are in-memory only.

**In-memory, discarded:** per-pair cosine/scoring matrices, full SegmentScoreTrace records (only 10 `trace_*` scalars persist via `score_variant_trace_summary`, strategy_binned/_process.py:351-381), matching-corpus manifests (recomputed per run; hash surfaces only in report/head_phase_provenance). `matrix_cache_identity`/`versioned_cache_root` (cache_identity.py) are defined+tests only — zero production callers.

**Current config:** effnet-only primary (flat medoid + PTC medoid segments, score_variant=`max_per_candidate_segment`); MusicNN opt-in; CTP archival (`[archival_ctp] enabled=false`).

**Stale artifacts:** on-disk `research.duckdb` (7.2GB, Aug 31) predates the follow-on contract (per FINDINGS.md Plan E note); the on-disk report is the synthetic fixture report (generate_fixture_report.py), and no `cache/`/`patches/` dirs exist yet — the real pipeline has NOT been run to completion post-repair.

## Before Any Edit
1. Run baseline tests: `python -m pytest scripts/embedding_research/tests/ -x -q` (must pass before starting)
2. Read the contracts section for every file you'll touch — contracts live in `scripts/embedding_research/_contracts_part_1.md` through `_contracts_part_7.md`
3. Read `scripts/embedding_research/RULES.md` for change protocol

## Contracts Quick Reference

### compute_retrieval_metrics() return keys (ALL 15 — always present)

| Key | Type |
| ----- | ------ |
| `map_{k}` | `float` (e.g. `map_10`) |
| `mrr` | `float` |
| `ndcg_{k}` | `float` (e.g. `ndcg_10`) |
| `recall_{k}` | `float` (e.g. `recall_10`) |
| `recall_{k}_genre` | `float` (e.g. `recall_10_genre`) |
| `precision_k_genre` | `float` |
| `precision_k_head_mean` | `float` |
| `disc_artist` | `float` |
| `disc_score` | `float` (back-compat alias = `disc_artist`) |
| `disc_genre` | `float` |
| `disc_head` | `float` |
| `disc_general` | `float` |
| `mean_within` | `float` |
| `mean_cross` | `float` |
| `per_head_corr` | `dict[str, float]` or `{}` |

> `disc_album` does NOT exist. The docstring is wrong. Do not add a SELECT or upsert for it.

### FLAT_COLUMNS (18 items)

```python
["backbone", "strategy", "sim_metric", "k",
 "disc_general", "disc_artist", "disc_genre", "disc_head", "disc_score",
 "mean_within", "mean_cross",
 "map_k", "mrr", "ndcg_k", "recall_k", "recall_k_genre",
 "precision_k_genre", "precision_k_head_mean"]
```

### BINNED_COLUMNS (24 items)

```python
["backbone", "bin_mode", "std_thresh", "rep_a", "rep_b", "sim_metric", "agg_method", "k",
 "disc_general", "disc_artist", "disc_genre", "disc_head", "disc_score",
 "mean_within", "mean_cross",
 "map_k", "mrr", "ndcg_k", "recall_k", "recall_k_genre",
 "precision_k_genre", "precision_k_head_mean",
 "flat_binned_spearman", "flat_binned_beneficial_reorder_rate"]
```

### Key Invariants

1. **`disc_album` does not exist** — never SELECT, upsert, or add a guard for it anywhere.
2. **`act[1]` is the class-1 probability** — `act = [p0, p1]`. Head scores for disc, binning, `disc_head`: always `act[1]`. `act[0]` is never correct.
3. **`bin_idx` formula is frozen**: `bin_idx = np.minimum((h_scores * 10).astype(np.int32), 9)` — 10 bins, score 1.0 → bin 9.
4. **`disc_general` zero-exclusion is intentional** — zero components are excluded from the mean; a WARNING is logged. Do not change to include zeroes.
5. **`as_tuple()` order must match INSERT column order** — `BinnedRetrievalRow.as_tuple()` order differs from DDL order; upserts must use named-column INSERTs, not positional. Verify both side-by-side after any field addition.
6. **All 5 layers must be updated atomically** when adding/removing a metric — partial fixes cause the next crash to be in a different file.

## Cross-File Change Checklist
When changing a metric key or column name, update ALL of:
- [ ] `similarity.py` — return dict key
- [ ] `db/_types.py` — dataclass field
- [ ] `db/_schema.py` — DDL column
- [ ] `db/flat.py` or `db/binned.py` — upsert + load SELECT
- [ ] `report/_base.py` — FLAT_COLUMNS or BINNED_COLUMNS

Also grep these 7 files before submitting: `db/_schema.py`, `db/_types.py`, `db/flat.py`, `db/binned.py`, `report/_base.py`, `similarity.py`, `run.py`.

## What Has Gone Wrong Before (do not repeat)
- Selecting `disc_album` from DB after it was removed from schema → `OperationalError`
- `BinnedRetrievalRow.as_tuple()` column order diverging from INSERT order → wrong values silently inserted
- Passing `act[0]` instead of `act[1]` for head scores → all bins 5–9, bins 0–4 unreachable
- Stale ALTER TABLE guards adding back removed columns on every run → schema drift
- Fixing a crash in one layer without checking all 5 connected layers → new crash on next run

## Known Gaps — Flat-Medoid Baseline & Report Pooling (audit 2026-08-31)

### The flat baseline is NOT medoid
- `pooling.STRATEGIES` (pooling.py:43-50) = `mean`, `trimmed_10`, `trimmed_20`, `median` (coordinate-wise `np.median(axis=0)` — synthetic, NOT medoid), `max_norm`, `l2norm_mean`. **No medoid exists in the flat pool.**
- Medoid exists ONLY for binned per-bin reps: `strategy_binned/_constants.py:50` `_BIN_POOL_STRATEGIES["medoid"]` = observed patch closest to centroid.
- `[pooling] rep_types` in research_config.toml is wired to `cfg["flat_strategies"]` (run.py:662) but that key is **dead config** — never consumed. `_segment_phase` and `GLOBAL_POOL_ANALYZE_CFG` run all 6 pooling strategies regardless. If the intent is a flat-medoid-only baseline run, it is not achievable via config today.

### The report pools strategies (confirmed)
- `report/_summary.py:33-35`: flat baseline = **MAX over all 6 flat strategies** of disc_genre; dominance rate = fraction of ALL PTC+CTP configs beating that max. Headline verdict uses disc_genre only.
- `report/_retrieval.py:212`: every flat row is labeled `config="flat"` — strategy identity (mean/median/max_norm/...) is dropped from the top-20 table (cols at 326-346 omit `strategy` and `sim_metric`).
- `report/_retrieval.py:482`: per-backbone delta-bar baseline = **MEDIAN over all 6 flat strategies**.
- `report/_binned.py:96-99`: threshold-sweep flat reference = **MEAN over all 6 flat strategies**.
- Three different flat "baselines" across report sections; none is medoid; none is a per-strategy comparison.

### Other confirmed facts
- DB is per-strategy: `analyze_metrics` PK = (strategy_key, sim_metric, k, metric) (db/_schema.py:89-97); `common/analyze.py` writes each strategy independently. No cross-strategy mixing in DB.
- `similarity.METRICS` is hardcoded to `{"cosine": ...}` (similarity.py:71-73) regardless of config — sim-metric dimension is effectively 1.
- `flat_binned_spearman` / `flat_binned_beneficial_reorder_rate` are **never populated** in the main pipeline (only `_optimize.py:311` calls `compute_retrieval_rows`, without `flat_upper_tri`; `common/analyze.py` uses `similarity.compute_retrieval_metrics`). `section_flat_binned_correlation` always renders empty.
- Corpus alignment: flat loads all cached sids; binned loads only sids with bins + rep keys (run.py `_load_ptc/_load_ctp_analyze_vecs`). Different strategies can run on different song sets — summary warns on n_songs mismatch, but no per-backbone alignment exists.

## Structural Map (research 2026-08-31, for repair/simplification planning)

### Phase boundaries (run.py main L593-723)
`ingest → embed → stratify → segment → classify → analyze → report`. **No optimize phase** (`[optimization] enabled=false`, `optimize_std_threshold` is manual); **no truncation phase** — `truncation_robustness_rows` table + `db/truncation.py` writer exist but nothing calls them, so `section_truncation` always renders empty.

### Identity keys (run.py:188-203; decode at report/_base.py:139-177)
- `global_pool`: `"global_pool:{backbone}:{strategy}"` — 6 flat strategies, no medoid.
- `ptc`: `"ptc:{bb}:{bin_mode}:{std_thresh:.2f}:{rep_a}:{rep_b}:{agg_method}"`
- `ctp`: `"ctp:{bb}:{head}:{std_thresh:.2f}:{rep_a}:{rep_b}:{agg_method}"` — CTP decode sets `bin_mode=None` (report/_base.py:170-175), so CTP rows have NaN bin_mode; `section_bin_mode_comparison` filters them out (report/_binned.py:685).
- Live TOML dims: `rep_types=["median","medoid"]`, `agg_methods=["median"]`, `metrics=["cosine"]` → 4 strategy keys per PTC/CTP config; analyze_metrics PK (strategy_key, sim_metric, k, metric).

### Segmentation semantics (unit normalization)
- `helpers/binning.py:90-171 temporal_segment`: running spherical mean centroid; `global_dist` = L2 on unit vectors (threshold is a DIRECT distance, not std multiplier); `perdim_dist` = Chebyshev max|Δ|; outlier_window=3, hard-split semantics.
- **PTC** (strategy_ptc/segment_fn.py:148): threshold = `std_thresh × p50` (p50 calibration per bin_mode) — std_thresh is a MULTIPLIER of p50. Segments+pool **unit** patches.
- **CTP** (strategy_ctp/segment_fn.py:184): threshold = `std_thresh × per-song score_std` on raw `acts[:,1]`; segments raw 1-D scores; pools **RAW** patch segments then `_l2_normalise_vec(pooled)` (L213). Asymmetry vs PTC: PTC pools unit patches, CTP pools raw then normalizes.
- **CONTRADICTION**: research_config.toml [binning] comment claims dist_thresholds are "Normalized L2 distance thresholds" but the PTC path multiplies by p50; the optimizer (`_optimize.py`) treats them as direct L2. One number, two semantics.

### Pair matrix / reduction — weights are dropped
- `compute_agg_mats` (strategy_binned/_process.py:137-218): mean fast path = `Σ bin-vecs / n_bins` — UNWEIGHTED mean over bin vectors. Per-bin patch counts (`weights` in cache npz) are never loaded by `_load_ptc/_load_ctp_analyze_vecs`; `bin_counts` = number of bins per song only. `loop_aggs` (median/max/min) also treat bin vectors equally; "medoid" agg raises.
- `sim_pairs` cache (analyze.py:369-374) is **write-only and mis-keyed**: raw_sim computed per (rep_a, rep_b) payload but keyed `(bb, strategy_name, sid-pair)` WITHOUT rep_a/rep_b (cache/sim_pairs.py) → the first rep combo to run populates it and later combos skip via `sim_pair_exists`; the stored value is never read back (agg_mats come from compute_agg_mats). Vestigial overhead + cross-rep collision.
- `cache/sim.py` (`load_sim`/`save_sim`): **0 callers — dead module**.

### Cache key map
- flat_vecs: `{OUT}/cache/{bb}/{strategy}/flat/{sid}.npy`
- binned_ptc: `{OUT}/cache/binned_ptc/{vsX_tsY_osZ_bpW}/{bb}/{bin_mode}/{thresh:.3f}/{sid}.npz` (semantics tag from `helpers/binning.py cache_semantics_tag`)
- binned_ctp: `{OUT}/cache/binned_ctp/{tag}/{bb}/{head}/{thresh:.3f}/{sid}.npz`
- sim_pairs: `{OUT}/cache/sim_pairs/{bb}/{strategy_name}/{min_sid}_{max_sid}.npz` (order-independent)
- sim: `{OUT}/cache/sim/{bb}/{bin_mode}/{thresh}/{rep_a}_{rep_b}_{metric}.npz` — DEAD
- flat_heads: `{OUT}/cache/{bb}/heads/{head}/{strategy}/{ptc|ctp}/{sid}.npy` (head_scores for analysis read strategy="mean" pathway="ptc" only, analyze.py:211-242, `act[-1]`)
- binned_ptc_heads / binned_ctp_heads: `{OUT}/cache/binned_ptc_heads|binned_ctp_heads/{bb}/{head}[/{bin_mode}]/{thresh}/{sid}.npz`

### Dead / stale code (simplification targets)
- `db/_types.py` is an empty stub ("legacy dataclasses removed"); `_process.py` imports `_BinnedRetrievalRow` from it but the live class is the local fallback NamedTuple (L18-50). Skill's FLAT_COLUMNS/BINNED_COLUMNS (above) are stale — actual lists are `ANALYZE_METRICS_COLUMNS` (report/_base.py:66-125, 59 cols) and `flat_columns`/`binned_columns` (report/_retrieval.py:95-202).
- `_process_group` (strategy_binned/_process.py:317-355): **0 callers** (legacy analyze_ctp wrapper). `compute_retrieval_rows` reachable only via `_process_group` + `_optimize.py:311`.
- `_EXPECTED_ROWS_PER_CONFIG` (strategy_binned/_constants.py:43): computed, never used.
- `flat_strategies` config (run.py:662): dead (segment phase runs all 6 pooling strategies; GLOBAL_POOL_ANALYZE_CFG uses `pooling.STRATEGIES`).
- `binned_ctp_vecs` table still DDL'd (db/_schema.py:207-220) though the cache module says the DB table was removed.
- `head_agreement_rows`, `binned_pair_sims` (schema comment: "upsert_binned_pair_sims_bulk() exists but is not called"), `binned_ptc_ctp_metrics`: DDL'd, never written by the pipeline.
- CONTRACTS.md stale: `strategy_flat/` module refs (L11, 1941, 2767, 4601, 4692, 4740, 4925) — module is now `strategy_global_pool/`; `_optimize.py` docstring mentions `disc_album` (does not exist).

### Tests by area (exact change surface)
- flat: `test_gp_embed.py`, `test_gp_segment_fn.py`, `test_segment.py` (segment skeleton), `test_embed.py`
- similarity/metrics: `test_similarity.py`, `test_per_song_metrics.py`
- analysis/identity: `test_analysis.py` (expected identifiers L159-203, var_kurt L270-335, map_k_general L338-432)
- segment fns: `test_ptc_segment_fn.py`, `test_ctp_segment_fn.py`; agg mats: `test_binned_process.py`
- caches: `test_flat_heads_cache.py`, `test_ptc_heads.py`, `test_sim_pair_cache.py`
- db: `test_db.py` (schema table list L52-59 includes the dead tables); report: `test_report.py` (decode strategy keys, unified table, summary, threshold sweep, bin-mode comparison)
- stratify: `test_stratify.py`; toml: `test_toml.py`
