# Embedding Research — Geometry Contracts

> **Current geometry era (migration complete):** The threshold-independent per-song Gram geometry
> DD and Plans A–U supersede the earlier runtime contract. The hard-cut deletion completed and the
> historical sections of this file were removed; what remains describes only the current
> geometry-era reality. Nothing here is permission for compatibility APIs, alternate readers,
> dual writes, or retired runtime vocabulary.

## Migration status (complete)

The hard cut is complete. Plan K restored a compilable/importable research
runtime and migrated every active runtime caller, test, fixture, report, maintenance, schema,
dynamic-dispatch, and serialized-phase surface to the geometry contracts below. Plan L deleted the
remaining retired ownership and stale schema surfaces. Plans M, N, O, P, Q, R, S, T, and U
completed exact identity persistence, seven-section reporting, seven-phase dispatch, stale-evidence
refusal, geometry-preserving maintenance, deletion proof, synthetic R1–R13 behavior, R1–R14
validation, and final acceptance. Every phase required compileall, clean import smoke, and focused
synthetic tests. No compatibility runtime or dual reader/writer remains.

## Corpus-level geometry contract

The corpus seam is owned by `common/geometry_analysis.py` and is consumed by `run.py`, head
analysis, persistence, report retrieval, and synthetic fixtures:

```text
GeometrySongRequest(song_id, backbone, geometry_identity, observation_evidence,
                    artist, genre, head_label, synthetic_only)
GeometryCorpusRequest(items, threshold_request, experiment, evaluation_id,
                      scoring_semantics_version, run_id, execution_id,
                      numerical_profile_digest, synthetic_only)
FrozenGeometryEvaluation(evaluation_id, query_vectors, query_weights,
                         eligible_song_ids, observation_evidence_digest, comparable)
GeometrySongAnalysis(request, thresholds, roster, scores)
build_geometry_corpus_request(con, *, stream_store, profile, threshold_request,
                              experiment, evaluation_id, run_id, execution_id,
                              scoring_semantics_version, song_ids=None,
                              backbones=None, synthetic_only=True) -> GeometryCorpusRequest
write_geometries_for_current_songs(con, *, stream_store, profile, run_id, lock,
                                   song_ids=None, backbones=None) -> tuple[GeometryRecord, ...]
analyze_geometry_corpus(request, *, con, stream_store, profile,
                        scoring=score_bounded_exact) -> GeometryCorpusAnalysis
score_unique_geometry_representations(roster, evaluation, scoring) -> GeometryScoreBundle
write_geometry_corpus_analysis(con, *, run_id, result) -> None
read_geometry_corpus_analysis(con, *, run_id, identity) -> GeometryCorpusAnalysis
```

The scheduler orders `(song_id, backbone)` deterministically; loads/verifies exactly one committed
observation and one exact-key `GeometryRecord` per item; calls `analyze_all_thresholds` once;
derives every structural and search projection before any scorer; and revalidates the complete
binding at start and end. It refuses missing, stale, mixed, corrupt, nonfinite, or mask-less
evidence.

`FrozenSearchRepresentation` and `GeometryRepresentationRoster` are transient CPU-memory values.
They preserve every structural threshold member while collapsing only equal ordered scoring inputs
within one experiment/evidence domain. Primary `temporal_global`/unit-space L2 and explicit
secondary `temporal_perdim`/Chebyshev never collapse, even at equal numeric thresholds. Frozen
source rows are gathered once per unique representation; the observed whole-song source medoid is
a separate baseline representation, never a winner candidate, and no synthetic/coordinate-wise
medoid is allowed.

The bounded scorer is invoked only for unique representations and emits counters for geometry
loads, all-threshold batches, source gathers, scorer calls, and
`segmentation_from_scorer_count == 0`. Metrics retain independent artist, genre, and frozen
semantic-head rulers; missing labels exclude only that ruler. Publication preflights all
geometry/observation/threshold/structural/search/evaluation/scoring/execution identities and
finite values, then writes aggregate/per-song/ruler/baseline/provenance rows atomically through
the existing invocation-obligation and terminal-completion lifecycle. Derived phases are CPU-only
and synthetic fixtures are the only execution evidence; no real corpus, production integration,
audio/model/ONNX/CUDA, optimizer, ANN, or durable threshold-result table is in scope.

