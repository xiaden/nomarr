---
name: embedding-research
description: Use when working on any file in scripts/embedding_research/. Covers contracts, change protocols, test baselines, and pipeline architecture for the embedding research scripts.
---

# Skill: Embedding Research Pipeline

## When to use this skill
Use when working on any file in `scripts/embedding_research/`. Load before reading any source file or making any edit.

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
