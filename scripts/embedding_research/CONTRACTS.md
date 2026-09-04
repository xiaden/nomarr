# Embedding Research — Frozen Stream and Catalog Contracts

> Binding research API/schema reference for the frozen observation-stream refactor. This file supersedes the stale 18-table/copied-vector contract. Legacy APIs remain only when explicitly marked archival compatibility.

## Scope and invariants

Only `scripts/embedding_research`, its tests/docs, and formal planning artifacts are in scope. No production or frontend changes. A′ uses immutable float32 NumPy `.npy`/`.npz` sidecars plus DuckDB scalar metadata/catalog. Parquet, DuckDB BLOB/tar/Zarr payloads, ANN v1, optimizer prerequisites, DuckDB 2.x migration, and deferred production quantized streams are excluded.

Existing invariants remain: `act[1]` is class 1; stratification uses `np.minimum((h_scores * 10).astype(np.int32), 9)`; PTC uses running spherical centroid, strict `>`, `OUTLIER_WINDOW=3`, and direct L2/per-dimension distance modes; absorbed outliers are represented exactly; medoids are observed source rows with smallest-index ties; global identity is `global_pool:{backbone}:medoid`; no `agg_method=medoid`, synthetic median, `disc_album`, non-finite output, or cross-backbone corpus mixing.

## Threshold contracts

`ThresholdResolution(configured, effective, semantics, calibration_record)` is immutable and finite.

```python
resolve_threshold(
    configured: float,
    *,
    semantics: Literal["direct_l2", "std_scaled"] = "direct_l2",
    calibration_record: Mapping[str, object] | None = None,
) -> ThresholdResolution
```

`direct_l2` is the default and guarantees `effective == configured`. `std_scaled` is explicit legacy-fidelity compatibility only; it records the calibration basis and effective threshold. Every catalog config stores both values, semantics, calibration record, outlier window, strategy version, and canonical config hash. Canonical numeric encoding is deterministic. The config default is EffNet, explicit PTC temporal configurations, observed medoid, cosine, optimizer disabled, and CTP disabled.

## StreamStore contracts

```python
StreamStore.lookup(song_id: str, backbone: str) -> StreamRecord
StreamStore.batch_gather(song_id: str, backbone: str, source_patch_indices: Sequence[int]) -> np.ndarray  # float32[N,D]
StreamStore.register(...) -> StreamRecord
StreamStore.reconcile(...) -> ReconcileReport
```

`StreamRecord` fields: `song_id`, `backbone`, opaque root-relative `artifact_ref`, `patch_count`, `dim`, `dtype`, `format_version`, `fingerprint_sha256`, `preprocess_fn`, `preprocess_version`, `backbone_model_hash`, `audio_params`, `embed_semantics_version`, `provenance_source`, `provenance_assumption`, `status`, `run_id`, `created_at`, `updated_at`. Only `ready` records whose SHA-256, shape, dtype, finite values, and `allow_pickle=False` load validate may be gathered. Paths are never IDs or SQL keys.

Publication is staged `.tmp` write, file `fsync`, close, atomic rename, directory `fsync`, transactional `pending` registration, then reconcile to exactly `ready`, `missing`, or `corrupt`. Legacy pre-registry artifacts are explicitly `provenance_source="legacy"` with assumptions/caveats or re-embedded; they are never silently provenance-complete. Immutable bytes may be superseded while logical `(song_id, backbone)` is replaceable.

`HeadStreamRecord` and the analogous head store contain song/backbone, opaque artifact ref, patch count, canonical head IDs and dimensions, model-suite/preprocess provenance, alignment and format versions, fingerprint, status, and run. `infer-heads` publishes complete, finite `[T,C]` streams whose `T` matches the backbone patch count; missing or mismatched heads are rejected.

## DuckDB logical schema

New/maintained active tables use scalar columns and intentionally have no new `PRIMARY KEY`/`UNIQUE` constraints. Application checks and duplicate tests enforce identities.

