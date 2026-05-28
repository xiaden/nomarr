# embed-phase-extraction — Contracts Ledger

**Feature:** Embed Phase Extraction & Common Pipeline  
**Design doc:** `artifacts/designs/pending/DD-embed-phase-extraction.md`  
**Parts:** `artifacts/designs/parts/embed-phase-extraction/README.md`

---

## Architectural Rules (from copilot-instructions.md)

- Research scripts have no layer enforcement — `scripts/embedding_research/` is self-contained
- No imports from `nomarr.*` except in `common/embed.py` (ONNX session via `nomarr.components.ml.onnx`)
- `db/` never imports from strategy packages
- DB is a research tool — reset semantics, no migrations

---

## Collections & Methods

> Populated after each plan is validated and merged.

### Part A — DB Schema & Write/Read API

- [ ] `analyze_metrics` table DDL
- [ ] `write_analyze_metrics(con, strategy_key, strategy_type, sim_metric, k, metrics: dict) -> None`
- [ ] `load_analyze_metrics(con) -> pd.DataFrame`
- [ ] `query_analysis_done(con) -> set[tuple]`

**Table DDL (`db/_schema.py`):**
```sql
CREATE TABLE IF NOT EXISTS analyze_metrics (
    strategy_key  TEXT    NOT NULL,
    strategy_type TEXT    NOT NULL,
    sim_metric    TEXT    NOT NULL,
    k             INTEGER NOT NULL,
    metric        TEXT    NOT NULL,
    value         DOUBLE,
    PRIMARY KEY (strategy_key, sim_metric, k, metric)
);
```

**Concrete signatures:**
- `write_analyze_metrics(con, strategy_key: str, strategy_type: str, sim_metric: str, k: int, metrics: dict) -> None`
- `load_analyze_metrics(con) -> pd.DataFrame` — wide-pivoted, sorted by `disc_general DESC`
- `query_analysis_done(con) -> set[tuple[str, str, int]]` — returns `(strategy_key, sim_metric, k)` tuples

**Deleted (no longer exported):** `upsert_retrieval`, `upsert_binned_retrieval`, `upsert_binned_retrieval_bulk`, `upsert_ctp_retrieval_bulk`, `purge_stale_retrieval_rows`, `retrieval_rows_exist`, `query_binned_analysis_done`, `query_ctp_analysis_done`, `load_retrieval_flat`, `load_retrieval_binned`, `BinnedRetrievalRow`, `CTPRetrievalRow`

### Part B — Extract `common/embed.py`

**Plan:** `artifacts/plans/pending/TASK-embed-phase-extraction-B-common-embed.md`

- [x] `common.embed.embed(con, *, song_ids: frozenset[str] | None, force: bool, backbones: list[str] | None, device: str) -> None`
- [x] `common.embed._embed_song_raw(path, backbone_name, backbone_cfg, load_audio_fn, preprocess_fn, session, run_in_batches_fn, batch_size, con, *, force: bool) -> bool`
- [x] `strategy_global_pool.embed` — stub delegating to `common.embed.embed` + pooling loop (deleted in Part C)

**nomarr import constraint:** Only `common/embed.py` imports from `nomarr.components.ml.*` in `scripts/embedding_research/`.

### Part C — Segment Skeleton & Strategy Thin Files

**Plan:** `artifacts/plans/pending/TASK-embed-phase-extraction-C-segment-skeleton.md`