The corpus-owner functions listed above were the minimal addition required because the earlier
DTO-only seam was incomplete; they now own the corpus seam and every caller that depended on the
deleted ownership consumes them. No derived runner function remains a refusal placeholder. Mixed
tests were rewritten to geometry identities, and the final handoff records the deleted surface
list, the rewritten mixed tests, and a zero-active-caller scan. The seven runtime phases are
exactly `ingest`, `embed`, `infer-heads`, `geometry`, `analyze`, `head-analysis`, and `report`;
the retired verbs are ordinary unknown commands. No compatibility path, dual runtime/schema,
filesystem-derived Gram, real corpus, optimizer, CTP, spectral baseline, or ANN is permitted.

## Scope and invariants

Only `scripts/embedding_research`, its tests/docs, and formal planning artifacts are in scope. No
production or frontend changes. A′ persists each geometry's canonical Gram matrix as a DuckDB
`BLOB` in `song_patch_geometry`, alongside its scalar identity/metadata columns. Parquet/tar/Zarr
payloads, ANN v1, optimizer prerequisites, DuckDB 2.x migration, and deferred production quantized
streams are excluded.

Current invariants: a single finite threshold-application contract `direct_distance` with
`configured == effective` exactly — its executed distance metric is never stored but derived from
the configured geometry mode (`l2` for `temporal_global`, `chebyshev`
for `temporal_perdim`); commit-bound observation evidence whose structural ranges yield the exact
searchable membership reconstructed on read (never a per-patch table, never an inclusive range),
with absorbed outliers represented exactly and segment medoids stored as observed source patch
indices; per-geometry identity preimages that bind each leaf to its song id and fold the frozen
stream plus committed-mask digests, mask/scoring semantics and versions, ordered medoid source
indices and normalized weights, and the full canonical structural rows — structural-only changes
alter song/exact identity but never split a search representation when the actual ordered scoring
inputs stay equal; class-1 `act[1]` canonical head pooling over the shared geometry boundary;
strategy-key identity decoded from `geometry:{backbone}:{score_variant}:v{version}:{keyset}`;
analysis that schedules every distinct current search representation exactly once as its own
leave-one-out pass over only that representation's canonical rows (per-representation retrieval
passes, never a merged union); and the observed whole-song source medoid RESTORED as an ACTIVE
baseline against which the report computes per-`(backbone, sim_metric, k, metric)` winner/delta
rows.

Still held regardless of surface: no synthetic/coordinate `median`, no `agg_method=medoid`, no
`disc_album`, no non-finite output, and no cross-backbone corpus mixing — the observed medoid
baseline is an observed source row's unit vector (source index plus centrality only), never a
synthetic/coordinate-wise vector. The active discrimination vocabulary is the three independent
ruler metrics `disc_artist`/`disc_genre`/`disc_head`, each computed on its own ruler-labeled
population.

## Threshold and configuration contracts (current)

There is exactly ONE threshold contract: a single finite threshold-*application* semantics
`direct_distance` applied directly to the boundary, with `configured == effective` exactly. The
executed boundary distance is a *derived* quantity, not a stored configuration axis: the primary
Gram engine compares rows by unit-vector L2 and derives all 171 primary thresholds from one decoded
Gram, while the Chebyshev secondary path is an explicit, separately-named experiment
(`temporal_perdim`, per-dimension Chebyshev over canonical coordinates). The advertised metric
always equals the executed metric; there is no `bin_mode`-selected metric dispatch. Scaled
(`std_scaled`), calibration/p50, weighted-reduction, and per-threshold cache/table vocabulary were
removed and are historical only. The pure API home is `helpers/thresholds.py`, free of
DuckDB/IO/audio deps:

