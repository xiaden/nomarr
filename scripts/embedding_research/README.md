# Embedding Research — Operational Notes

Research-only pipeline. This directory contains no production code; nothing here changes
production behavior. It runs its own embed/segmentation/analysis pipeline over a fixed song
corpus and emits a static HTML report for offline inspection.

- **Design contract**: see `CONTRACTS.md` (the authoritative module/API reference).
- **Findings log**: see `FINDINGS.md` (per-run conclusions, decisions, final semantics).

> **Current (corrective pass)**: the configuration loader in `helpers/toml.py` is strict —
> `research_config.toml` describes ONLY the executable current `[pipeline]` (EffNet default;
> explicit MusicNN opt-in) and `[analysis]` settings; a missing/malformed/schema-invalid file
> raises a named error, never warn-and-return `{}`. Thresholds have exactly ONE semantics — finite
> direct L2 between normalized unit vectors, `configured == effective` — via
> `helpers/thresholds.py` (`resolve_threshold`, `canonical_float`, `canonical_config_hash`,
> `config_encoder_version`). `std_scaled`/calibration/p50 and all old config sections are removed.
> Whole-tree deletion surfaces owned by later plans are inventoried in `CONTRACTS.md` §
> "Plan A deletion inventory".

## Primary experiment scope (follow-on)

The default primary experiment is deliberately narrow (see `CONTRACTS.md`):

- **backbone**: `effnet` only by default; MusicNN is enabled only by explicit selection
  (`backbones=["effnet","musicnn"]`) and is never part of default runs.
- **representation**: the active catalog is the COMPACT canonical `seg_config` rows under the single
  finite direct-L2 semantics (`configured == effective`); there is no flat/PTC/CTP strategy baseline
  and no copied-vector representation. Winner/delta baselines are chosen deterministically per
  `(backbone, sim_metric, k, metric)` as the lowest `(canonical_config_id, strategy_key)` active
  catalog class after collapse — never a synthesized flat medoid baseline.
- **primary score variant**: `max_per_candidate_segment` — patch-count-weighted, deduplicated, with
  collision/winner/cosine/contribution traces and explicit tie/collision ambiguity variants.
- **CTP is hard-disabled and its legacy surface is DELETED** (Plan A removed the `[archival_ctp]`
  config switch; Plan E P1-S5 deleted the retained CTP module/cache/table inventory): a default run
  performs no CTP inference, writes no CTP caches/rows, and never includes CTP in primary
  winner/delta rows.
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
| `head-analysis` | CPU head pooling/medoid over the shared catalog boundary membership → provenance (no classifier topology) | **yes** |
| `report` | render results + provenance (never infers) | **yes** |

Only `ingest`, `embed`, and `infer-heads` may discover audio, load models, create ML sessions, or run
inference (CPU or CUDA). The five derived phases (`catalog`…`report`) consume only manifests,
registries, DuckDB catalog rows, and frozen stream/head artifacts; each runs with audio/model
directories, ONNX sessions, and CUDA entirely absent, and their runner bodies import only CPU-only
modules (enforced structurally and by call-level sentinel tests in
`tests/test_phase4_dispatch_boundaries.py`).

The old pipeline names `stratify`, `segment`, `classify`, and `head` are **retired**: they are not
phases and are rejected loudly by the CLI (never silently aliased, exit code `2`). Stratification is an explicit
catalog input/config step (selects/generates the corpus + config surface before the per-song pass),
not a phase. The legacy orchestration functions were **deleted** in the Plan E P1-S3 hard cut
(superseded run.py orchestration/loaders/model cache and legacy phase wrappers are gone). The
remaining legacy module/table surfaces (`classify.py`, `head_pooling.py`, `strategy_*/`, legacy
`cache/*` + `cache_identity.py`, dead DB table DDL + writer modules, and the legacy report/CLI
vocabulary) were **deleted or retained-stripped** in the Plan E P1-S5 hard cut — see CONTRACTS.md's
deletion inventory for the per-row EXECUTED dispositions.

### Maintenance (explicit, not phases)

- `python run.py verify [--strict]` audits current-format artifacts: payload/manifest/digest/shape/
  finite/commit identity against the filename grammar, plus the selected current catalog (manifest /
  open / WAL). `verify` **owns** read-write WAL recovery/checkpoint of a WAL-bearing current catalog
  and reports corruption; `--strict` freshly rehashes every current payload so a same-size tamper is
  caught. Exit `1` on refusal.
