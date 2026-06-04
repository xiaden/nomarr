# Embedding Research Package Unification — Design Document

**Status:** Draft  
**Author:** Copilot  
**Created:** 2026-05-19  

---

## Scope

scripts/embedding_research/ — the entire research pipeline package

---

## Problem Statement

The embedding research package has grown into two parallel, independently-driven tracks (flat pooling and temporal binning) that share no common structure and produce separate reports. This creates several failure modes:

1. **Fidelity gap**: `binned_embed.py` and `binned_analyze.py` each accept `--std-thresh` independently. If `embed_binned` runs with thresholds [0.5, 1.0, 2.0] and `analyze_binned` is later called with a wider default sweep, it silently skips configurations that were never embedded. The user has no indication that analysis results are incomplete relative to the embedding corpus.

2. **No unified comparison**: binned and flat strategies each produce separate tables and separate report sections with no side-by-side view. The stated research goal is to find the best overall retrieval strategy — which requires comparing flat pooling vs temporal binning in a single ranked table.

3. **Accumulated debug cruft**: 13 `_*.py` scripts (`_check_analyze.py`, `_diag*.py`, `_smoke*.py`, etc.) are one-shot investigation artifacts that no longer have a purpose. They add surface area and confusion.

4. **Duplicated tracks**: `embed.py` + `binned_embed.py`, `classify.py` + `binned_classify.py`, `analyze.py` + `binned_analyze.py`, `report.py` + `html_report.py` are structural mirrors with no cross-referencing. Adding a new backbone requires touches in every parallel file.

5. **Cache blindness**: the pipeline only checks whether an individual row exists for resume purposes. There is no phase-level cache check that says "given the current config, what work has already been done?" before the run begins. This means the operator must reason externally about what to re-run.

---

## Architecture

## Target Structure

```
scripts/embedding_research/
    run.py              CLI: single entrypoint, phases = embed | classify | analyze | report | all
    config.py           paths, model registry, threshold lists (unchanged)
    db.py               schema + all read/write/query functions (refactored, not replaced)
    similarity.py       metrics + retrieval quality (unchanged)
    pooling.py          pooling functions (unchanged)
    strategy_flat.py    COMPLETE flat-pooling strategy: embed → cache-check → pool → upsert; analyze → cache-check → metrics → upsert
    strategy_binned.py  COMPLETE binned strategy: calibrate → segment → pool → upsert; analyze → discover thresholds from DB → metrics → upsert
    classify.py         head inference for both flat and binned representations (unified)
    report.py           single unified HTML report comparing ALL strategies side-by-side
```

**Deleted:** `embed.py`, `analyze.py`, `binned_embed.py`, `binned_analyze.py`, `binned_classify.py`, `binned_sim.py`, `html_report.py`, `io_utils.py` (merged), `write_queue.py` (merged), all `_*.py` debug scripts

## Core Principle: DB as Source of Truth for Analysis

`strategy_flat.analyze()` and `strategy_binned.analyze()` do NOT accept a threshold list as input. Instead they query the DB first:

```python
# strategy_binned.analyze — what's in the DB defines what gets analyzed
present = db.query_binned_configs(con)   # -> [(backbone, bin_mode, std_thresh), ...]
already_done = db.query_binned_analysis_done(con)
to_do = present - already_done
```

This eliminates the fidelity gap. If embeddings exist for a config, analysis will run for it. If they don't exist, analysis will not manufacture phantom results.

## Per-Strategy File Contract

Each strategy file (`strategy_flat.py`, `strategy_binned.py`) exports exactly two public functions:

```python
def embed(con, *, limit, force, backbones, verbose, device, **kwargs) -> None:
    """Check cache → compute missing → upsert. Never re-does work unless force=True."""

def analyze(con, *, k, backbones, workers, verbose, **kwargs) -> None:
    """Discover configs from DB → check analysis cache → compute missing → upsert."""
```

No phase logic lives in `run.py`. `run.py` is purely wiring.

## Cache Check Pattern

Both embed and analyze use the same two-step pattern:
1. Query DB for the set of (config) keys that should be done given current args
2. Query DB for the set of (config) keys that ARE done
3. Work = (should_be_done) - (are_done), unless force=True

For `analyze`, "should_be_done" is derived from what was embedded, not from the CLI args. This is what prevents the fidelity gap.

## Unified Report

`report.py` runs a single query against both `retrieval_rows` and `binned_retrieval_rows`, producing:

- A ranked table of ALL configurations (flat + binned) by disc_score, MAP@k, MRR, NDCG@k
- Per-backbone comparison: best flat strategy vs best binned strategy at each threshold
- Threshold sweep chart per backbone/bin_mode
- Head agreement section (both flat and binned)

No separate `html_report.py`. One file, one run, one output.

---

## Design Goals

1. A single `python run.py all` produces a complete, correct, comparable analysis every time — with no "go back and redo" steps.
2. `strategy_flat.py` and `strategy_binned.py` are self-contained: reading either file alone is sufficient to understand that strategy end-to-end.
3. The DB is the only source of truth about what configs have been analyzed. CLI arguments narrow what gets computed, never define what gets reported.
4. Adding a new backbone requires edits only to `config.py` and `db.py` (schema only if the schema changes).
5. The package has ≤ 9 files (down from 30+).

---

## Constraints

- The `binned_analyze` job currently running in Docker must not be interrupted.
- All existing DB data is valid and must be preserved (no schema changes, no drops).
- `db.py` schema DDL is not changing; only new read/query helper functions are added.
- The package still runs only inside the devcontainer.
- Python 3.11+, DuckDB, NumPy, tqdm are available; faiss and threadpoolctl are optional.

---

## Open Questions

- `write_queue.py` is used by `binned_embed.py` for async DB writes. After unification, do we keep the write queue pattern in `strategy_binned.py` or simplify to synchronous writes? (Leaning: keep it — it's a real perf win for the binned case which writes 4 reps × many bins × many songs.)
- `report.py` currently generates markdown + CSV; `html_report.py` generates HTML charts. After unification, do we keep the markdown/CSV outputs or go HTML-only? (Leaning: HTML-only since the goal is a "research report to browse".)
- `binned_sim.py` defines AGG_METHODS, REP_TYPES, SIM_METRICS for the binned analysis. Should this move into `strategy_binned.py` or stay as a shared import? (Leaning: into `strategy_binned.py` since it's only used there.)

---