```python
@dataclass(frozen=True)
class ThresholdResolution:
    configured: float      # finite
    effective: float       # finite; == configured exactly
    semantics: str         # == "direct_distance" (threshold application; the only semantics)
    encoder_version: str   # SHA-256 of helpers/thresholds.py bytes (whole-module)

resolve_threshold(configured: object) -> ThresholdResolution   # single arg only
canonical_float(value: object) -> str      # finite; -0.0 -> "0.0"; rejects NaN/Inf
canonical_config_hash(*, backbone, bin_mode, threshold, outlier_window,
                      strategy_version, encoder_version) -> str
config_encoder_version() -> str            # lazy whole-module SHA-256, metadata-refreshed
```

`resolve_threshold` accepts only a finite numeric `configured` and always returns the
`direct_distance` application semantics; it has no `semantics` or `calibration_record` parameter.
The threshold-config rows carry the threshold-application label in their stored
`threshold_semantics` column (always `direct_distance`) and NO stored distance-metric column — the
executed metric is a property of the geometry engine, not a configurable axis — and no
`calibration_record`/`config_membership` columns. The resolved threshold is one scalar with
`configured == effective` and application semantics `direct_distance` in every retained mode. The
primary Gram engine uses unit-vector L2 over the 171-grid; the Chebyshev secondary is a distinct,
explicitly-named experiment (`temporal_perdim`) and never a `bin_mode`-selected variant of the
primary path.

The strict configuration loader lives in `helpers/toml.py`:
`load_research_config(path: Path | None = None) -> CurrentResearchConfig` accepts ONLY the
executable current `[pipeline]` (EffNet default backbone; explicit MusicNN opt-in) and
`[analysis]` settings and raises distinct named errors (`ResearchConfigMissingError`,
`ResearchConfigSyntaxError`, `ResearchConfigParserUnavailableError`,
`ResearchConfigValidationError`) for a missing/unparsable/invalid file — never warn-and-return
`{}`.

## StreamStore contracts

```python
StreamStore.lookup(song_id: str, backbone: str) -> StreamRecord
StreamStore.batch_gather(song_id: str, backbone: str, source_patch_indices: Sequence[int]) -> np.ndarray  # float32[N,D]
StreamStore.register(...) -> StreamRecord
StreamStore.reconcile(...) -> ReconcileReport
```

`StreamRecord` fields: `song_id`, `backbone`, opaque root-relative `artifact_ref`, `patch_count`,
`dim`, `dtype`, `format_version`, `fingerprint_sha256`, `preprocess_fn`, `preprocess_version`,
`backbone_model_hash`, `audio_params`, `embed_semantics_version`, `provenance_source`,
`provenance_assumption`, `status`, `run_id`, `created_at`, `updated_at`. Only `ready` records whose
SHA-256, shape, dtype, finite values, and `allow_pickle=False` load validate may be gathered.
Paths are never IDs or SQL keys.

Publication is staged `.tmp` write, file `fsync`, close, atomic rename, directory `fsync`,
transactional `pending` registration, then reconcile to exactly `ready`, `missing`, or `corrupt`.
Current filesystem manifests and observation commits are authoritative; registry rows are
rebuildable index/cache metadata. Supersession is handled by immutable content addressing, and
downstream registry consumers read through the registry row/status contract. Immutable current
bytes are never replaced at an existing digest.

### Committed observation groups — the only usable observation (current)

A **committed observation group** is the immutable publication unit a derived consumer may read:
the immutable embedding **stream**, the **aligned audio-derived silence mask**, and the
**commit/identity marker** (`observation_commits/<song_id>.<backbone>.<commit_sha256>.json`,
written last). A complete, valid group is REQUIRED for geometry construction, for canonical head
analysis, and for FS-reindex readiness. There is no stream-only, mask-less, uncommitted, or
old-format read path, and no compatibility reader or dual write.

Readiness is ONE shared filesystem-authoritative predicate used by the current-stream resolver,
the current-mask resolver, the geometry producer preflight, and reindex:
`observation_group_ready(store, song_id, backbone, *, stream_record=None)` (module-level,
re-exported from `streams/`) delegates to `StreamStore.observation_group_ready`, which selects the
NEWEST valid committed group by verifying — on disk — the marker content digest, the referenced
current-format stream and mask manifests, both payload bytes/size/SHA-256/dtype/shape/finite
values, stream-mask identity, patch-count equality, alignment token, audio fingerprint, and mask
semantics. A registry row claiming `ready` is cache metadata ONLY and never authorizes a group by
itself.