- `python run.py reindex` is a thin public wrapper over `reconcile_current_manifests`: it walks only
  current filesystem sources and rebuilds the registry/cache/corpus metadata; it never opens
  audio/models/ONNX/CUDA/sessions/segmentation.
- `python run.py cleanup --scope {staging|stray|views}` report-then-remove **only** current-format
  candidates from the filename grammar + manifest relationships: `staging` (catalog
  `.staging-*` dirs + `.staging/*.tmp` leftovers), `stray` (digest-named payloads with no sibling
  manifest + unselected current-format catalog dirs), `views` (disposable views). `--dry-run` is the
  default for `staging`/`stray`. Legacy/bare/`.vN` names are never classified or removed. The obsolete
  `dead`/`archival`/`analysis-run` scopes are removed from the CLI and their module-level table/cache
  deletion was completed in Plan E P1-S5.
- `python run.py reset --scope analysis` removes only the disposable `research.duckdb`(+WAL) and
  disposable views, byte-preserving `corpus/`, `streams/`, `heads/`, `audio_masks/`,
  `observation_commits/`, and `catalogs/`. Invalid scope exits nonzero. There is no global reset that
  deletes tier 1/2 data.

A single exclusive run lock guards every DB/artifact-mutating branch (all phases + all four
maintenance commands). Lock file at `OUTPUT_ROOT/.run-lock` (local) or local temp keyed by a hash of
the resolved DB path (non-local output root); contention exits `2`.

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
  recorded as `empty`, never corrupt.

## Required generated outputs

After a full run the following must exist under `{OUTPUT_ROOT}` (default
`scripts/outputs/embedding_research`):

| Output | Location |
| --- | --- |
| Report data | `{OUTPUT_ROOT}/report/report.json` |
| Rendered report | `{OUTPUT_ROOT}/report/report.html` |
| Research DB (DuckDB) | `{OUTPUT_ROOT}/research.duckdb` |
| Frozen streams + aligned head streams (registries + stored sidecars) | `streams/` under `{OUTPUT_ROOT}`, recorded in `stream_registry` / `head_stream_registry` |
| Compact segmentation-catalog snapshot (published durable catalog) | `catalogs/<catalog-id>/catalog.duckdb` + `catalog.manifest.json`, selected by `catalogs/current.json` (staged at `catalogs/.staging-<run_id>/catalog.duckdb` before publish) |
| Materialized search views | `views/<keyset_hash>/` under the stream-store root, refs in `run_provenance.view_refs` |
| Run-scoped analyze metrics | `analyze_metrics` rows (`run_id`) in `research.duckdb` |
| Run provenance | per-phase `run_provenance` rows in `research.duckdb` |

The following legacy cache paths were **deleted** in the Plan E P1-S5 hard cut (Waves 1–2b); they
are not required outputs and are never written or read by a default run:

- flat pooled / medoid vector caches, binned PTC segment caches, binned CTP segment caches
  (`cache/`), plus `cache_identity.py` and its `cache_semantics_tag` semantics-tag grammar.

CTP caches are additionally hard-disabled and non-runnable (Plan A removed the `[archival_ctp]`
switch; the strict loader rejects the section), so they can never feed primary rows.

## Immutable filesystem artifacts and reindex (Plan B, landed)

Streams, masks, and heads are immutable, self-describing filesystem artifacts (Plan B corrective
pass); the DuckDB registries are a rebuildable index/cache, never the source of truth. Directory
layout under `{OUTPUT_ROOT}`:

| Family | Payload | Sibling manifest |
| --- | --- | --- |
| `streams/` | digest-named float32 patch matrix `<sid>.<bb>.<64-hex-sha256>.npy` | `.json` manifest (kind `stream`) |
| `audio_masks/` | digest-named `uint8` mask (length `patch_count`, `1 = searchable`) `.npy` | `.json` manifest (kind `mask`) |
| `heads/` | digest-named concatenated head-suite `.npz` | `.json` manifest (kind `head`) |
| `observation_commits/` | commit marker `<sid>.<bb>.<64-hex>.json`, written **last** | — |