- `stream_registry(song_id, backbone, artifact_ref, patch_count, dim, dtype, format_version, fingerprint_sha256, preprocess_fn, preprocess_version, backbone_model_hash, audio_params, embed_semantics_version, provenance_source, provenance_assumption, status, run_id, created_at, updated_at)`; identity `(song_id, backbone)`.
- `head_stream_registry(song_id, backbone, artifact_ref, patch_count, head_ids, dim_by_head, format_version, fingerprint_sha256, preprocess_fn, preprocess_version, backbone_model_hash, alignment_version, status, run_id, created_at, updated_at)`; identity `(song_id, backbone)`.
- `seg_config(config_id INTEGER, backbone, bin_mode, threshold_configured, threshold_effective, semantics, calibration_record, outlier_window, strategy_version, alias_of_config_id, canonical_config_hash, created_at, run_id)`.
- `seg_meta(config_id, song_id, seg_id, start_idx, end_idx, member_count, absorbed_outlier_count, weight, medoid_source_patch_idx, segment_signature, created_at)`.
- `seg_membership(config_id, song_id, seg_id, member_patch_idx, is_absorbed_outlier, membership_version)`; authoritative exact membership including absorbed outliers.
- `run_provenance(run_id, phase, status, started_at, finished_at, input_artifact_hashes, output_artifact_hashes, config_hash, song_count, warning_count, software_versions, command_line, structural_change_summary, retained, view_refs)`.
- singleton `corpus_state(state_version, registered_song_count, eligible_song_count, complete_flag, latest_catalog_run_id, latest_search_view_hash, reconciled_at, reconciliation_status)`; zero/one application check.
- `catalog_metadata(catalog_semantics_version, serialization_version, manifest_version, backbone_set, latest_run/config identifiers)`; metadata only.

No vector BLOBs, `view_manifest`, or artifact-classification table is introduced. Legacy tables are retained only when an explicit archival/golden obligation exists. `analyze_metrics` is migrated backup-first to include `run_id`, with legacy rows copied as `run_id='legacy'`; readers and writes are run-scoped.

## Catalog and identity APIs

```python
build_segmentation_catalog(con, stream_store, configs, song_ids, run_id, *, verify=False) -> CatalogBuildReport
configs_by_backbone(con, backbone) -> Sequence[SegConfigRecord]
segments_by_config_song(con, config_id, song_id) -> Sequence[SegMetaRecord]
membership_by_config_song_seg(con, config_id, song_id, seg_id) -> Sequence[SegMembershipRecord]
stream_by_song_backbone(con, song_id, backbone) -> StreamRecord
```

`config_id` is an integer application identity. A catalog pass loads one verified stream per song/backbone and evaluates every threshold/config in one pass. `seg_membership` stores each source patch index once, including `is_absorbed_outlier`; `seg_meta.start_idx/end_idx` are structural report ranges only. Segment medoids and global medoids store observed source indices, never copied vectors. Single-config rebuild deletes only that config; full rebuild is explicit. Application checks reject duplicate config/membership/segment/singleton identities without database constraints.

Canonical serialization sorts rows, fixes column/type/NULL/numeric encodings, and includes semantic/software versions. Per-song signatures include stream fingerprint and canonical config/membership/meta rows. Strict `search_view_hash` includes sorted song signatures, configs, stream fingerprints, catalog/manifest/software versions. Manifest-only `catalog_fingerprint` hashes complete logical state but excludes its own value. Aliases map to canonical configs; reports expose configured/effective values, aliases, failed/empty songs, outliers, medoid changes, and structural changes. Planning scale arithmetic is approximately `10,000 × 100 × 10 ≈ 10M` catalog rows and is not an empirical claim.

## Disposable views and bounded scoring

```python
materialize_search_view(...) -> SearchViewRecord
score_bounded_exact(
    query_vectors, query_weights, candidate_view, *,
    query_chunk_size, candidate_chunk_size, working_memory,
    tie_policy="first_index",
    collision_policy="retain_all_candidate_segments",
    expensive_trace=False,
) -> BoundedScoreResult
```