The two SOLE read seams are store-backed and expose no filesystem-path API:
`StreamStore.load_committed_observation(song_id, backbone) -> CommittedObservation` materializes
the validated immutable identity plus both payload arrays (stream `float32[P,D]`, aligned mask
`uint8[P]`; `1` = searchable) and raises the typed `StreamValidationError` ('group refused') for
absent/corrupt/wrong-length/wrong-digest/uncommitted/mismatched groups; `CurrentStreamResolver`
(`make_current_stream_resolver`) and `CurrentMaskResolver` (`make_current_mask_resolver`) each
resolve ONLY a complete committed group. Geometry and head consumers construct these resolvers
from their `StreamStore`; no ad-hoc, literal-`None`, or one-argument mask loader exists.

Fail-closed semantics: missing, corrupt, wrong-length, wrong-digest, uncommitted, or mismatched
masks are typed refusals (geometry: per-input `MaskRefusalError`; head: per-song skip/error reason;
reindex: refused issue). Absence is NEVER interpreted as no silence — a group without a valid
aligned mask is refused, never silently rebuilt or pooled all-searchable.

### Head stream contracts (current)

`HeadStreamStore.batch_gather(song_id, backbone, source_patch_indices, *,
forbid_duplicates=False) -> np.ndarray` returns validated float32 `[N, total_dim]` rows with
columns concatenated in canonical head order and source-index semantics. `infer-heads` publishes
complete, finite `[T,C]` streams whose `T` matches the backbone patch count; missing or mismatched
heads are rejected. The canonical CPU head runner is
`common.head_analysis.run_shared_geometry_head_analysis`, which pools classifier head outputs over
the shared geometry boundary, keeps pooled values transient, and writes only non-blocking
coverage/skip provenance into `head_phase_provenance`.

## Geometry persistence and analysis (current)

`db/geometry.py` owns the geometry record and its exact-key persistence:

- `song_patch_geometry` stores one exact-key complete geometry per `(song_id, backbone)`:
  `geometry_id`, the observation commit digest, `geometry_semantics_version`,
  `numerical_profile_digest`, the complete observation-evidence tuple, the Gram blob, and the
  matrix.
- `write_geometry(observation, profile, run_id, *, lock=None)` computes and publishes one
  exact-key complete geometry transactionally. Geometry persistence never acquires a second lock
  or performs an implicit recovery/reset; callers that mutate the primary DB pass the existing run
  lock explicitly.
- `read_geometry(exact_identity, con)` and `read_geometry_matrix(exact_identity, con)` read and
  validate exactly one complete row by its full identity.
- `verify_geometry_binding(record, current_observation, profile)` compares the complete persisted
  observation-evidence tuple without rebinding or repair.
- `write_geometries_for_current_songs(...)` loads and mask/resource-checks every item before the
  first write, publishes each row through `write_geometry`, then re-reads and verifies it through
  `verify_geometry_binding`.
- `load_geometry_observation(store, song_id, backbone)` loads the sole complete committed
  observation through the `StreamStore` seam. A missing mask, provenance value, or payload digest
  is an integrity refusal; it is never filled from a default or interpreted as an all-searchable
  observation.

`common/geometry_analysis.py` owns the corpus request and analysis described above; its
`score_unique_geometry_representations` scores each frozen representation exactly once through the
bounded CPU scorer boundary and keeps the separately identified observed baseline out of the
winner `scores`. `write_geometry_corpus_analysis` preflights every identity and finite value,
persists the mandatory observed baseline before any other aggregate evidence, revalidates every
geometry binding before commit, and terminalizes the invocation only after complete publication;
any refusal rolls back every output. `read_geometry_corpus_analysis` reads exactly one complete
scope and has no latest/current resolution path.

## DuckDB logical schema

