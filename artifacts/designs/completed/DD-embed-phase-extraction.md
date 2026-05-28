# Embed Phase Extraction & Common Pipeline — Design Document

**Status:** Draft  
**Author:** research  
**Created:** 2026-05-26  
**Revised:** 2026-05-26  

**Related Documents:**
- [Embedding Research Pipeline Repair](artifacts/designs/pending/DD-embedding-research-repair.md)
- [Embedding Research Package Unification (superseded preference only)](artifacts/designs/pending/DD-embedding-research-unification.md)

---

## Scope

`scripts/embedding_research/` — new `common/` package; strategy modules reduced to thin single files; `run.py` orchestration updated. Analyze and report phases are refactored for symmetry but not functionally changed.

---

## Problem Statement

The research pipeline has two related problems:

**1. `strategy_global_pool` (née `strategy_flat`) has false ownership of ONNX inference.**
ONNX session management, audio loading, and patch sidecar production are coupled inside `strategy_global_pool/_embed.py`. The global-pool strategy's claim to uniqueness is historical, not architectural — it became the embed owner by accident of ordering, not by design.

**2. The analyze phase is massively duplicated across strategy packages.**
`strategy_global_pool/_analyze.py` and `strategy_binned/_analyze.py` both implement the same outer skeleton: iterate songs/backbones, load pooled vecs, call `compute_agg_mats`, call `compute_retrieval_metrics`, load head scores, write to DB. The only genuine differences are: which DB table to write to, which pooled-vec cache to read from, and strategy-specific config params (`bin_mode`, `std_thresh` for binned). The iteration skeleton, similarity math, and retrieval metric computation are duplicated.

**3. Adding a new strategy requires touching multiple files across two packages.**
Today: new `strategy_X/_embed.py`, `strategy_X/_analyze.py`, `strategy_X/_process.py`, wiring in `run.py`, plus understanding both embed and analyze internals. After this refactor: one thin strategy file with a single `segment_fn`, one wiring line in `run.py`. Everything else is common plumbing.

---

## Architecture

### Target Package Layout

```
scripts/embedding_research/
    common/
        __init__.py
        embed.py       # ONNX inference → patch sidecars (was strategy_global_pool/_embed.py's top half)
        segment.py     # Shared segment skeleton; strategies inject segment_fn
        analyze.py     # Shared analyze skeleton; strategies inject db_write_fn + retrieval config
    strategy_global_pool/
        __init__.py
        segment_fn.py  # One function: patches.mean(axis=0) per pooling strategy
    strategy_ptc/
        __init__.py
        segment_fn.py  # Distance-based temporal binning
    strategy_ctp/
        __init__.py
        segment_fn.py  # Score-stream temporal binning
    classify.py        # Unchanged (already standalone)
    similarity.py      # Unchanged (already shared)
    db/                # Unchanged
    cache/             # Unchanged
    run.py             # Pure wiring: call common phases in order
```

### Layer Mapping

| Component | Current Location | Target Location |
|---|---|---|
| ONNX session, audio load, preprocessing, inference, sidecar write, song registration | `strategy_global_pool/_embed.py` | `common/embed.py` |
| Segment iteration skeleton (skip logic, sidecar load, cache write, DB write) | duplicated in `strategy_global_pool/_embed.py` + `strategy_binned/_embed.py` | `common/segment.py` |
| Analyze iteration skeleton (load vecs, agg_mats, retrieval_metrics, head_scores, DB write) | duplicated in `strategy_global_pool/_analyze.py` + `strategy_binned/_analyze.py` | `common/analyze.py` |
| Global-pool segmentation logic | `strategy_global_pool/_embed.py` | `strategy_global_pool/segment_fn.py` |
| PTC segmentation logic | `strategy_binned/_embed.py` | `strategy_ptc/segment_fn.py` |
| CTP segmentation logic | `strategy_binned/_analyze.py` (CTP loop) | `strategy_ctp/segment_fn.py` |
| Phase orchestration | `run.py` (mixed with logic) | `run.py` (pure wiring only) |

---

## Common Modules

### `common/embed.py` — Backbone Inference

Owns ONNX sessions, audio loading, preprocessing, inference, sidecar writes, song registration. The only file that imports from `nomarr.components.ml.onnx` in the research pipeline.