Views gather observed medoids through `batch_gather`, are keyset-addressed and regenerated per run, and record keyset/content hashes in `run_provenance.view_refs`. Keysets include corpus hash, run/config/song/query keys, `(application_version, numpy_version, sklearn_version_or_null)`, shape/dtype, and scoring semantics. v1 exact CPU is the future ANN seam; no ANN index is created.

The primary score is `max_per_candidate_segment` with `first_index + retain_all_candidate_segments`; the explicit alternative is `equal_tie_split + unique_source_max`. Temporary query/candidate matmul chunks are released after streamed reductions. Normal analysis retains no N×N trace; full traces are explicitly expensive/debug. `scoring_harness.py` remains the small full-matrix oracle. MAP, MRR, NDCG, Recall, and discrimination are separate evaluation lenses.

### Phase 1 (Plan D) implemented surface — `search_views.py`

Implements the ledger `SearchViewRecord` (Plan A P2-S4; Plan D). Public API: `SearchViewKey`, `SearchViewRecord`, `AnalysisCorpus(backbone, song_ids, config_ids=())`, `QueryKeyset(query_song_ids=(), query_segments=())`, `materialize_search_view(stream_store, catalog, corpus, run_id, *, query_keyset=None, working_memory, record_provenance=True, software_versions=None) -> SearchViewRecord`, `record_search_view(catalog, record, *, run_id=None)`, and `validate_search_view_keyset(catalog, record)` (raises `StaleSearchViewError`). Keyset hash inputs are exactly the corpus `search_view_hash`, run id, sorted config ids, sorted song ids, query keys, `(application_version, numpy_version, sklearn_version_or_null)`, matrix shape/dtype, and `scoring_semantics_version`. Backbone is an ADDITIONAL hashed key dimension beyond that DD minimal list (the documented, QA-conformed P1-S1 extension): it is an explicit member of the canonical payload that is hashed, so a reader reconstructing the keyset must include it. Views are single-backbone; config ids default to every canonical (non-aliased) `seg_config` of the backbone.

**On-disk payload (disposable views).** Each view is written under the stream store's output root at `views/<keyset_hash>/` (`view_ref` is the root-relative `views/<keyset_hash>`), physically `vectors.npy` (float32 `[N, D]`, `allow_pickle=False`; row `i` = `row_addresses[i]`) plus `keys.json` (canonical keyset + ordered `rows` `[config_id, song_id, seg_id, medoid_source_patch_idx]`). Medoids are gathered ONLY by catalog `seg_meta.medoid_source_patch_idx` via `batch_gather`, never from ranges/copies/paths. `content_hash` = sha256 over the canonical payload (keyset bytes + row lines + little-endian float32 `tobytes()`), recomputable independently of the file bytes.

**Provenance.** `record_search_view` writes a canonical `keyset_hash|content_hash|view_ref` line into the existing `run_provenance.view_refs` (phase `analyze`, `retained=False`), deduped by keyset hash and preserving other runs incl. `retained` rows; no new table. Materialization ALWAYS regenerates (gathers + rewrites) — a view file's existence never authorizes reuse; `validate_search_view_keyset` is the logical-identity gate. No `view_manifest`/second registry, no indexes, no PK/UNIQUE, no ANN/VSS (exact CPU v1).

## Shared heads, CTP, cleanup, and CLI

Head analysis uses frozen aligned head streams and exact catalog membership (including absorbed outliers), `boundary_source="effnet_ptc"`, `head_pool_variant="shared_effnet_ptc_boundary"`, class-1 `act[1]`, finite outputs, and non-blocking provenance. Inclusive ranges cannot define head membership. CTP is phase-gated: with `[archival_ctp] enabled=false`, no CTP work/config/vector/row occurs; explicitly enabled CTP is archival only.

Active artifacts are streams/head streams/registries/catalog/manifest/provenance/current analysis/docs. Archival artifacts are legacy flat/PTC/head/CTP caches/readers and compatibility tables. Dead copied medoid vectors, obsolete tables/writers, and zero-caller APIs are removed only after caller audit. Cleanup scopes are `staging`, `views`, `dead`, `archival`, and `analysis-run RUN_ID`; normal analysis never globally deletes Tier 1/2 results.