New/maintained active tables use scalar columns and intentionally have no new `PRIMARY KEY`/`UNIQUE`
constraints. Application checks and duplicate tests enforce identities.

- `song_patch_geometry` — one exact-key complete geometry per `(song_id, backbone)` (see above).
- `geometry_analysis_records` — run-scoped aggregate/per-song/ruler/baseline geometry analysis
  records with the complete identity axes.
- `geometry_head_evidence` — geometry-bound head analysis evidence.
- `stream_registry` and `head_stream_registry` — immutable sidecar registries; identity
  `(song_id, backbone)`.
- `songs` — corpus rows (PK `song_id`).
- `analyze_metrics` — one current run-scoped schema: `run_id TEXT NOT NULL` with no default, no PK.
- `song_retrieval_metrics` — per-song aggregate lenses (PK `strategy_key,sim_metric,k,song_id`).
- `head_phase_provenance` — canonical 18-column head sink, no PK.
- `phase_timings` — elapsed wall-clock per phase (PK `run_ts,phase`); the active efficiency source.
- `run_provenance` — per-phase run rows, including retention state.
- `corpus_state` — singleton post-run corpus state; zero/one application check.
- `analyze_incomplete_diagnostics` — versioned non-metric diagnostics for non-comparable
  representations, no PK/UNIQUE; app-scoped replacement by `(run_id, strategy_key, sim_metric, k)`.

No vector BLOBs, `view_manifest`, or artifact-classification table is introduced. `analyze_metrics`
is run-scoped: `run_id` is a required non-null `TEXT` column with no default. All readers and
writes are run-scoped under a caller-supplied current run id. A stale pre-cut table (missing
`run_id` or exposing an unexpected `run_id` column default) is refused with `StaleSchemaError` and
explicitly reset via `python run.py reset --scope analysis`; no executable writer or reader
reinterprets a stale row as current lineage.

## Report contract (schema v2 — seven sections, active geometry only)

The `report` phase is the executable entry point. It renders exactly seven sections in this order:
`summary`, `corpus`, `analysis`, `winners`, `head-analysis`, `provenance`, `efficiency`.

- `summary` — active geometry-result status per backbone (winner / delta / factor summary, or an
  explicit empty-active-results message).
- `corpus` — active songs / corpus health.
- `analysis` — ONLY `analyze_metrics` rows with `strategy_type == 'geometry'`: run id / sim_metric
  / k / metric / value plus geometry strategy identity, score variant, scoring-semantics version,
  evidence-content-hash provenance, canonical geometry id, and sorted membership ids.
- `winners` — deterministic winner / delta / factor tables per backbone. The baseline per
  `(backbone, sim_metric, k, metric)` is the observed whole-song source medoid baseline row (when
  a finite one shares that exact scope); the medoid is never itself a winner candidate. The winner
  is the highest finite matched geometry class with `strategy_key` tie-break, and
  `delta = winner − baseline`. A cell without a finite medoid baseline row emits no delta row.
- `head-analysis` — canonical `head_phase_provenance` per supported backbone with finite / status
  / coverage and provenance.
- `provenance` — active `run_provenance`, command lines, hashes, warnings, reuse/refusal
  decisions, and limitations.
- `efficiency` — retained `phase_timings`.

Emitted keys are active-only; no emitted section/table ID, title, key, warning, or value uses
retired vocabulary or a retired phase name. Completed-scope selection is PER `run_id` (a grouped
per-run predicate over append-only provenance). A single failed analyze row vetoes the ENTIRE run,
so a contradictory run is never auto-selected and is refused through an explicit `report_run_id`
(fail closed). A clean completed run stays deterministically selectable and the report data remains
run-scoped (never blends runs).

## Verification

Required tests cover the direct threshold contract, exact membership/medoids, one-pass loads,
identity hashes, bounded oracle equivalence, lifecycle/fault/corruption, negative boundaries, root
relocation/export-import, stale refusal, scale/memory, run-scoped migration/resets/schema, zero-row
unused surfaces, fixture/report validation, full research pytest, compileall, ruff format/check,
and an explicit diff audit excluding `nomarr/` and `frontend/`.