```python
def embed(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    device: str = "cpu",
) -> None:
    """
    Run backbone ONNX inference for each (song, backbone) in scope.
    Writes raw patch tensors to PATCHES_DIR/{backbone}/{song_id}.npy.

    Skip condition: patches_path(sid, backbone).exists() and force=False.
    Postcondition: patches_path(sid, backbone).exists() for all
    (sid, backbone) in scope where audio loading succeeded.
    """
```

Skip is sidecar-keyed. Audio load failure → skip song, log error, no partial sidecar written.

---

### `common/segment.py` — Segment Phase Skeleton

Owns: song/backbone iteration, sidecar loading (`np.load(patches_path(...))`), skip-condition checking, pooled-vec cache write, DB write. Strategies inject a `segment_fn`.

```python
SegmentFn = Callable[
    [np.ndarray, str, str],   # (patches, backbone, strategy_name)
    dict[str, np.ndarray],    # {strategy_name: pooled_vec}
]

def segment(
    con,
    segment_fn: SegmentFn,
    strategy_names: list[str],
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    extra_cfg: dict | None = None,
) -> None:
    """
    Shared segment phase. Loads patch sidecars, calls segment_fn,
    writes pooled vecs to cache and DB.

    Skip condition: all (backbone, strategy) pairs already in
    embedded_configs (DB-keyed) and force=False.
    If sidecar missing for a song, skip with warning — embed phase
    has not run yet for this song/backbone.
    """
```

Strategies that produce multiple output vectors per song (e.g. global_pool produces `{mean: ..., median: ..., ...}`) return multiple keys; `common/segment.py` writes each key to cache independently.

---

### `common/analyze.py` — Analyze Phase Skeleton

Owns: song/backbone iteration, pooled-vec loading from cache, `compute_agg_mats`, `compute_retrieval_metrics`, `query_flat_head_labels` load, DB write. Strategies inject a `db_write_fn` and retrieval config.

```python
AnalyzeCfg = TypedDict("AnalyzeCfg", {
    "strategy_names": list[str],
    "load_vecs_fn": Callable,      # how to load pooled vecs for this strategy
    "db_write_fn": Callable,       # which DB table to write to
    "extra_cols": dict,            # strategy-specific retrieval row fields (e.g. bin_mode, std_thresh)
})

def analyze(
    con,
    cfg: AnalyzeCfg,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    k: int = 10,
) -> None:
    """Shared analyze phase. Runs retrieval metrics and writes rows to DB."""
```

The `extra_cols` dict carries strategy-specific fields (e.g. `{"bin_mode": "ptc", "std_thresh": 1.2}`) that are forwarded into the `strategy_key` construction. The analyze skeleton does not need to know about `bin_mode` or `std_thresh` directly.

With the unified `analyze_metrics` EAV table (see Unified Metrics Schema below), `db_write_fn` is identical for all strategies: upsert one `strategy_configs` row, then INSERT one `analyze_metrics` row per metric. The only strategy-specific concern is `strategy_key` construction, handled by an injected `strategy_key_fn`.

---

## Strategy Files

After refactor, each strategy contains only its unique segmentation logic.

### `strategy_global_pool/segment_fn.py`

```python
from scripts.embedding_research.pooling import STRATEGIES

def segment_fn(
    patches: np.ndarray,  # [n_patches, embed_dim]
    backbone: str,
    strategy_name: str,
) -> dict[str, np.ndarray]:
    """Global pool: apply each pooling function to all patches → 1 vec per strategy."""
    pool_fn = STRATEGIES[strategy_name]
    return {strategy_name: pool_fn(patches)}

STRATEGY_NAMES = list(STRATEGIES.keys())  # ["mean", "median", ...]
```

The entire unique logic is one line per pooling variant. Everything else — iteration, sidecar loading, cache write — lives in `common/segment.py`.

### `strategy_ptc/segment_fn.py`

```python
def segment_fn(
    patches: np.ndarray,
    backbone: str,
    strategy_name: str,   # encodes std_thresh
) -> dict[str, np.ndarray]:
    """PTC: distance-based temporal binning → N segment vecs."""
    # current: _distance_bin_segments() logic from strategy_binned/_embed.py
    ...
```

### `strategy_ctp/segment_fn.py`