CLI boundaries are exactly `ingest`, `embed`, `infer-heads`, `catalog`, `catalog-report`, `analyze`, `head-analysis`, and `report`. Only the first three may discover audio/load models/create sessions/run ONNX. Derived phases work without audio/models/ONNX/CUDA and support `--verify`; a rollback-only canary over every surviving legacy PK/UNIQUE table runs when `--verify` is set or when a post-crash signature is detected (a surviving `<db>.wal` or any non-`completed` `run_provenance` row) before derived-phase reads, blocks on failure, and instructs EXPORT/IMPORT repair. SIGKILL is bookkeeping/order evidence, not power-loss durability proof.

### Canonical CPU shared-head analysis (Plan E Phase 1)

The active derived head-analysis module is `common/head_analysis.py`; `classify.py`'s live-ONNX `run_shared_ptc_head_pooling` remains `LEGACY interim` until the Plan E CLI rewrite. The exact pure helper contract is:

```python
pool_head_outputs_over_ptc_boundaries(
    acts: np.ndarray,
    member_patch_indices: Sequence[int],
    *,
    segment_id: int,
    weight: int,
    is_absorbed_outlier: Sequence[bool],
) -> HeadBoundaryPoolResult
```

`acts` is already gathered in the exact `seg_membership.member_patch_idx` order; the helper validates finite `[N,C]` rows, observed unique source indices, co-indexed outlier flags, and `weight == N` including absorbed outliers. It pools only those rows and returns one transient segment/head value object with float32 pooled `acts[C]`, scalar `class1`, integer `weight`, exact source-index and outlier-flag tuples, segment ID, finite flag, and fixed boundary provenance. It never accepts structural `seg_meta.start_idx/end_idx` as membership. Any head-medoid value is an on-demand lookup of the catalog's observed `seg_meta.medoid_source_patch_idx` row from the same gather; no coordinate-wise median is computed. It has no IO/audio/model/ONNX/CUDA/segmentation/CTP behavior.

The canonical runner contract is:

```python
run_shared_ptc_head_pooling(
    con,
    head_store: HeadStreamStore,
    *,
    config_ids: Sequence[int] | None = None,
    song_ids: Collection[str] | None = None,
    heads: Collection[str] | None = None,
    run_id: str,
    reference_corpus_hash: str | None = None,
    force: bool = False,
) -> HeadPhaseManifest
```

The returned manifest records `run_id`, selected canonical `config_ids`, sorted dimensions, and deterministic per-config/head coverage and skip/error outcomes; it is JSON-safe and always marks the optional primary analysis as non-blocking.

Without `config_ids`, it selects canonical EffNet PTC `seg_config` rows from `configs_by_backbone(con, "effnet")` (`alias_of_config_id is None`, `semantics` in `direct_l2|std_scaled`, `bin_mode` in `temporal_global|temporal_perdim`, and `strategy_version == PTC_STRATEGY_VERSION`). It uses `segments_by_config_song` and `membership_by_config_song_seg` as the only membership source, validates source indices against the ready head record, gathers the union of exact rows once per song through `HeadStreamStore.batch_gather` (all heads in canonical sorted-column order), and slices heads using the registry `dim_by_head`. Pooled values are transient search-view values; observed head medoids are likewise read from the gathered `medoid_source_patch_idx`; no new pooled vector/cache/medoid artifact is written. The only durable head-analysis sink is non-blocking coverage/skip provenance in `head_phase_provenance`, including config ID, configured/effective threshold identity, semantics, fixed boundary/variant labels, finite status, counts, reason, and reference corpus hash; it never mutates primary catalog/membership/analysis/winner rows. No new PK/UNIQUE/index is introduced.

### Head-phase provenance migration (Plan E Phase 1 AMEND ROUND 2)

