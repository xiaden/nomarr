# embed-phase-extraction — Implementation Parts

**Design doc:** `artifacts/designs/pending/DD-embed-phase-extraction.md`

---

## Parts

| Part | Title | Depends On | Files Touched |
|---|---|---|---|
| A | DB Schema & Write/Read API | None | `db/_schema.py`, `db/_types.py`, `db/flat.py`, `db/binned.py`, `db/__init__.py` |
| B | Extract `common/embed.py` | None | `common/` (new), `strategy_global_pool/_embed.py` |
| C | Segment Skeleton & Strategy Thin Files | B | `common/segment.py`, `strategy_global_pool/segment_fn.py`, `strategy_ptc/` (new), `strategy_ctp/` (new), `strategy_binned/_embed.py` (deleted) |
| D | Analyze Skeleton & `AnalyzeCfg` | A, C | `common/analyze.py`, `strategy_global_pool/_analyze.py` (deleted), `strategy_binned/_analyze.py` (deleted) |
| E | Report Layer Adaptation | A | `report/_base.py`, `report/_retrieval.py`, `report/_summary.py`, `report/_binned.py` |
| F | `run.py` Pure Wiring | B, C, D | `run.py` |
| G | Test Updates | A, D, E | `tests/test_db.py`, `tests/test_analysis.py`, `tests/test_report.py` |

---

## Dependency Graph

```
A ──────┬──────────────────────────► D ──► F
        │                             ▲
B ──────┼──────► C ──────────────────┘
        │                             
        └──────► E ──────────────────► G
                                       ▲
                 D ────────────────────┘
```

---

## Execution Rounds

```
Round 1: A          (no deps — DB foundation)
Round 2: B, E       (B has no deps; E depends on A only)
Round 3: C          (depends on B)
Round 4: D          (depends on A, C)
Round 5: F          (depends on B, C, D)
Round 6: G          (depends on A, D, E)
```

---

## Per-Part Scope

### Part A: DB Schema & Write/Read API

Replaces the three existing retrieval tables (`retrieval_rows`, `binned_retrieval_rows`, `binned_ctp_retrieval_rows`) with a single EAV table `analyze_metrics(strategy_key, strategy_type, sim_metric, k, metric, value)`. Removes the `BinnedRetrievalRow` and `CTPRetrievalRow` DTOs from `db/_types.py`. Replaces all old upsert/query functions in `db/flat.py` and `db/binned.py` with `write_analyze_metrics` and `load_analyze_metrics`. Updates `db/__init__.py` exports. The DB is reset (not migrated) — old DDL is deleted, new DDL is added. This part produces the DB contract that all downstream parts depend on.

### Part B: Extract `common/embed.py`

Creates the `common/` package. Extracts ONNX session management, audio loading, preprocessing, inference, sidecar writes, and song registration from `strategy_global_pool/_embed.py` into `common/embed.py`. The public signature is `embed(con, *, song_ids, force, backbones, device) -> None`. The remaining stub in `strategy_global_pool/_embed.py` delegates to `common/embed.py` until it is fully replaced in Part C. This part does not touch the DB layer.

### Part C: Segment Skeleton & Strategy Thin Files

Creates `common/segment.py` with the shared segment phase skeleton and the `SegmentFn` protocol. Creates `strategy_global_pool/segment_fn.py` (one-liner: `pool_fn(patches)` per strategy variant). Creates `strategy_ptc/` package with `segment_fn.py` containing distance-based temporal binning logic migrated from `strategy_binned/_embed.py`. Creates `strategy_ctp/` package with `segment_fn.py` containing score-stream temporal binning logic migrated from `strategy_binned/_analyze.py`. Deletes `strategy_binned/_embed.py`. The old `strategy_global_pool/_embed.py` is replaced entirely by `common/embed.py` (Part B) + `segment_fn.py` (this part).

### Part D: Analyze Skeleton & `AnalyzeCfg`

Creates `common/analyze.py` with the shared analyze phase skeleton. Defines `AnalyzeCfg` as a `TypedDict` with injected `load_vecs_fn`, `db_write_fn`, and `strategy_key_fn`. The skeleton owns: song/backbone iteration, pooled-vec loading, `compute_agg_mats`, `compute_retrieval_metrics`, `query_flat_head_labels`, and the `write_analyze_metrics` call (from Part A). Deletes `strategy_global_pool/_analyze.py` and `strategy_binned/_analyze.py`. Wires concrete `AnalyzeCfg` instances for global_pool, ptc, and ctp in `run.py` stubs (full `run.py` rewrite deferred to Part F).

### Part E: Report Layer Adaptation

Adapts the report layer to read from `analyze_metrics` instead of the three old tables. Replaces the `FLAT_COLUMNS` / `BINNED_COLUMNS` split in `report/_base.py` with a unified column set. Rewrites `report/_retrieval.py::query_flat` and `query_binned` into a single `query_analyze_metrics()` that filters by `strategy_type`. Adapts `section_unified_table`, `section_per_backbone`, `report/_summary.py`, and `report/_binned.py` to consume the unified DataFrame. No functional change to report output — only the data source changes.

### Part F: `run.py` Pure Wiring

Rewrites `run.py` to contain only phase dispatch — no pipeline logic. Each phase becomes a one-or-two-line delegate to the corresponding `common/` function. `_embed_phase` calls `common.embed.embed`; `_segment_phase` calls `common.segment.segment` three times (once per strategy); `_analyze_phase` calls `common.analyze.analyze` three times (once per `AnalyzeCfg`). The `_PHASES` dict structure is preserved. All skip logic, iteration, and DB writes are owned by the `common/` functions.

### Part G: Test Updates

Updates `tests/test_db.py` to remove the three old retrieval tables from `EXPECTED_TABLES`, add `analyze_metrics`, and rewrite insert/select coverage for the new EAV schema. Updates `tests/test_analysis.py` assertions from `retrieval_rows` SELECT checks to `analyze_metrics` queries. Updates `tests/test_report.py` fixtures and assertions for the unified DataFrame shape. All 48 currently passing tests must continue to pass after this part.
