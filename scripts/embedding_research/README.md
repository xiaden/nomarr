# Embedding Research — Operational Notes

Research-only pipeline. This directory contains no production code; nothing here changes
production behavior. It runs its own embed/segmentation/analysis pipeline over a fixed song
corpus and emits a static HTML report for offline inspection.

- **Design contract**: see `CONTRACTS.md` (the authoritative module/API reference).
- **Findings log**: see `FINDINGS.md` (per-run conclusions, decisions, final semantics).

> **Current (corrective pass)**: the configuration loader in `helpers/toml.py` is strict —
> `research_config.toml` describes ONLY the executable current `[pipeline]` (EffNet default;
> explicit MusicNN opt-in) and `[analysis]` settings; a missing/malformed/schema-invalid file
> raises a named error, never warn-and-return `{}`. Thresholds have exactly ONE application
> semantics — `direct_distance`, `configured == effective` (stored in `seg_config.threshold_semantics`)
> — resolved via `helpers/thresholds.py` (`resolve_threshold`, `canonical_float`, `canonical_config_hash`,
> `config_encoder_version`). The executed distance metric is never stored; it is derived from the config's
> `bin_mode` via `helpers/binning.DIST_FNS` (`l2` for `temporal_global`, `chebyshev` for `temporal_perdim`).
> `std_scaled`/calibration/p50 and all old config sections are removed.
> Whole-tree deletion surfaces owned by later plans are inventoried in `CONTRACTS.md` §
> "Plan A deletion inventory".

## Primary experiment scope (follow-on)

The default primary experiment is deliberately narrow (see `CONTRACTS.md`):

- **backbone**: `effnet` only by default; MusicNN is enabled only by explicit selection
  (`backbones=["effnet","musicnn"]`) and is never part of default runs.
- **representation**: the active catalog is the COMPACT canonical `seg_config` rows under the single
  threshold-*application* semantics `direct_distance` (`configured == effective`, stored in
  `seg_config.threshold_semantics`); the executed distance metric is never stored (derived from `bin_mode`
  via `helpers/binning.DIST_FNS`, see below); there is no flat/PTC/CTP *strategy* baseline,
  no copied-vector representation, and no synthetic (coordinate-wise) medoid. Segmentation dispatches
  the two retained temporal `bin_mode` values through `helpers/binning.DIST_FNS` — `temporal_global`
  → direct unit-vector L2 (`l2`), `temporal_perdim` → per-dimension Chebyshev (`chebyshev`) — and fails
  closed on unknown modes and on the retired `'direct'` mode (advertised metric == executed metric by
  construction). `temporal_global`/L2 is the sole PRIMARY (and sole canonical-head) experiment;
  `temporal_perdim`/Chebyshev is retained only as a separately named SECONDARY experiment with its own
  declared, persisted threshold grid, and equal numeric thresholds are distinct experiment identities
  (never deduplicated across metrics). Analysis executes each
  distinct current search-representation class exactly once over only its canonical rows (per-class
  retrieval passes, never a merged union — see `CONTRACTS.md`). The winner/delta baseline per
  `(backbone, sim_metric, k, metric)` is the **observed** `global_pool:{backbone}:medoid` searchable-patch
  medoid (restored by the Plan B corrective pass as an active silence-aware observed baseline — an
  observed source row's unit vector, never a synthesized flat medoid and never the lowest active catalog
  class).
- **primary score variant**: `max_per_candidate_segment` — patch-count-weighted, deduplicated, with
  collision/winner/cosine/contribution traces and explicit tie/collision ambiguity variants.
- **CTP is hard-disabled and its legacy surface is DELETED** (Plan A removed the `[archival_ctp]`
  config switch; Plan E P1-S5 deleted the retained CTP module/cache/table inventory): a default run
  performs no CTP inference, writes no CTP caches/rows, and never includes CTP in primary
  winner/delta rows.
- **evaluation lenses**: MAP, MRR, NDCG, Recall, and discrimination are evaluation lenses, not
  optimization objectives, and are never collapsed into one composite.