- [x] `SegmentFn = Callable[[np.ndarray, str, str], dict[str, np.ndarray]]` (patches, backbone, strategy_name → result dict)
- [x] `common.segment.segment(con, segment_fn: SegmentFn, strategy_names: list[str], *, song_ids: frozenset[str] | None = None, force: bool = False, backbones: list[str] | None = None, extra_cfg: dict | None = None) -> None`
- [x] `extra_cfg` keys consumed by skeleton: `skip_check_fn(sid, backbone, strategy_name) -> bool`, `cache_write_fn(sid, backbone, strategy_name, result) -> None`
- [x] `strategy_global_pool.segment_fn.segment_fn(patches: np.ndarray, backbone: str, strategy_name: str) -> dict[str, np.ndarray]` — returns `{strategy_name: STRATEGIES[strategy_name](patches)}`
- [x] `strategy_global_pool.segment_fn.STRATEGY_NAMES: list[str]` — `list(STRATEGIES.keys())`
- [x] `strategy_global_pool.segment_fn.SKIP_CHECK_FN` — delegates to `cache.flat_vecs.is_done()`
- [x] `strategy_global_pool.segment_fn.CACHE_WRITE_FN` — delegates to `cache.flat_vecs.save_pooled()`
- [x] `strategy_ptc.segment_fn.make_segment_fn(con) -> SegmentFn` — factory closing over `con` for `_load_cached_calibration`
- [x] `strategy_ptc.segment_fn.STRATEGY_NAMES: list[str]` — `[f"ptc_{bin_mode}_{std_thresh:.2f}" for bin_mode in BIN_MODES for std_thresh in STD_THRESHOLDS]`
- [x] `strategy_ptc.segment_fn.SKIP_CHECK_FN` — delegates to `cache.binned_ptc.list_done_keys()`
- [x] `strategy_ptc.segment_fn.CACHE_WRITE_FN` — delegates to `cache.binned_ptc.save()`
- [x] `strategy_ctp.segment_fn.make_segment_fn(head_sessions: dict[str, object], run_in_batches_fn) -> SegmentFn` — factory closing over sessions
- [x] `strategy_ctp.segment_fn.STRATEGY_NAMES: list[str]` — `[f"ctp_{head_name}_{bin_mode}_{std_thresh:.2f}" for head_name in sorted({head for head_map in HEADS.values() for head in head_map} or HEAD_LABELS.keys()) for bin_mode in BIN_MODES for std_thresh in STD_THRESHOLDS]`
- [x] `strategy_ctp.segment_fn.CACHE_WRITE_FN` — delegates to `cache.binned_ctp.save()`

**Source note:** CTP segment logic lives in `classify.py::_process_song_head_missing()`, not `strategy_binned/_analyze.py` as DD line 71 states.

### Part D (pending)

- [x] `AnalyzeCfg` TypedDict fields in `scripts/embedding_research/common/analyze.py` — `strategy_names`, `load_vecs_fn`, `db_write_fn`, `strategy_key_fn`, `strategy_type`, `extra_cfg`
- [x] `common.analyze.analyze(con, cfg: AnalyzeCfg, *, song_ids: frozenset[str] | None = None, force: bool = False, backbones: list[str] | None = None, k: int = 10) -> None`
- [x] `GLOBAL_POOL_ANALYZE_CFG`, `PTC_ANALYZE_CFG`, `CTP_ANALYZE_CFG` wiring locations in `scripts/embedding_research/run.py`

### Part E

- `report._retrieval.query_analyze_metrics(con) -> pd.DataFrame` — runs a DuckDB `PIVOT` over `analyze_metrics` (`ON metric USING FIRST(value) GROUP BY strategy_key, strategy_type, sim_metric, k`), returns `empty_df(ANALYZE_METRICS_COLUMNS)` when `analyze_metrics` is missing or any exception occurs, and applies `_decode_strategy_key(df)` to the result before returning it.
- `ANALYZE_METRICS_COLUMNS` — unified report DataFrame contract with identity columns `strategy_key`, `strategy_type`, `sim_metric`, `k`; derived config columns `backbone`, `strategy`, `bin_mode`, `std_thresh`, `rep_a`, `rep_b`, `agg_method`; and metric columns `disc_general`, `disc_artist`, `disc_genre`, `disc_head`, `disc_score`, `mean_within`, `mean_cross`, `map_k`, `mrr`, `ndcg_k`, `recall_k`, `recall_k_genre`, `precision_k_genre`, `precision_k_head_mean`, `flat_binned_spearman`, `flat_binned_beneficial_reorder_rate`.
- Report sections no longer accept `(flat_df, binned_df)` pairs; unified section builders accept `df: pd.DataFrame` and partition internally by `strategy_type`.

### Part F (pending)

- [ ] `run._embed_phase`, `run._segment_phase`, `run._analyze_phase` signatures (pure delegates)

### Part G (pending)

- [ ] Test coverage for `analyze_metrics` CRUD
- [ ] Test coverage for unified report DataFrame shape

---

## DTOs

> Populated after each plan is validated.

_(empty — DTOs removed in Part A; EAV write path uses plain `dict`)_

---

## Decisions

- **DB reset semantics:** drop and recreate DB for schema changes; no migration ETL
- **Opaque `strategy_key`:** composite identity string; lookup is direct equality; no dimension table
- **`strategy_type` discriminator:** flat text column alongside `strategy_key` for report-layer partitioning without string parsing
- **`AnalyzeCfg` as TypedDict:** behavior-carrying config object; injected `load_vecs_fn`, `db_write_fn`, `strategy_key_fn`
- **`SegmentFn` as `Callable`:** formal protocol; consistent with existing `STRATEGIES`/`METRICS` callable registries
- **`common/` package name:** chosen over role-specific name; houses embed+segment+analyze which are all phase-level concerns