`head_phase_provenance` is migrated backup-first: take an `EXPORT DATABASE`/equivalent backup, create the replacement, copy rows, drop/rename in one transaction, and verify schema and readable rows before commit. The replacement has exactly these named columns and nullability: `run_id TEXT NOT NULL`, `config_id INTEGER NULL`, `backbone TEXT NOT NULL`, `head TEXT NOT NULL`, `bin_mode TEXT NOT NULL`, `threshold_configured DOUBLE NULL`, `threshold_effective DOUBLE NULL`, `semantics TEXT NULL`, `boundary_source TEXT NOT NULL`, `head_pool_variant TEXT NOT NULL`, `status TEXT NOT NULL`, `reason TEXT NULL`, `n_songs INTEGER NOT NULL`, `n_pooled INTEGER NOT NULL`, `finite INTEGER NOT NULL`, `scoring_semantics_version INTEGER NOT NULL`, `reference_corpus_hash TEXT NULL`, and legacy `threshold DOUBLE NULL`. It has no `PRIMARY KEY`, `UNIQUE`, or index. Existing rows are retained read-only with `run_id='legacy'`, old `threshold` populated, and `config_id`, `threshold_configured`, `threshold_effective`, and `semantics` NULL; canonical rows have non-NULL current fields and NULL legacy `threshold`. Any persisted timestamps elsewhere remain integer milliseconds.

The exact canonical-row predicate for readers, reports, fixtures, and coverage is `run_id <> 'legacy' AND config_id IS NOT NULL AND backbone = 'effnet' AND bin_mode IN ('temporal_global','temporal_perdim') AND threshold_configured IS NOT NULL AND threshold_effective IS NOT NULL AND semantics IN ('direct_l2','std_scaled') AND boundary_source = 'effnet_ptc' AND head_pool_variant = 'shared_effnet_ptc_boundary' AND threshold IS NULL`. Rows outside it are archival/unclassified, preserved and excluded. Application identity is `(config_id, backbone, head, bin_mode, threshold_configured, threshold_effective, semantics, boundary_source, head_pool_variant)`, excluding `run_id`; incoming duplicate identities are rejected, and a rerun transactionally replaces the existing current row for that identity without touching archival rows.

`classify.run_shared_ptc_head_pooling` remains callable as `LEGACY interim` live-ONNX/inclusive-range compatibility through Phase 4 and retains its legacy cache/manifest behavior; it never calls the canonical CPU runner or canonical persistence. Legacy `run.py` head-phase glue remains callable through Phase 4 and may append only archival rows marked `run_id='legacy'` with canonical-only fields NULL; it never dual-writes or creates a canonical current row. Phase 4 alone retires/rewires both surfaces. Pooled values remain transient, and head analysis does not mutate catalog/membership, primary corpus/winner, or `analyze_metrics` rows.

## Verification

Required tests cover direct/legacy threshold tracks, exact membership/medoids, one-pass loads, hashes/aliases, bounded oracle equivalence, lifecycle/fault/corruption, negative boundaries, root relocation/export-import, stale invalidation, scale/memory, run-scoped migration/resets/schema, CTP zero rows, fixture/report validation, full research pytest, compileall, ruff format/check, and an explicit diff audit excluding `nomarr/` and `frontend/`.

## Plan A baseline — implemented outcomes (Phases 1–2, 2026-09-02)

Concise contract-level record of what Plan A actually shipped, cross-referencing the
FINDINGS.md audit/reference sections. A full working-tree rewrite is Plan F; this is the
binding baseline recorded before then.

### P1-S1 — active / archival / dead inventory (full detail in FINDINGS "Part A audit")
- **Active primary**: `common/embed.py` sidecar write (frozen patch seam), `common/segment.py`
  sidecar read, `helpers/binning.global_dist` (direct unit-vector L2), pooling medoid,
  classify flat/binned + head phase (audio/ONNX boundary), `report/_*.py` (reads DB scalars +
  manifests only), written DuckDB tables (`songs`, `analyze_metrics`, `song_retrieval_metrics`,
  `stratified_corpus`, `phase_timings`, `head_phase_provenance`).