```python
def segment_fn(
    patches: np.ndarray,
    backbone: str,
    strategy_name: str,   # encodes head + std_thresh
) -> dict[str, np.ndarray]:
    """CTP: score-stream temporal binning → N segment vecs."""
    # current: CTP loop logic from strategy_binned/_analyze.py
    ...
```

---

## `run.py` — Pure Wiring

After refactor `run.py` contains no pipeline logic — only phase dispatch:

```python
def _embed_phase(con, cfg):
    common.embed.embed(con, **cfg)

def _segment_phase(con, cfg):
    common.segment.segment(con, strategy_global_pool.segment_fn, GLOBAL_POOL_STRATEGY_NAMES, **cfg)
    common.segment.segment(con, strategy_ptc.segment_fn, PTC_STRATEGY_NAMES, **cfg)
    common.segment.segment(con, strategy_ctp.segment_fn, CTP_STRATEGY_NAMES, **cfg)

def _analyze_phase(con, cfg):
    common.analyze.analyze(con, GLOBAL_POOL_ANALYZE_CFG, **cfg)
    common.analyze.analyze(con, PTC_ANALYZE_CFG, **cfg)
    common.analyze.analyze(con, CTP_ANALYZE_CFG, **cfg)

_PHASES = {
    "ingest": _ingest_phase,
    "embed":   _embed_phase,
    "segment": _segment_phase,
    "classify": _classify_phase,
    "analyze": _analyze_phase,
    "report":  _report_phase,
}
```

---

## Phase Ordering

```
ingest → embed → segment → classify → analyze → report
```

- `embed` before `segment`: sidecars must exist before any strategy reads them
- `segment` before `analyze`: pooled vecs must be in cache before retrieval metrics run
- `classify` before `analyze`: head scores must be in DB before `common/analyze.py` reads them
- `embed` (global_pool segment artifacts) before binned analyze: preserved — both run in `segment` phase, before `analyze`

---

## Resume / Skip Semantics

| Phase | Skip key | Source |
|---|---|---|
| `embed` | `patches_path(sid, backbone).exists()` | filesystem |
| `segment` | `(backbone, strategy) in embedded_configs` | DB (`query_embedded_configs`) |
| `analyze` | retrieval row exists in DB | DB |

Skip semantics are unchanged from current behavior — only consolidated into `common/`.

---

## Rename: `strategy_flat` → `strategy_global_pool`

**Resolved.** The module is renamed to `strategy_global_pool`.

- Python module: `strategy_global_pool/`
- DB identifiers (`flat_head_labels`, `retrieval_rows.strategy = 'flat_mean'`) are **not renamed** — those are data contracts, not module names. The strategy values stored in DB (e.g. `'flat_mean'`, `'flat_median'`) can stay as-is or be updated via migration; that is an implementation-time decision.
- All references in `run.py`, `__init__.py`, and imports updated at implementation time.

---

## Two-Pass Confirmed

**Resolved.** `common/embed.py` writes patch sidecars; `common/segment.py` reads them for every strategy including global_pool. No single-pass optimization. Rationale: ONNX inference dominates wall-time by 2–3 orders of magnitude; the additional `np.load()` per song is negligible. Cleaner phase boundary takes priority.

---

## Design Goals

1. Every strategy is symmetric: a `segment_fn` and a wiring entry in `run.py`. No strategy owns inference or analysis infrastructure.
2. Adding a new strategy: write one `segment_fn.py`, add one `AnalyzeCfg`, add two lines in `run.py`. No touching `common/`.
3. `common/embed.py` is the single owner of the ONNX contract — the only file that imports `nomarr.components.ml.onnx` in the research pipeline.
4. `run.py` contains no pipeline logic — only phase dispatch.
5. Phase ordering guarantees are explicit and enforced by `_PHASES` ordering.

---

## Constraints

- **ADR-001 (ONNX Runtime):** ONNX stays as the inference backend. Moving inference to `common/embed.py` is scope-neutral.
- **ASR-0010 (throughput):** Two-pass flat segmentation adds negligible I/O vs inference cost. Must be verified empirically at implementation time.
- **ASR-0011 (backend-contract boundary):** `common/embed.py` accepts `device` but does not bake backend-specific assumptions beyond what `create_session()` already abstracts.
- **DD-repair ordering constraint:** global_pool-derived artifacts before binned analysis — preserved via phase ordering.
- **Sidecar format frozen:** `patches_path(sid, backbone)` → `float32 [n_patches, embed_dim]`. `common/embed.py` must write the identical format.
- **Write queue:** Binned DB write performance concern is unchanged — `common/analyze.py` must preserve async write behavior for binned writes.
- **Amplitude-based segmentation:** Confirmed dead end. Not referenced.
- **DD-embedding-research-unification superseded:** This design supersedes the unification draft's preference for strategy-owned end-to-end flows.

