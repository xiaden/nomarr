# Embedding Research — Operational Notes

Research-only pipeline. This directory contains no production code; nothing here changes
production behavior. It runs its own embed/segmentation/analysis pipeline over a fixed song
corpus and emits a static HTML report for offline inspection.

- **Design contract**: see `CONTRACTS.md` (the authoritative module/API reference).
- **Findings log**: see `FINDINGS.md` (per-run conclusions, decisions, final semantics).

## Primary experiment scope (follow-on)

The default primary experiment is deliberately narrow (see `CONTRACTS.md`):

- **backbone**: `effnet` only by default; MusicNN is enabled only by explicit selection
  (`backbones=["effnet","musicnn"]`) and is never part of default runs.
- **flat baseline**: `flat_strategies=["medoid"]` (observed global medoid); **PTC representation**:
  `rep_types=["medoid"]`.
- **primary score variant**: `max_per_candidate_segment` — patch-count-weighted, deduplicated, with
  collision/winner/cosine/contribution traces and explicit tie/collision ambiguity variants.
- **CTP is deferred/archival** (`[archival_ctp] enabled=false`): available and callable, but never
  required for the primary corpus and never in primary winner/delta rows.
- **evaluation lenses**: MAP, MRR, NDCG, Recall, and discrimination are evaluation lenses, not
  optimization objectives, and are never collapsed into one composite.

## CLI phases (explicit phase boundaries)

`python run.py <phase>` exposes **exactly eight** phase boundaries (see `CONTRACTS.md`
for the binding responsibility table and `run.py` for the runner wiring):

```
ingest -> embed -> infer-heads -> catalog -> catalog-report -> analyze -> head-analysis -> report
```

| Phase | Permitted responsibility | Runs CPU-only without audio/models/ONNX/CUDA? |
| --- | --- | --- |
| `ingest` | discover/normalize the corpus + input manifest | no (may discover audio) |
| `embed` | bounded inference + immutable streams/registry | no (loads models, runs ONNX) |
| `infer-heads` | aligned head streams | no (loads models, runs ONNX) |
| `catalog` | verify/read streams, generate/select configs, build all thresholds in one pass → catalog rows/signatures | **yes** |
| `catalog-report` | report configs/aliases/membership/outliers/medoids/structural changes | **yes** |
| `analyze` | gather disposable views + bounded exact scoring → view hashes/run-scoped metrics | **yes** |
| `head-analysis` | CPU head pooling/medoid over memberships + shared PTC → provenance (no classifier topology) | **yes** |
| `report` | render results + provenance (never infers) | **yes** |

Only `ingest`, `embed`, and `infer-heads` may discover audio, load models, create ML sessions, or run
inference (CPU or CUDA). The five derived phases (`catalog`…`report`) consume only manifests,
registries, DuckDB catalog rows, and frozen stream/head artifacts; each runs with audio/model
directories, ONNX sessions, and CUDA entirely absent, and their runner bodies import only CPU-only
modules (enforced structurally and by call-level sentinel tests in
`tests/test_phase4_dispatch_boundaries.py`).

The old pipeline names `stratify`, `segment`, `classify`, and `head` are **retired**: they are not
phases and are rejected loudly by the CLI (never silently aliased). Stratification is an explicit
catalog input/config step (selects/generates the corpus + config surface before the per-song pass),
not a phase. The legacy orchestration functions remain importable/callable for archival/test
compatibility but are unreachable from CLI dispatch.

### Maintenance (explicit, not phases)

- `python run.py cleanup --scope {staging,views,dead,archival,analysis-run} [--run-id X] [--confirm] [--dry-run]`
  removes only the requested scope (see the reset-scopes table below); `archival` requires
  `--confirm`, and `analysis-run` requires both `--run-id` and `--confirm`.  Protection of legacy
  (`run_id='legacy'`) and retained runs is honored by the library layer by default and is only
  overridden through that explicit double-confirmation path (the deliberate operator override).
- `python run.py reset [--binned-cache]` is an explicit separate maintenance command that drops the
  DB (and optionally the binned segment caches). There is no implicit/global reset of tier 1/2 data.

### Verification and strict refusal

- `--verify` runs each phase's own verification where relevant (e.g. `catalog` passes
  `verify=True` to `build_segmentation_catalog`) and, for derived phases, a post-crash rollback-only
  canary over every surviving legacy `PRIMARY KEY`/`UNIQUE` table, recording command line, software
  versions, inputs/outputs, warnings, and reuse decisions in `run_provenance`.
- Even without `--verify`, a detected post-crash signature — a surviving `<db>.wal` file or any
  `run_provenance` row with `status <> 'completed'` — auto-runs the same rollback-only canary before
  any derived-phase (`catalog`…`report`) read.