- **Archival (read-only compatibility, never primary input)**: `cache/flat_vecs`,
  `cache/binned_ptc`, `cache/binned_ptc_heads`, `cache/binned_ctp*`/`binned_ctp_heads`;
  `strategy_ptc/segment_fn` is the ACTIVE PTC writer but carries ARCHIVAL `std_scaled`
  threshold semantics (now explicit-only); `strategy_ctp/segment_fn` is archival scaled
  (per-song `score_std` multiplier) and phase-gated.
- **Dead candidates (no production change this plan)**: `_calibrate._calibrate` (0 live callers →
  `binned_calibration` never produced in normal runs), `_optimize._eval_threshold`/
  `optimize_std_threshold` (tests-only), `cache_identity.matrix_cache_identity`/
  `versioned_cache_root` (tests-only; `SCORING_SEMANTICS_VERSION=1` active), DuckDB tables
  `pooled_vecs`/`head_results`/`head_agreement_rows`/`patch_features`/`binned_pair_sims`/
  `binned_classify_ctp`/`truncation_robustness_rows`/`binned_ctp_vecs`/`binned_ptc_ctp_metrics`/
  `head_sim_corr_rows` (DDL'd, zero live writers). Removal is Plan E's decision — nothing deleted.

### P1-S2 — captured legacy references (full detail in FINDINGS "Part A legacy-fidelity reference capture")
- Legacy PTC effective threshold was `std_thresh × base_threshold`, `base_threshold = p50` only
  if a (never-produced) `binned_calibration` row existed, else the silent `0.1` default — the
  exact R2 configured-vs-effective gap. Configured `dist_thresholds = [0.95 … 1.5 step 0.05]`.
- Direct-L2 helper contract (`global_dist`) = direct unit-vector L2; `perdim_dist` = Chebyshev.
- Tolerance policy: **hashes exact; float matrices tolerance-bounded (documented rtol/atol)**,
  no bit identity. dtype/shape: float32 sidecars + unit-normed `(n_patches, dim)`; DB scalars
  float64→float.

### P2-S1..S3 — threshold decision + canonical identity
- `direct_l2` is the DEFAULT: `threshold_effective == threshold_configured` exactly, no
  multiplier, no DB lookup. `std_scaled` is EXPLICIT opt-in only and REQUIRES a recorded
  calibration basis (`statistic` + finite positive `value`); effective = configured × basis is
  recorded; no implicit p50/0.1 fallback in any form.
- API home: pure module `helpers/thresholds.py` (`ThresholdResolution`, `resolve_threshold`,
  `validate_semantics`, canonical encoders + `canonical_config_hash`) — free of
  DuckDB/IO/audio deps. `make_segment_fn(con, *, semantics="direct_l2", calibration_records=None)`
  routes through it; running-centroid algorithm unchanged.
- Canonical encoding contract: `canonical_float` = shortest round-trip repr with exponent
  expansion and `-0.0 → 0.0` (locale-independent, non-finite rejected); config hash is
  semantics-sensitive over a fixed field order; deterministic sha256. **No path parameter**
  anywhere in canonical identity/hash — identity is pure content, never path-derived (R3).
- **No-orphan guarantee**: legacy on-disk cache-path encoders (`helpers.binning.threshold_key`
  and `canonical_threshold`) are UNCHANGED so archival/legacy cache readers keep resolving;
  canonical encoding applies only to new seg_config identity/hash computation.
- Cross-plan record contracts (`StreamRecord`…`SearchViewRecord`, status vocabulary) defined in
  the shared planning ledger (artifacts/designs/parts/embedding-research-repair/CONTRACTS.md,
  Plan A P2-S4) — implementation is Plan B/C/D.

### P1-S4 — DuckDB dependency / version boundary
- `duckdb>=1.5,<2.0` (requirements.txt). `require_supported_duckdb()` gates the duckdb LIBRARY
  version to `1.5 ≤ v < 2.0` (fails loudly otherwise) at every research CLI phase startup.
- Storage-format version is an opaque **LABEL** (`storage_version_label`), never parsed or
  numerically compared; it is distinct from the library-version gate.
- A future DuckDB 2.x transition is a separately approved follow-up — not implied by this plan.