- **Grammar / immutability.** The only payload grammar is `<song_id>.<backbone>.<64-hex-lowercase-sha256>.<suffix>`; bare and `.vN` names are never written or parsed (`parse_artifact_name` is the digest-only parser). Publication is staged `.tmp` write → `fsync(file)` → close → atomic rename → `fsync(dir)`; bytes at an existing digest are never replaced (content-addressed, no-replace). A registry row/status (`pending`/`ready`/`missing`/`corrupt`) reflects a validated current group; the rows/columns (`STREAM_REGISTRY_COLUMNS`/`HEAD_STREAM_REGISTRY_COLUMNS`, `STREAM_TABLE`/`HEAD_STREAM_TABLE`, `row_tuple`/`from_row`) remain as cache until Plans C/E migrate their consumers.
- **Mask semantics v1** (`audio_masks/`): pinned `essentia_rms_dbfs_v1`, `-60 dBFS`, two-frame silent-run removal, `fraction_active_ge 0.5`, two-patch hysteresis; derived via production `get_params`/`compute_log_mel`/`extract_patches` plus the sole approved frozen replay of frame-range arithmetic. Zero model/session/ONNX/CUDA for (re)derivation.
- **Heads.** `infer-heads` publishes one immutable, digest-named `.npz` + manifest per song/backbone with the complete canonical head inventory, exact committed-stream `patch_count` alignment, finite/dimension checks, and manifest provenance. `HeadStreamStore.batch_gather(song_id, backbone, source_patch_indices, *, forbid_duplicates=False) -> np.ndarray` returns validated float32 `[N, total_dim]` with columns concatenated in canonical head order (source-index gather).
- **Current-reader seam.** Retained current-format readers resolve current payloads through the single
  `CurrentStreamResolver`/`make_current_stream_resolver` seam (`streams/store.py`, re-exported from `streams/__init__.py`): the registry `artifact_ref` is used only as a cache lookup, and the resolver resolves a row-`ready` cache entry whose current self-describing manifest and payload validate through `StreamStore.lookup`/`batch_gather`. Observation-commit group authority is NOT enforced by the resolver itself — it is enforced by the group publication/readiness flow (`observation_group_ready`) and by reindex; production embed always publishes the observation group before reconcile, so every production-ready row is group-committed. Absent, non-`ready`, or corrupt payloads fail closed (return `None`).
- **Reindex.** `streams/reindex.py` exposes `reconcile_current_manifests(root, con)` and the public `reindex(root, con)` maintenance wrapper. They walk only current-format digest manifests/commit markers (plus optional `corpus/`/`catalogs/` manifests), validate refs/digests/shape/dtype/finite/alignment/commit-readiness/catalog WAL state, and rebuild the retained registry cache rows from the filesystem after a DB deletion. They refuse corrupt/incomplete/mismatched/WAL-bearing state and never open audio/models/ONNX/CUDA, parse old names, or rerun segmentation. Reindex is exposed as the `streams.reindex` module API (`reconcile_current_manifests`/`reindex`); CLI wiring is deferred to Plan E.
- **References / timestamps.** Payloads, manifests, commit markers, and registry rows carry only root-relative artifact refs; timestamps are integer milliseconds. Same-run ordering is payload/manifest/commit first, then the validated registry cache row, before any retained reader consumes the group.

Registry row/status consumers (`catalog.py`, `catalog_identity.py`, `db/segmentation.py`,
`catalog_report.py`, `db/stream_registry.py`) pass against the retained cache contract unchanged.
The legacy reader/module surfaces (`classify.py`, `common/segment.py`, `strategy_binned/`,
`strategy_global_pool/`, CTP surfaces, and legacy run orchestration) were **deleted** in the Plan E
P1-S5 hard cut.

## Report contract (seven sections, active catalog only)

The `report` phase renders exactly seven sections in this order — `summary`, `corpus`, `analysis`,
`winners`, `head-analysis`, `provenance`, `efficiency` — with catalog-only active rows and no
inference:

- `summary` — active catalog-result status per backbone (winner / delta / factor summary, or an
  explicit empty-active-results message).
- `corpus` — active songs / corpus health.
- `analysis` — ONLY `analyze_metrics` rows with `strategy_type == 'catalog'`: run_id / sim_metric / k
  / metric / value plus catalog strategy identity, score variant, scoring-semantics version,
  view-content-hash provenance, canonical config id, and sorted alias ids.