- `--strict` **requires** `--verify`. `--verify --strict` turns every recorded corruption,
  unresolved duplicate, incomplete required artifact, or canary failure into a hard phase refusal
  (nonzero exit); the run is recorded as `failed`. Under plain `--verify` the same conditions are
  recorded as warning notes and the phase continues (never blocks on a warning).
- The canary enumerates constrained tables from DuckDB metadata at runtime, probes each non-empty
  table by capturing its lexicographically-smallest key row, deleting and re-inserting it inside a
  transaction that is always **rolled back** (never committed), and treats any failure as corruption.
  On failure it blocks all `catalog`/`analyze`/`report` reads and instructs repair with
  `EXPORT DATABASE '<dir>'` then `IMPORT DATABASE '<dir>'` into a fresh DuckDB file. Empty tables are
  recorded as `empty`, never corrupt (CTP-disabled empty tables are expected).

## Required generated outputs

After a full run the following must exist under `{OUTPUT_ROOT}` (default
`scripts/outputs/embedding_research`):

| Output | Location |
| --- | --- |
| Report data | `{OUTPUT_ROOT}/report/report.json` |
| Rendered report | `{OUTPUT_ROOT}/report/report.html` |
| Research DB (DuckDB) | `{OUTPUT_ROOT}/research.duckdb` |
| Frozen streams + aligned head streams (registries + stored sidecars) | `streams/` under `{OUTPUT_ROOT}`, recorded in `stream_registry` / `head_stream_registry` |
| Materialized search views | `views/<keyset_hash>/` under the stream-store root, refs in `run_provenance.view_refs` |
| Run-scoped analyze metrics | `analyze_metrics` rows (`run_id`) in `research.duckdb` |
| Run provenance | per-phase `run_provenance` rows in `research.duckdb` |

The following legacy cache paths are **archival** — written only by legacy code paths, NOT required
outputs of a default run:

- flat pooled vectors: `{OUTPUT_ROOT}/cache/{backbone}/{strategy}/flat/{song_id}.npy`
- medoid flat vectors: `{OUTPUT_ROOT}/cache/{backbone}/medoid/flat/{song_id}.npy`
- binned PTC segment caches: `{OUTPUT_ROOT}/cache/binned_ptc/{tag}/{backbone}/{bin_mode}/{threshold}/{song_id}.npz`
- binned CTP segment caches: `{OUTPUT_ROOT}/cache/binned_ctp/{tag}/{backbone}/{head}/{threshold}/{song_id}.npz`

`{tag}` is the cache semantics tag (see `cache_identity.py` / `cache_semantics_tag`); changing it
invalidates segment caches by selecting a different root (old roots are orphaned, never deleted).
CTP segment caches are **archival**: they are produced but never feed primary rows unless
`[archival_ctp] enabled=true`.

## Baseline labels

Every winner/delta/headline claim is measured against the **explicit flat medoid baseline** for the
same backbone and K:

```
global_pool:{backbone}:medoid
```

e.g. `global_pool:effnet:medoid` and `global_pool:musicnn:medoid`. Each backbone is an independent
population with its own matching-corpus manifest and medoid; there is no cross-backbone aggregate and
no max/median/mean-across-flat fallback.

## Report tables

The report includes, per backbone:

- `winner_delta_{backbone}` — one row per `(group, metric, K)` grid cell: the deterministic winner
  (strategy key, type, value) and its delta vs the medoid baseline. 33 columns
  (`WINNER_DELTA_COLUMNS`).
- `factor_summary_{backbone}` — wins/deltas grouped by each configuration factor while retaining
  group × metric × K and the contributing strategy keys. 10 columns (`FACTOR_SUMMARY_COLUMNS`).
- Each `winner_delta_{backbone}` row carries the bounded per-pair trace summary
  (`trace_n_pairs`, `trace_numerator_sum/mean`, `trace_denominator_sum/mean`,
  `trace_collision_count`, `trace_winner_count`, `trace_retained_contributions`,
  `trace_dropped_contributions`, `trace_finite`) and the ambiguity variant
  (`winner_ambiguity_variant`), so collisions, winners, weights, cosines, and contribution
  retention stay visible.

Plus `backbone_summary` (flat medoid `disc_genre`, best binned config, `delta_vs_medoid`),
unified/per-backbone/threshold/binned-mode/head-value/head-output-shared-ptc-boundary/
head-sim-corr/flat-binned-correlation
sections. See `CONTRACTS.md` §6 for the exact section surface.

## Numerical fixture

The three **legacy weighted hypotheses** (opt-in comparison formulas, NOT the primary scoring
method — the primary score is `max_per_candidate_segment`, see `CONTRACTS.md` and
`tests/test_scoring_harness.py`) are pinned by an exact fixture in
`tests/test_weighted_scoring.py`:

```
S   = [[1, .2],
       [.4, .8]]
w_A = [1, 3]      # source (row) patch-count weights
w_B = [2, 1]      # target (column) patch-count weights
```

| Reduction | Input | Value |
| --- | --- | --- |
| `target_weighted(S, w_B)` | forward A→B | `0.6333333333` |
| `target_weighted(S.T, w_A)` | reverse B→A | `0.6000000000` |
| `bidirectional_weighted(S, S.T, w_B, w_A)` | mean of the two directions | `0.6166666667` |
| `normalized_mean_pair_weighted(S, w_A, w_B)` | globally weighted bilinear mean | `0.5833333333` |

Note `target_weighted` is directional (0.6333… vs 0.6000…); the reverse matrix is always supplied
separately, never derived by transposing the forward matrix.

## Running the tests

Full research suite:

```bash
python -m pytest scripts/embedding_research/tests/ -q
```

Early-exit equivalent (stop at first failure), as used by the quality gate:

```bash
python -m pytest scripts/embedding_research/tests/ -x -q
```

Config/doc-adjacent smoke (docs-only phases):

```bash
python -m pytest scripts/embedding_research/tests/test_toml.py scripts/embedding_research/tests/test_quality_gate.py -q
```

Byte-compile and formatter/linter checks:

```bash
python -m compileall scripts/embedding_research
ruff format --check scripts/embedding_research
ruff check scripts/embedding_research
```

Deterministic fixture report generation + validation:

```bash
python scripts/embedding_research/generate_fixture_report.py
python scripts/embedding_research/validate_fixture_report.py
```

The suite pins the fixtures, schema DTOs, score-harness/ambiguity semantics, weighted-hypothesis
fixtures, cache-identity behavior, and corpus identity above. Keep it green; do not weaken existing
assertions when extending the research docs or code. Fixture report numbers are synthetic
(see `FINDINGS.md`) unless a real model/audio run produced them.

## Maintenance — active / archival / dead inventory

This is the static artifact inventory (R14) that drives `cleanup.py`'s explicit reset scopes and
P4's canary-table enumeration. Classifications come from the caller audit in `FINDINGS.md`
"Part A audit" (2026-09-02) cross-checked against `db/_schema.py` and the live call graph (a writer
with no production caller is DEAD). An artifact not listed here is **unclassified** and `cleanup.py`
refuses to touch it.

Dispositions: **[Active]** = current producer/consumer in a default run; **[Archival]** = legacy
read-only compatibility, only under an explicit label/opt-in, never a primary input;
**[Dead]** = zero live producer and zero/only-test consumer (a `cleanup --scope dead` candidate).

### DuckDB tables (`db/_schema.py`)

**[Active] — live writer/reader in a default run:**

- `songs` — corpus rows (`upsert_song`, `load_all_songs`).
- `analyze_metrics` — run-scoped aggregate metrics (`db/flat.write_analyze_metrics`,
  `db/analyze_scope.write_catalog_analyze_rows`).
- `song_retrieval_metrics` — per-song aggregate lenses (`write_song_retrieval_metrics`).
- `stratified_corpus` — stratification subsets (`write_stratified_sids`).
- `head_phase_provenance` — canonical current head rows + `run_id='legacy'` archival rows.
- `phase_timings` — elapsed wall-clock per phase (`upsert_phase_timing`).
- `stream_registry` / `head_stream_registry` — frozen sidecar registries.
- `run_provenance` — per-phase run rows, incl. `retained` flag + `view_refs`.
- `corpus_state` — singleton post-run corpus state.
- `catalog_metadata` — metadata-only singleton.
- `seg_config` / `seg_meta` / `seg_membership` — segmentation catalog (primary schema).

**[Archival] — legacy-compatibility rows inside an active table:**

- `analyze_metrics` / `head_phase_provenance` rows with `run_id='legacy'` — read-only, excluded from
  active coverage, protected from normal reset / view GC.

**[Dead] — DDL'd, zero live writer (surviving legacy PK/UNIQUE tables; not assumed permanent, see P4
canary):**

- `pooled_vecs`, `head_results` — obsolete copied-vector / head-result tables.
- `head_agreement_rows`, `binned_pair_sims` — agreement / pair-sim side tables.
- `patch_features` — librosa audio features (producer `patch_features_done` removed in P3-S4; table
  remains DDL-only).