- **independent rulers**: artist, genre, and frozen semantic-head agreement are three independent rulers,
  each with its own suffixed finite aggregate values and evaluable-query count
  (`map_k_artist`/`mrr_artist`/`ndcg_k_artist`/`recall_k_artist`/`disc_artist`/`n_queries_artist` and the
  parallel `_genre`/`_head` suffixes). Missing/null artist/genre values and songs lacking complete frozen-head
  evidence are PER-RULER exclusions (never guessed, never substituted with `unknown`, never a run failure).
  The observed `global_pool:{backbone}:medoid` carries the same three rulers' values/counts and is never a
  class/winner candidate. The fixed per-song `song_retrieval_metrics` surface stays artist-ruler-only, with
  `disc_genre_contrib`/`disc_head_contrib` explicitly historical-empty.

## CLI phases (explicit phase boundaries)

`python run.py <command>` is EXACTLY a **twelve-command** CLI — the eight phase verbs below plus
the four maintenance commands in the next subsection. The eight explicit phase boundaries are
(see `CONTRACTS.md` for the binding responsibility table and `run.py` for the runner wiring):

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
registries, DuckDB catalog rows, frozen stream/head artifacts, and the committed observation groups
(immutable stream + aligned silence mask + commit/identity marker) that authorise the catalog and
head-analysis reads; each runs with audio/model
directories, ONNX sessions, and CUDA entirely absent, and their runner bodies import only CPU-only
modules (enforced structurally and by call-level sentinel tests in
`tests/test_phase4_dispatch_boundaries.py`).

The old pipeline names `stratify`, `segment`, `classify`, and `head` are **retired**: they are not
phases and are ordinary unknown commands — `LEGACY_PHASE_ALIASES` and the named compatibility
rejection path were REMOVED in the Plan C hard cut (P1-S7), so they exit `2` through the identical
code path as any unrecognized verb (never silently aliased, no special-case). Stratification is an
explicit catalog input/config step (selects/generates the corpus + config surface before the per-song pass),
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
  current filesystem sources and rebuilds the registry/cache rows (validating optional `corpus/` and
  `catalogs/` manifests); it never opens audio/models/ONNX/CUDA/sessions/segmentation.
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
| `heads/current/` | fixed-path CURRENT marker `<sid>.<bb>.json` per identity (head-suite analogue of `catalogs/current.json`), atomically replaced on supersession | — |
| `observation_commits/` | commit marker `<sid>.<bb>.<64-hex>.json`, written **last** | — |

- **Grammar / immutability.** The only payload grammar is `<song_id>.<backbone>.<64-hex-lowercase-sha256>.<suffix>`; bare and `.vN` names are never written or parsed (`parse_artifact_name` is the digest-only parser). Publication is staged `.tmp` write → `fsync(file)` → close → atomic rename → `fsync(dir)`; bytes at an existing digest are never replaced (content-addressed, no-replace). A registry row/status (`pending`/`ready`/`missing`/`corrupt`) reflects a validated current group; the rows/columns (`STREAM_REGISTRY_COLUMNS`/`HEAD_STREAM_REGISTRY_COLUMNS`, `STREAM_TABLE`/`HEAD_STREAM_TABLE`, `row_tuple`/`from_row`) remain as cache until Plans C/E migrate their consumers.
- **Mask semantics v1** (`audio_masks/`): pinned `essentia_rms_dbfs_v1`, `-60 dBFS`, two-frame silent-run removal, `fraction_active_ge 0.5`, two-patch hysteresis; derived via production `get_params`/`compute_log_mel`/`extract_patches` plus the sole approved frozen replay of frame-range arithmetic. Zero model/session/ONNX/CUDA for (re)derivation.
- **Heads.** `infer-heads` publishes one immutable, digest-named `.npz` + manifest per song/backbone with the complete canonical head inventory, exact committed-stream `patch_count` alignment, finite/dimension checks, and manifest provenance. `HeadStreamStore.batch_gather(song_id, backbone, source_patch_indices, *, forbid_duplicates=False) -> np.ndarray` returns validated float32 `[N, total_dim]` with columns concatenated in canonical head order (source-index gather).
- **Heads/CURRENT marker (Plan C).** `streams/heads_current.py` owns one fixed-path, per-identity
  marker at `heads/current/<sid>.<bb>.json` that selects the CURRENT complete head suite among many
  immutable on-disk generations for an identity. `HeadStreamStore.publish` publishes it (staged
  durable write → atomic replace, strict `generation` bump) for every freshly-inferred suite; it is
  never a digest name. `resolve_current_head_suite` accepts ONLY the marker-selected suite aligned
  to the CURRENT committed stream and fails closed on a missing/malformed/stale/mismatched marker or
  a marker referencing a superseded stream — selection NEVER falls back to mtime/lexical order. Head
  reindex rebuilds head registry rows ONLY from these markers and performs no inference.