---

## Unified Metrics Schema

The three current retrieval tables (`retrieval_rows`, `binned_retrieval_rows`, `binned_ctp_retrieval_rows`) have identical metric columns. The only structural differences are:
- `retrieval_rows` (global_pool): no `bin_mode / std_thresh / rep_a / rep_b / agg_method`; no `flat_binned_spearman / flat_binned_beneficial_reorder_rate`
- `binned_ctp_retrieval_rows` adds `head` to the PTC key

These are replaced by a single `analyze_metrics` table.

### `analyze_metrics`

```sql
CREATE TABLE analyze_metrics (
    strategy_key  TEXT NOT NULL,      -- opaque composite key, e.g. "ctp:effnet:temporal_global:0.5:arousal"
    strategy_type TEXT NOT NULL,      -- 'global_pool' | 'ptc' | 'ctp'  (lightweight discriminator)
    sim_metric    TEXT NOT NULL,      -- 'cosine' | 'l2'
    k             INTEGER NOT NULL,
    metric        TEXT NOT NULL,      -- 'map_k' | 'mrr' | 'ndcg_k' | 'disc_score' | ...
    value         DOUBLE,
    PRIMARY KEY (strategy_key, sim_metric, k, metric)
);
```

`strategy_key` encodes the full configuration identity. `strategy_type` is a lightweight discriminator so the report layer can partition by strategy family without string parsing.

**Key construction per strategy:**

| Strategy | `strategy_key` format |
|---|---|
| global_pool | `"global_pool:{backbone}:{strategy}"` e.g. `"global_pool:effnet:mean"` |
| ptc | `"ptc:{backbone}:{bin_mode}:{std_thresh}:{rep_a}:{rep_b}:{agg_method}"` |
| ctp | `"ctp:{backbone}:{head}:{bin_mode}:{std_thresh}:{rep_a}:{rep_b}:{agg_method}"` |

### Rationale

**Why an opaque key?**
The key is known at query time — lookup is a direct equality match (`WHERE strategy_key = 'ctp:effnet:temporal_global:0.5:arousal'`), not pattern matching. Every read path in the pipeline is a full table dump into pandas with no SQL-level dimension filtering; filtering happens in Python after the load. A separate dimension table adds a join to every read with zero practical benefit. The opaque key plus `strategy_type` discriminator is sufficient.

**Why EAV for metrics rather than wide columns?**
- Strategy-specific metrics (`flat_binned_spearman`, `recall_k_genre`) become absent rows rather than NULL columns, eliminating the `_ensure_retrieval_rows_columns()` ALTER TABLE pattern currently in `db/flat.py`
- Adding a new metric is a data operation, not a schema change
- The write path loops over `compute_retrieval_metrics()` output dict directly — no per-strategy INSERT column lists
- DuckDB's `PIVOT` makes wide-format analysis easy when needed

**Write path (via `AnalyzeCfg.db_write_fn`):**

```python
def write_metrics(con, strategy_key: str, strategy_type: str, sim_metric: str, k: int, metrics: dict) -> None:
    rows = [
        (strategy_key, strategy_type, sim_metric, k, name, value)
        for name, value in metrics.items()
        if value is not None
    ]
    con.executemany(
        "INSERT OR REPLACE INTO analyze_metrics VALUES (?,?,?,?,?,?)", rows
    )
```

Every strategy calls the same function. No strategy-specific DB logic.

### Reset Semantics

This is a research script. Schema changes drop and recreate the DB — no migration ETL. Old tables (`retrieval_rows`, `binned_retrieval_rows`, `binned_ctp_retrieval_rows`) are removed from the DDL at implementation time.

---

## Migration Scope

All files that must change as part of this refactor. The planner must account for every item here.

### Files Deleted or Replaced