- `binned_classify_ctp`, `binned_ctp_vecs` — CTP-binned activation/vector tables (CTP archival-gated).
- `binned_ptc_ctp_metrics`, `head_sim_corr_rows` — divergence / head-sim correlation metrics.
- `truncation_robustness_rows` — truncation sweep (`upsert_truncation_robustness` has no caller).
- `binned_calibration` — p50 calibration (producer `strategy_binned/_calibrate.py` removed in P3-S4;
  table remains DDL-only).
- `binned_song_stats` — per-song bin stats (producers `_process._compute_song_stats` /
  `_process_group` removed in P3-S4; table remains DDL-only).

### Filesystem caches (`cache/`)

**[Active]:**

- `cache/flat_heads.py` — classifier head-output activation cache (`cache/{bb}/heads/...`), written
  by the legacy `classify.py` path; read by catalog stratification membership building
  (`common/stratify`) under a positive `[pipeline].limit` budgeted corpus and by legacy head-sim
  readers. Head analysis reads frozen aligned head-stream sidecars (`streams/`), not this cache.
- Frozen stream / aligned head-stream sidecars (`streams/`), the sole immutable embedding source.

**[Archival] — legacy threshold-specific copied vectors, read-only golden/compat:**

- `cache/flat_vecs.py` — flat pooled sidecars (`cache/{bb}/{strategy}/flat/{sid}.npy`), superseded by
  frozen flat medoid head streams.
- `cache/binned_ptc.py`, `cache/binned_ptc_heads.py` — legacy PTC threshold copies incl. `pool_*_raw/norm`.
- `cache/binned_ctp.py`, `cache/binned_ctp_heads.py` — CTP caches, only accrued under
  `[archival_ctp] enabled=true`.

**[Dead] — obsolete copies/writers (within archival payloads, `--scope dead`):**

- threshold-specific `pool_medoid_raw` / `pool_medoid_norm` copied vectors and obsolete threshold
  vector copies (superseded by observed source-patch medoids); dead matrix/cache writers.

### Writers / APIs

**[Active]:** `common/embed.py` sidecar producer; `common/infer_heads.py`;
`common/head_analysis.py` canonical CPU runner (writes `head_phase_provenance` only);
`common/catalog_analysis.py` + `db/analyze_scope.write_catalog_analyze_rows`;
`search_views.materialize_search_view` (disposable view writer); `common/analyze.py` analyze +
`db/flat.write_analyze_metrics`; report readers (`report/_*.py`, DB scalars + manifests only).

**[Archival] (legacy-interim compatibility, retained not CLI-reachable; retirement is a separate follow-on):** `classify.py`
`run_shared_ptc_head_pooling` (live-ONNX/inclusive-range LEGACY interim) and `run.py` legacy `_head_phase`
glue; `head_pooling.py` LEGACY-interim re-export; `strategy_ctp/segment_fn.py` (archival, phase-gated);
PTC `std_scaled` explicit legacy-fidelity semantics; `strategy_binned/_optimize.optimize_std_threshold`
/ `_eval_threshold` (manual-only, tests-only).

**[Dead]** (zero production callers; `cleanup --scope dead` candidates): `db/binned.upsert_calibration`
/ `upsert_binned_song_stats` (their producers `strategy_binned/_calibrate.py` and
`_process._compute_song_stats` / `_process_group` were removed in P3-S4, leaving the tables DDL-only);
`cache_identity.matrix_cache_identity` / `versioned_cache_root` (tests-only; `SCORING_SEMANTICS_VERSION=1`
is Active); legacy flat/PTC/head cache writers that only ever wrote dead payloads.

### Disposable search views (`views/<keyset_hash>/`)

**[Active / regenerable]** — always rebuilt for a run, never the source of truth; keyed/content-hashed
and anchored in `run_provenance.view_refs`. GC (`cleanup --scope views`) may delete only views not
referenced by a retained run.

### Reset scopes (`cleanup.py`; wired to the CLI as `cleanup --scope ...`)

| Scope | Deletes | Requires confirmation | Protected |
| --- | --- | --- | --- |
| `staging` | aged `.staging/*.tmp` + stale staging payloads | no | retained runs |
| `views` | disposable views not referenced by retained provenance | no | retained-run-referenced views |
| `dead` | only statically-classified Dead artifacts | no | nothing unclassified |
| `archival` | archival tables/caches/artifacts | **yes** (loud) | nothing unclassified |
| `analysis-run RUN_ID` | exactly that run's `analyze_metrics` rows | **yes** (`--confirm`; also requires `--run-id`) | legacy + retained runs (library default); deleted only via the explicit `--run-id` + `--confirm` override |

No default/global reset of Tier 1/2 baseline/corpus results; an artifact outside this inventory is
unclassified and never deleted. Sidecars (search-view payloads, per-stream auxiliaries) are preserved
on stream/catalog reset unless the explicit scope says otherwise.