- **Committed observation groups + the sole read seams.** The only usable observation is a COMPLETE
  committed observation group: the immutable stream + the aligned audio-derived silence mask + the
  commit/identity marker (`observation_commits/<sid>.<bb>.<commit>.json`, written last). Catalog
  construction, canonical head analysis, and FS-reindex readiness all REQUIRE such a group; there is
  no stream-only, mask-less, or uncommitted read path. Active consumers read through the two
  store-backed seams constructed from their `StreamStore` — `CurrentStreamResolver`/
  `make_current_stream_resolver` (`.load(song_id, backbone) -> float32[P,D] | None`) and
  `CurrentMaskResolver`/`make_current_mask_resolver` (`.load(song_id, backbone) -> uint8[P] | None`)
  — plus `StreamStore.load_committed_observation`, and NO filesystem-path, one-argument, or no-mask
  loader exists. Every seam resolves ONLY a complete committed group via the ONE shared
  `observation_group_ready`/`StreamStore.observation_group_ready` predicate (newest valid commit on
  disk: marker content digest + referenced current-format stream/mask manifests + payload
  bytes/digest/dtype/shape/finite + identity, alignment, audio-fingerprint, mask-semantics checks). A
  registry `ready` row is cache metadata only and never authorizes a group by itself. Missing /
  corrupt / wrong-length / wrong-digest / uncommitted masks fail closed and are never interpreted as
  no silence.
- **Reindex.** `streams/reindex.py` exposes `reconcile_current_manifests(root, con)` and the public `reindex(root, con)` maintenance wrapper. They walk only current-format digest manifests/commit markers (plus optional `corpus/`/`catalogs/` manifests) and rebuild the retained registry cache rows from the filesystem after a DB deletion. FS-reindex readiness is defined IDENTICALLY to the rest of the system: `_rebuild_stream_registry` rebuilds a stream-registry row ONLY from a complete committed observation group that satisfies the shared `observation_group_ready` predicate (via `load_committed_observation`); incomplete / mismatched / stream-only artifacts are reported refused, and a ready row is never rebuilt from a stream-only artifact. They validate refs/digests/shape/dtype/finite/alignment/commit-readiness/catalog WAL state, refuse corrupt/incomplete/mismatched/WAL-bearing state, and never open audio/models/ONNX/CUDA, parse old names, or rerun segmentation. Head-suite registry rows are rebuilt ONLY from the `heads/current/` CURRENT markers via `resolve_current_head_suite` (marker-selected complete suites aligned to the current committed stream; see the Heads/CURRENT marker bullet above). Reindex is exposed as the `streams.reindex` module API (`reconcile_current_manifests`/`reindex`).
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
  `(backbone, sim_metric, k, metric)` is the observed `global_pool:{backbone}:medoid` medoid baseline row
  (when a finite one shares that exact scope); the medoid is never itself a winner candidate. The winner
  is the highest finite segmented catalog class with `strategy_key` tie-break; `delta = winner - baseline`
  is finite. A cell without a finite medoid baseline row emits no delta row. Aliases are sorted and never
  duplicate score rows.
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
> seven-section catalog contract. The current 11-table schema is listed in the "Required generated
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
- `analyze_incomplete_diagnostics` — versioned non-metric diagnostics for non-comparable
  representations (`db/incomplete_diagnostics.write_incomplete_analyze_diagnostic`, written only
  after the mandatory observed baseline succeeds; no PK/UNIQUE, app-scoped replacement by
  `(run_id, strategy_key, sim_metric, k)`).

  > **Note — the segmentation catalog is NOT a DuckDB table here.** The five *compact*
  > catalog tables (`catalog_metadata` / `seg_config` / `catalog_song` / `seg_meta` /
  > `run_provenance`) live inside published FILESYSTEM snapshot files
  > (`catalogs/<catalog-id>/catalog.duckdb` + `catalog.manifest.json`, selected by
  > `catalogs/current.json`), not in `research.duckdb`. The old `research.duckdb`
  > `seg_config`/`seg_meta`/`seg_membership` tables were removed (corrective pass P1-S12).
  > `stream_registry` / `head_stream_registry` / `run_provenance` + `catalog_metadata` here are
  > rebuildable registries/provenance only.