| File | Reason |
|---|---|
| `strategy_global_pool/_embed.py` | Split: ONNX inference → `common/embed.py`; segment fn → `strategy_global_pool/segment_fn.py` |
| `strategy_global_pool/_analyze.py` | Replaced by `common/analyze.py` skeleton |
| `strategy_binned/_embed.py` | Segment fn → `strategy_ptc/segment_fn.py` |
| `strategy_binned/_analyze.py` | Analyze loop → `common/analyze.py`; CTP fn → `strategy_ctp/segment_fn.py` |

### Files Created

| File | Content |
|---|---|
| `common/__init__.py` | Package init |
| `common/embed.py` | ONNX inference, audio load, sidecar write, song registration |
| `common/segment.py` | Segment phase skeleton + `SegmentFn` protocol |
| `common/analyze.py` | Analyze phase skeleton + `AnalyzeCfg` TypedDict |
| `strategy_global_pool/segment_fn.py` | `patches.mean(axis=0)` per pooling variant |
| `strategy_ptc/__init__.py` | Package init (rename from `strategy_binned` PTC path) |
| `strategy_ptc/segment_fn.py` | Distance-based temporal binning logic |
| `strategy_ctp/__init__.py` | Package init |
| `strategy_ctp/segment_fn.py` | Score-stream temporal binning logic |

### DB Layer (`db/`)

| File | Change |
|---|---|
| `db/_schema.py` | Remove DDL for `retrieval_rows`, `binned_retrieval_rows`, `binned_ctp_retrieval_rows`; add `analyze_metrics` DDL |
| `db/_types.py` | Remove `BinnedRetrievalRow`, `CTPRetrievalRow` DTOs (superseded by EAV write path) |
| `db/flat.py` | Remove `upsert_retrieval`, `load_retrieval_flat`, `load_retrieval_binned`, `_ensure_retrieval_rows_columns`; add `write_analyze_metrics`, `load_analyze_metrics` |
| `db/binned.py` | Remove `upsert_binned_retrieval_bulk`, `upsert_ctp_retrieval_bulk`, `query_binned_analysis_done`, `query_ctp_analysis_done`, `purge_stale_retrieval_rows`; migrate skip/done checks to use `analyze_metrics` |
| `db/__init__.py` | Update exports to reflect removed/added functions |

### Report Layer (`report/`)

| File | Change |
|---|---|
| `report/_base.py` | Replace `FLAT_COLUMNS` / `BINNED_COLUMNS` constants with unified column set from `analyze_metrics` |
| `report/_retrieval.py` | Replace `query_flat()` / `query_binned()` with single `query_analyze_metrics()`; adapt `section_unified_table`, `section_per_backbone` to unified DataFrame |
| `report/_summary.py` | Adapt summary sections that currently expect flat-vs-binned split DataFrames |
| `report/_binned.py` | Adapt binned-specific sections to load from `analyze_metrics` filtered by `strategy_type` |

### Orchestration (`run.py`)

Full rewrite to pure phase dispatch. Current logic to migrate:
- Phase guards / skip logic → owned by each `common/` phase function
- `analyze_ctp` inline call → unified via `common/analyze.py` with CTP `AnalyzeCfg`
- `_PHASES` dict structure preserved; implementations become single-line delegates

### Tests (`tests/`)

| File | Change |
|---|---|
| `tests/test_db.py` | Update `EXPECTED_TABLES` — remove old three retrieval tables, add `analyze_metrics`; rewrite insert/select coverage for new schema |
| `tests/test_analysis.py` | Update assertions from `retrieval_rows` selects to `analyze_metrics` |
| `tests/test_report.py` | Update fixtures and assertions for unified DataFrame shape |

---

## Open Questions

**OQ-3 — Can PTC and CTP share one `AnalyzeCfg` variant?**
PTC and CTP both load pooled segment vecs and write retrieval rows. The differences are: PTC reads from `cache/binned_ptc/`, CTP from `cache/binned_ctp/`; both carry `(bin_mode, std_thresh)` in `extra_cols`; CTP additionally has `head`. With the unified `analyze_metrics` EAV table, the `db_write_fn` signature is identical for both — the `strategy_key` construction is the only difference. One `AnalyzeCfg` schema with different injected `load_vecs_fn` and `strategy_key_fn` handles both. Decision deferred to implementation.

---