- `winners` — deterministic winner / delta / factor tables per backbone. The baseline per
  `(backbone, sim_metric, k, metric)` is the lowest `(canonical_config_id, strategy_key)` active
  catalog class after collapse; the winner is the highest finite metric with `strategy_key` tie-break;
  `delta = winner - baseline`. Aliases are sorted and never duplicate score rows.
- `head-analysis` — canonical `head_phase_provenance` per supported backbone with finite / status /
  coverage and provenance.
- `provenance` — active `run_provenance`, command lines, hashes, warnings, reuse/refusal decisions,
  and limitations.
- `efficiency` — retained `phase_timings`.

Emitted keys are active-only; no emitted section/table ID, title, key, warning, or value uses
forbidden legacy vocabulary or a retired phase name. See `CONTRACTS.md` §"Report contract" for the
exact section surface.

## Numerical fixture

**Superseded (Plan E P1-S5, 2026-09-05).** The three legacy weighted hypotheses (`target_weighted`,
`bidirectional_weighted`, `normalized_mean_pair_weighted`) and their exact fixture — previously
pinned in `tests/test_weighted_scoring.py` — were DELETED in the P1-S5 hard cut along with
`strategy_binned/_weighted.py`; the weighted reductions and that test file no longer exist (see
`CONTRACTS.md`'s deletion inventory for the per-row EXECUTED dispositions). The primary score remains
`max_per_candidate_segment` (see `CONTRACTS.md` and `tests/test_scoring_harness.py`).

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
python -m pytest scripts/embedding_research/tests/test_toml.py -q
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

The suite pins the fixtures, schema DTOs, score-harness/ambiguity semantics, and corpus identity
above. Keep it green; do not weaken existing
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

> **Superseded (Plan E P1-S5, 2026-09-05):** the tables/caches/writers below marked [Archival]/[Dead]
> were PHYSICALLY REMOVED in the P1-S5 hard cut — the 13-table DDL drop plus `db/binned.py`,
> `db/truncation.py`, `db/stratify.py`, `cache/*`, `cache_identity.py`, `classify.py`,
> `head_pooling.py`, `strategy_ctp/`, `strategy_binned/`, `strategy_global_pool/`,
> `common/analyze.py`, `common/stratify.py` deletion, and the legacy `report/_*.py` migration to the
> seven-section catalog contract. The current 10-table schema is listed in the "Required generated
> outputs" table and `CONTRACTS.md`; the authoritative deletion inventory with per-row EXECUTED
> dispositions is `CONTRACTS.md`'s Plan A deletion inventory. Only the [Active] rows below remain
> current.

### DuckDB tables (`db/_schema.py`)

**[Active] — live writer/reader in a default run:**

- `songs` — corpus rows (`upsert_song`, `load_all_songs`).
- `analyze_metrics` — run-scoped aggregate metrics (`db/flat.write_analyze_metrics`,
  `db/analyze_scope.write_catalog_analyze_rows`).
- `song_retrieval_metrics` — per-song aggregate lenses (`write_song_retrieval_metrics`).
- `head_phase_provenance` — canonical current head rows only (no legacy/archival partition).
- `phase_timings` — elapsed wall-clock per phase (`upsert_phase_timing`).
- `stream_registry` / `head_stream_registry` — frozen sidecar registries.
- `run_provenance` — per-phase run rows, incl. `retained` flag + `view_refs`.
- `corpus_state` — singleton post-run corpus state.
- `catalog_metadata` — metadata-only singleton.

  > **Note — the segmentation catalog is NOT a DuckDB table here.** The five *compact*
  > catalog tables (`catalog_metadata` / `seg_config` / `catalog_song` / `seg_meta` /
  > `run_provenance`) live inside published FILESYSTEM snapshot files
  > (`catalogs/<catalog-id>/catalog.duckdb` + `catalog.manifest.json`, selected by
  > `catalogs/current.json`), not in `research.duckdb`. The old `research.duckdb`
  > `seg_config`/`seg_meta`/`seg_membership` tables were removed (corrective pass P1-S12).
  > `stream_registry` / `head_stream_registry` / `run_provenance` + `catalog_metadata` here are
  > rebuildable registries/provenance only.

**[Archival] — legacy-compatibility rows inside an active table:**

- `analyze_metrics` rows with `run_id='legacy'` — read-only, excluded from active
  coverage, protected from normal reset / view GC.

**[Historical — Plan E P1-S5.]** The twelve legacy PK/UNIQUE tables previously classed [Dead]
(`pooled_vecs`, `head_results`, `head_agreement_rows`, `binned_pair_sims`, `patch_features`,
`binned_classify_ctp`, `binned_ctp_vecs`, `binned_ptc_ctp_metrics`, `head_sim_corr_rows`,
`truncation_robustness_rows`, `binned_calibration`, `binned_song_stats`) were DROPPED in the Plan E
P1-S5 hard cut along with their dead writers (`db/binned.py`, `db/truncation.py`); none remains in
any DuckDB table today. See the banner above and `CONTRACTS.md`'s deletion inventory for the per-row
EXECUTED dispositions.

### Filesystem caches (`cache/`)

**[Historical — Plan E P1-S5.]** The `cache/` directory (`cache/flat_heads.py`,
`cache/flat_vecs.py`, `cache/binned_ptc*.py`, `cache/binned_ctp*.py`) and
`cache_identity.py` were DELETED in Plan E P1-S5 (the corrective-pass hard cut).  No
analysis cache remains; the sole immutable embedding / aligned-head source is the frozen
stream + head-stream sidecars under `streams/`, which the `catalog` / `head-analysis`
phases read directly.

### Writers / APIs

**[Active]:** `common/embed.py` sidecar producer; `common/infer_heads.py`;
`common/head_analysis.py` canonical CPU runner `run_shared_catalog_head_analysis`
(writes `head_phase_provenance` only);
`common/catalog_analysis.py` + `db/analyze_scope.write_catalog_analyze_rows`;
`search_views.materialize_search_view` (disposable view writer);
`db/flat.write_analyze_metrics`; report readers (`report/_*.py`, DB scalars + manifests only).

**[Historical — Plan E P1-S5.]** The modules previously listed as [Archival] — `classify.py`
(`run_shared_ptc_head_pooling`), `head_pooling.py`, `strategy_ctp/segment_fn.py`, and
`strategy_binned/_optimize` (`optimize_std_threshold` / `_eval_threshold`) — and as [Dead] —
`db/binned.upsert_calibration` / `upsert_binned_song_stats`, `cache_identity.matrix_cache_identity` /
`versioned_cache_root`, and the legacy flat/PTC/head cache writers — were DELETED in the Plan E P1-S5
hard cut; none is retained (`SCORING_SEMANTICS_VERSION=1` remains the live scoring-semantics version,
now owned by `common/head_analysis.py`). Only the [Active] writer set above remains current. See the
banner above and `CONTRACTS.md`'s deletion inventory for the per-row EXECUTED dispositions.

### Disposable search views (`views/<keyset_hash>/`)

**[Active / regenerable]** — always rebuilt for a run, never the source of truth; keyed/content-hashed
and anchored in `run_provenance.view_refs`. GC (`cleanup --scope views`) may delete only views not
referenced by a retained run.

### Reset scopes (`cleanup.py`; wired to the CLI as `cleanup --scope ...` / `reset --scope ...`)

`cleanup_current` accepts exactly the scopes `staging`, `stray`, and `views`; `reset` accepts exactly
`analysis`. The obsolete `dead`/`archival`/`analysis-run` scopes and their module-level table/cache
deletion were removed in Plan E P1-S5.

| Command | Scope | Deletes | Requires confirmation | Protected |
| --- | --- | --- | --- | --- |
| `cleanup` | `staging` | aged `.staging/*.tmp` leftovers + stale staging payload dirs (`.staging-<run_id>/`) | no | retained runs |
| `cleanup` | `stray` | digest-named payloads with no sibling manifest + unselected current-format catalog dirs | no | retained / current-format referenced |
| `cleanup` | `views` | disposable views not referenced by retained provenance | no | retained-run-referenced views |
| `reset` | `analysis` | disposable `research.duckdb`(+WAL) + disposable views | no | `corpus/`, `streams/`, `heads/`, `audio_masks/`, `observation_commits/`, `catalogs/` (byte-preserved) |

`--dry-run` is the default for `cleanup` `staging`/`stray`. Legacy/bare/`.vN` names are never
classified or removed. No default/global reset of Tier 1/2 baseline/corpus results; an artifact
outside the current inventory is unclassified and never deleted.