**[Archival] — legacy-compatibility rows inside an active table: no longer applies.**

- `analyze_metrics` rows with `run_id='legacy'` no longer exist: the analyze hard cut REMOVED the
  pre-cut backup-first migration (old rows copied as `run_id='legacy'`), the `'legacy'` default, and
  the run-exclusion predicate. `analyze_metrics` now has ONE current run-scoped schema with a
  required non-null `run_id` (no default, no legacy partition). A stale pre-cut table that still
  lacks `run_id`, carries any `run_id='legacy'` row, or exposes a non-None `run_id` column
  default (a HEAD-era pre-cut shape carrying `DEFAULT 'legacy'` with no rows to trip the
  row-presence check) is refused by `db/_schema.py`'s `StaleSchemaError` guard and reset via
  `python run.py reset --scope analysis` — never read or relabeled into current lineage. Every
  `analyze_metrics` row is a live run-scoped row under a real caller-supplied run id.

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
`db/flat.write_analyze_metrics`;
`db/incomplete_diagnostics.py` (`write_incomplete_analyze_diagnostic` /
`read_incomplete_analyze_diagnostics`); report readers (`report/_*.py`, DB scalars + manifests only).

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


## Apparatus-v1.0 remaining corrective pass

> **Landed/current-state note (2026-09, Plans A→B→C-Phases-1-2).** The dependency chain below is no
> longer merely "remaining": execution-reporting Plans A (observation-corpus-metrics) and B
> (atomic-lifecycle-diagnostics) are LANDED (QA-passed), and Plan C Phases 1–2 — complete corpus
> deltas + the deterministic fixture/adversarial gate battery — are LANDED in the working tree.
> Only Plan C P3-S2 (commit) and P3-S3 (QA-PushManager Gate-1 publication) remain pending. The
> older execution/reporting Plans E/F/G prose elsewhere is SUPERSEDED/HISTORICAL for execution by this
> broader chain — do not read E/F/G-era "complete equality / hash-only delta / subset" claims as
> current contract. Current delta semantics: only genuinely equal COMPLETE persisted corpus
> identity/evidence (13-field surface) yields a delta; any differing/one-sided field yields an
> explicit incomplete diagnostic with a field-level reason (see the Plan C landed addendum in
> `CONTRACTS.md`).

The pushed candidate `cc3a17155f30e35674f85086c3aa09d60d2d147c` was the input state for the dependency-ordered corrective chain below. The older pending execution/reporting Plans E/F/G are superseded for execution by this broader chain and must not be run independently:

```text
A observation binding, corpus semantics, rulers, and metric identity
  -> B atomic analyze lifecycle and durable incomplete diagnostics
    -> C complete corpus deltas, deterministic verification, and QA-PushManager Gate 1 publication
```

This pass preserves the filesystem-first immutable observation architecture, compact catalog, CPU-only derived phases, source-index medoids, bounded exact scoring, v2-only analyze scope, mandatory observed global-medoid baseline, evaluation-corpus identity, semantic/disposable identity separation, seven-section report, and research-only scope. It does not run a real corpus/model/audio/ONNX sweep and does not add
compatibility readers, fallback paths, dual writes, CTP, ANN, production changes, or frontend
changes. See the appended apparatus-v1.0 section of `CONTRACTS.md` and the task plans A/B/C (and
their landed addenda) for binding details; Plans E/F/G are historical for execution.
