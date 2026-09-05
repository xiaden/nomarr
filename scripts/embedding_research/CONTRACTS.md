# Embedding Research — Frozen Stream and Catalog Contracts

> Binding research API/schema reference for the frozen observation-stream refactor. This file supersedes the stale 18-table/copied-vector contract. During the staged corrective-pass migration, the registry row/column/status surface may remain only as rebuildable index/cache metadata for named downstream consumers; no legacy compatibility API, fallback reader, alias, adoption path, or dual write survives the final hard cut.

## Scope and invariants

Only `scripts/embedding_research`, its tests/docs, and formal planning artifacts are in scope. No production or frontend changes. A′ uses immutable float32 NumPy `.npy`/`.npz` sidecars plus DuckDB scalar metadata/catalog. Parquet, DuckDB BLOB/tar/Zarr payloads, ANN v1, optimizer prerequisites, DuckDB 2.x migration, and deferred production quantized streams are excluded.

Current invariants (post-Plan E P1-S5 hard cut): a single finite direct-L2 threshold contract with `configured == effective` exactly; the compact filesystem catalog whose structural `seg_meta` yields exact searchable `M_g` reconstructed on read (never a per-patch table, never an inclusive range), with absorbed outliers represented exactly and search medoids stored as observed source patch indices; class-1 `act[1]` canonical head pooling over `boundary_source="catalog"` / `head_pool_variant="shared_catalog_boundary"`; and catalog-scoped strategy-key identity decoded from `catalog:{backbone}:{score_variant}:v{version}:{keyset}`. Former invariants that named DELETED surfaces are historical only: the `global_pool:{backbone}:medoid` global identity (the `global_pool` strategy was removed in P1-S5; the report baseline is now the lowest active `(canonical_config_id, strategy_key)` catalog class), the `np.minimum((h_scores * 10).astype(np.int32), 9)` stratification formula (`db/stratify.py` deleted), and the running-spherical-centroid PTC semantics with `OUTLIER_WINDOW=3` (`strategy_ptc` deleted). Still held regardless of surface: no synthetic/coordinate `median`, no `agg_method=medoid`, no `disc_album`, no non-finite output, and no cross-backbone corpus mixing.

## Threshold and configuration contracts (current — Plan A corrective pass)

There is exactly ONE threshold contract: a finite DIRECT L2 distance between
normalized unit vectors, with `configured == effective` exactly.  Scaled
(`std_scaled`), calibration/p50, weighted-reduction, and per-threshold cache/
table vocabulary were removed and are historical only.  The pure API home is
`helpers/thresholds.py`, free of DuckDB/IO/audio deps:

```python
@dataclass(frozen=True)
class ThresholdResolution:
    configured: float      # finite
    effective: float       # finite; == configured exactly
    semantics: str         # == "direct_l2" (the only semantics)
    encoder_version: str   # SHA-256 of helpers/thresholds.py bytes (whole-module)

resolve_threshold(configured: object) -> ThresholdResolution   # single arg only
canonical_float(value: object) -> str      # finite; -0.0 -> "0.0"; rejects NaN/Inf
canonical_config_hash(*, backbone, bin_mode, threshold, outlier_window,
                      strategy_version, encoder_version) -> str
config_encoder_version() -> str            # lazy whole-module SHA-256, metadata-refreshed
```

`resolve_threshold` accepts only a finite numeric `configured` and always returns
direct normalized-unit-vector L2 semantics; it has no `semantics` or
`calibration_record` parameter.  The COMPACT snapshot ``seg_config`` rows (delivered by
Plan C) carry no ``semantics``/``calibration_record``/``alias_of_config_id`` columns —
the corrective compact model is canonical-only under a single direct-L2 semantics, and
the alias machinery plus those fields were dropped when the old research ``seg_*`` schema
was retired (P1-S12).

The strict configuration loader lives in `helpers/toml.py`:
`load_research_config(path: Path | None = None) -> CurrentResearchConfig` accepts
ONLY the executable current `[pipeline]` (EffNet default backbone; explicit
MusicNN opt-in) and `[analysis]` settings and raises distinct named errors
(`ResearchConfigMissingError`, `ResearchConfigSyntaxError`,
`ResearchConfigParserUnavailableError`, `ResearchConfigValidationError`) for a
missing/unparsable/invalid file — never warn-and-return `{}`.  See the appended
Plan A deletion inventory at the end of this file for the surfaces later plans
(B–E) remove.

## StreamStore contracts

```python
StreamStore.lookup(song_id: str, backbone: str) -> StreamRecord
StreamStore.batch_gather(song_id: str, backbone: str, source_patch_indices: Sequence[int]) -> np.ndarray  # float32[N,D]
StreamStore.register(...) -> StreamRecord
StreamStore.reconcile(...) -> ReconcileReport
```

`StreamRecord` fields: `song_id`, `backbone`, opaque root-relative `artifact_ref`, `patch_count`, `dim`, `dtype`, `format_version`, `fingerprint_sha256`, `preprocess_fn`, `preprocess_version`, `backbone_model_hash`, `audio_params`, `embed_semantics_version`, `provenance_source`, `provenance_assumption`, `status`, `run_id`, `created_at`, `updated_at`. Only `ready` records whose SHA-256, shape, dtype, finite values, and `allow_pickle=False` load validate may be gathered. Paths are never IDs or SQL keys.

Publication is staged `.tmp` write, file `fsync`, close, atomic rename, directory `fsync`, transactional `pending` registration, then reconcile to exactly `ready`, `missing`, or `corrupt`. Current filesystem manifests and observation commits are authoritative; registry rows are rebuildable index/cache metadata. Plan B removes legacy adoption/supersession internals and old bare/`.vN` parser branches after an orphan check, while downstream registry consumers remain until Plans C/E migrate them. Immutable current bytes are never replaced at an existing digest.

### Plan B retained-reader resolution handoff

> **Superseded by Plan E P1-S5 hard cut (2026-09-05).** This transitional Plan-B record is no longer
> current contract: every retained-reader module and test named in the list below was DELETED in the
> P1-S5 hard cut (see the deletion inventory below for the per-row EXECUTED dispositions). The
> subsection is retained as pre-Plan-E traceability only and must not be read as live module state.

Plan B (this pass, P1-S1) has COMPLETED the reader-resolution migration ahead of the digest-only writer switch: every retained bare-payload reader now resolves current stream payloads through ONE store-backed `CurrentStreamResolver` seam. The seam implementation and factory live in `streams/store.py` and are re-exported from `streams/__init__.py`; readers construct it from their available `con` (via a `StreamStore`) and accept an explicit resolver kwarg for injection:

```python
class CurrentStreamResolver(Protocol):
    def load(self, song_id: str, backbone: str) -> np.ndarray | None: ...


def make_current_stream_resolver(store: StreamStore) -> CurrentStreamResolver: ...
```

The seam uses `(song_id, backbone)` only to query the retained registry cache for the opaque `artifact_ref`, then gates on a row-`ready` registry entry and delegates payload read/validation (self-describing manifest + payload bytes) to the store. Observation-commit group authority is enforced by the group publication flow (`observation_group_ready`) and reindex, not by the resolver itself; production embed always publishes the observation group before reconcile, so every production-ready row is group-committed. It returns `None` for absent/non-ready payloads and fails closed for corrupt, stale, mismatched, or incomplete current artifacts. It never reconstructs bare/versioned names, scans/adopts old files, rehashes legacy output, or exposes filesystem paths. Existing reader-local `patches_path`/`_patches_path` monkeypatch seams may preserve their two-argument test shape only as explicit resolver injection; no default may fall back to the old config grammar. Runtime entrypoints use their existing `con`; direct helper tests inject a resolver, including `con=None` characterization calls.

The migrated retained reader list (now resolution-migrated by B, still whole-module deletion surfaces for E) is `common/segment.py::segment`; `classify.py::_classify_song`, `_classify_song_missing`, `run_flat`, `run_shared_ptc_head_pooling`, and `run_binned`; `strategy_binned/_optimize.py::optimize_std_threshold`; `strategy_global_pool/_embed.py::embed`; and `run.py`'s retained `_segment_phase`/`_classify_phase` resolver plumbing plus reset-side bare-path wording (`PATCHES_DIR` definitions remain as dead config, out of B's deletion scope). The named characterization tests remain behavior tests and migrate fixtures/monkeypatches to current digest artifacts or explicit resolver injection: `test_segment.py`, `test_gp_embed.py`, `test_quality_gate.py`, `test_head_phase_persistence.py`, `test_corpus_orchestration.py`, `test_analysis.py`, `test_score_variant.py`, `test_weighted_scoring.py`, `test_binned_process.py`, `test_gp_segment_fn.py`, `test_ctp_phase_gate.py`, `test_head_analysis_active.py`, `test_shared_boundary_head_phase.py`, `test_derived_phase_negative_boundaries.py`, `test_phase4_dispatch_boundaries.py`, `test_negative_boundaries.py`, and `test_p3s4_stale_cleanup.py`. Adjacent writer/layout tests `test_embed.py`, `test_infer_heads.py`, `test_stream_cpu_boundary.py`, and `test_stream_write_proxy.py` migrate with the digest publication switch. B changes only resolution; deletion of these retained modules/legacy dispatch remains E-owned, and C/E consume the retained registry row/status contract and B's store surfaces.

`HeadStreamRecord` and the analogous head store contain song/backbone, opaque artifact ref, patch count, canonical head IDs and dimensions, model-suite/preprocess provenance, alignment and format versions, fingerprint, status, and run. `infer-heads` publishes complete, finite `[T,C]` streams whose `T` matches the backbone patch count; missing or mismatched heads are rejected. Through Plan B, `HeadStreamStore.batch_gather(song_id, backbone, source_patch_indices, *, forbid_duplicates=False) -> np.ndarray` returns validated float32 `[N, total_dim]` rows with columns concatenated in canonical head order and source-index semantics. The active retained CPU consumer `common/head_analysis.py::run_shared_ptc_head_pooling` (and its interface-parity fakes/tests) relies on this concatenated three-argument shape while that E-owned surface remains in place. The previously proposed `Mapping[str, np.ndarray]` return and optional `heads=` selection parameter are formally deferred to the D/E window that rewrites/removes `common/head_analysis.py`; Plan C must not depend on them.

## DuckDB logical schema

New/maintained active tables use scalar columns and intentionally have no new `PRIMARY KEY`/`UNIQUE` constraints. Application checks and duplicate tests enforce identities.

- `stream_registry(song_id, backbone, artifact_ref, patch_count, dim, dtype, format_version, fingerprint_sha256, preprocess_fn, preprocess_version, backbone_model_hash, audio_params, embed_semantics_version, provenance_source, provenance_assumption, status, run_id, created_at, updated_at)`; identity `(song_id, backbone)`.
- `head_stream_registry(song_id, backbone, artifact_ref, patch_count, head_ids, dim_by_head, format_version, fingerprint_sha256, preprocess_fn, preprocess_version, backbone_model_hash, alignment_version, status, run_id, created_at, updated_at)`; identity `(song_id, backbone)`.
- The COMPACT segmentation-catalog core (`catalog_metadata`, `seg_config`, `catalog_song`,
  `seg_meta`, `run_provenance`) is NOT part of this research-DB schema.  It lives only in
  durable COMPACT FILESYSTEM catalogs (`catalogs/<catalog-id>/catalog.duckdb` + a published
  `catalog.manifest.json`, selected by `catalogs/current.json`); its column/DDL home with exact
  column tuples and the publish/open lifecycle are in `catalog_storage.py`, and the producer is
  `catalog.py::build_segmentation_catalog`.  The old research `seg_config` / `seg_meta` /
  `seg_membership` tables were removed in the corrective pass (P1-S12).
- `run_provenance(run_id, phase, status, started_at, finished_at, input_artifact_hashes, output_artifact_hashes, config_hash, song_count, warning_count, software_versions, command_line, structural_change_summary, retained, view_refs)`.
- singleton `corpus_state(state_version, registered_song_count, eligible_song_count, complete_flag, latest_catalog_run_id, reconciled_at, reconciliation_status)` (the `latest_search_view_hash` column was REMOVED under **Plan D P1-S2**); zero/one application check.
- `catalog_metadata(catalog_semantics_version, serialization_version, manifest_version, backbone_set, latest_run/config identifiers)`; metadata only.

No vector BLOBs, `view_manifest`, or artifact-classification table is introduced. Legacy tables are retained only when an explicit archival/golden obligation exists. `analyze_metrics` is migrated backup-first to include `run_id`, with legacy rows copied as `run_id='legacy'`; readers and writes are run-scoped.

**Current 10-table research schema (Plan E P1-S5 hard cut).** The retained DuckDB tables are exactly `songs` (PK `song_id`), `analyze_metrics` (run-scoped, no PK; legacy rows copied as `run_id='legacy'`), `song_retrieval_metrics` (PK `strategy_key,sim_metric,k,song_id`), `head_phase_provenance` (18-column canonical sink, no PK), `phase_timings` (PK `run_ts,phase`; the active efficiency source), and `stream_registry` / `head_stream_registry` / `run_provenance` / `corpus_state` / `catalog_metadata` (registry/provenance/catalog tables, no PK/UNIQUE). The thirteen obsolete copied-vector/threshold/stratification tables — `pooled_vecs`, `head_results`, `head_agreement_rows`, `patch_features`, `binned_pair_sims`, `binned_classify_ctp`, `binned_song_stats`, `truncation_robustness_rows`, `binned_ctp_vecs`, `binned_ptc_ctp_metrics`, `head_sim_corr_rows`, `binned_calibration`, and `stratified_corpus` — were PHYSICALLY REMOVED (DDL dropped, no replacement or compatibility DDL) in Plan E P1-S5 (Wave 2b), together with their dead writer/read paths (`db/binned.py`, `db/truncation.py`, `db/stratify.py`) and the now-empty `db/__init__.py` facade entries.

## Catalog and identity APIs

```python
# Catalog building (compact snapshot producer; catalog.py::build_segmentation_catalog)
build_segmentation_catalog(stream_store, mask_store, configs, song_ids,
                           *, output_root, run_id, verify=False) -> CatalogBuildReport

# Compact snapshot readers (over the snapshot con from
# catalog_storage.open_current_catalog / open_snapshot_file; see catalog.py)
compact_configs_by_backbone(con, backbone) -> tuple[CompactConfigRecord, ...]
compact_segments_by_config_song(con, config_id, song_id) -> tuple[CompactSegRecord, ...]
compact_catalog_songs_by_config(con, config_id) -> tuple[CatalogSongRecord, ...]
```

(Legacy research-DB helpers `configs_by_backbone` / `segments_by_config_song` /
`membership_by_config_song_seg` / `stream_by_song_backbone` and the record objects
`SegConfigRecord` / `SegMetaRecord` / `SegMembershipRecord` were removed in P1-S12.
`stream_by_song_backbone` is superseded by the store-backed `CurrentStreamResolver` seam.)

`config_id` is an integer application identity. A catalog pass loads one verified stream and one
mask per song/backbone and evaluates every threshold/config in one pass.  The COMPACT model stores
no per-patch membership: `seg_meta` holds structural `[start_idx, end_idx)` report ranges plus
canonical `absorbed_indices`, `absorbed_count`, and normalized `searchable_weight`; exact
searchable membership is reconstructed on read as `[start, end) − absorbed − mask-silent`, never
read from an inclusive range.  Segment and global search medoids store observed source indices
(`search_medoid_source_patch_idx`), never copied vectors.  Single-config rebuild deletes only that
config; full rebuild is explicit.  Application checks reject duplicate config/segment/singleton
identities without database constraints.

Canonical serialization sorts rows, fixes column/type/NULL/numeric encodings, and includes semantic/software versions. Per-song signatures include stream fingerprint and canonical config/membership/meta rows. Corpus identity was once carried by a strict `search_view_hash` (sorted song signatures, configs, stream fingerprints, catalog/manifest/software versions), but Plan D P1-S2 REMOVED it: search views are now per-run disposable keyset/content views with no durable corpus hash, and the strict-identity role is fully covered by manifest-only `catalog_fingerprint` plus per-song `song_signature` leaves (see the Plan D P1-S2 inventory row — module CONTRACTS rows note this removal). Manifest-only `catalog_fingerprint` hashes complete logical state but excludes its own value. Aliases map to canonical configs; reports expose configured/effective values, aliases, failed/empty songs, outliers, medoid changes, and structural changes. Planning scale arithmetic is approximately `10,000 × 100 × 10 ≈ 10M` catalog rows and is not an empirical claim.

## Disposable views and bounded scoring

```python
# §D binding surface (P1-S5).  candidate_view carries vectors + row_addresses and optional
# candidate_weights; chunk sizes are derived from `working_memory` (a positive byte budget).
# Explicit per-dimension chunk overrides remain for deterministic bounded-memory tests.
score_bounded_exact(
    query_vectors, query_weights, candidate_view: ScoringCandidateView, *,
    query_chunk_size=None,
    candidate_chunk_size=None,
    working_memory=None,
    tie_policy="first_index",
    collision_policy="retain_all_candidate_segments",
    expensive_trace=False,
) -> BoundedScoreResult

# §D small-fixture reference oracle (scoring_harness.py) — the v1 full-matrix reference
# that score_bounded_exact must match within the declared tolerance.
score_exact_oracle(
    query_vectors, query_weights, candidate_vectors, candidate_weights, ...
) -> OracleScoreResult
```

Views gather observed medoids through `batch_gather`, are keyset/content-addressed and ALWAYS regenerated per run (a file's existence never authorizes reuse), and record keyset/content hashes in `run_provenance.view_refs`. The keyset identity is built from backbone, run id, sorted config ids, sorted song ids, matrix shape/dtype, and `scoring_semantics_version` — there is NO corpus `search_view_hash` and no `(application_version, numpy_version, sklearn_version_or_null)` software triple (both removed under **Plan D P1-S2**; see the deletion inventory row). Row addresses are ordered `(config_id, song_id, seg_id, source_patch_idx)`; weights are per-row searchable-count-normalized (sum 1 per song; zero-searchable metadata-only songs contribute no row). v1 exact CPU is the future ANN seam; no ANN index is created.

The primary score is `max_per_candidate_segment` with `first_index + retain_all_candidate_segments`; the explicit alternative is `equal_tie_split + unique_source_max`. `working_memory` derives geometrically-equal float64 cosine chunk sizes (`chunk = max(1, int(sqrt(working_memory / 8)))`); each temporary query-x-candidate chunk is reduced to per-candidate scalars (max cosine, winner source index, tie count) and released — normal analysis retains **no N×N matrix and no per-pair trace**. Only `O(n_candidate)` reduced scalars and `O(n_source)` winner counters survive the streamed reduction. `expensive_trace=True` is an explicitly-labelled, opt-in debug mode (sets `result.trace_retained`) that still honours the same chunk limits and retains only a segment-level trace, never the pair product. All emitted values are finite (finite-only); a non-finite vector/weight is rejected, and an **empty candidate view** (zero searchable rows — the analyze scheduler excludes zero-searchable candidates upstream, so `analyze` never feeds one) yields a finite EMPTY result (score 0.0, zero retained/dropped) rather than NaN/Inf or a crash. `scoring_harness.py` remains the small full-matrix oracle and exposes the array-oriented §D reference `score_exact_oracle(...) -> OracleScoreResult` over `score_max_per_candidate_segment`. `score_bounded_exact` and `score_exact_oracle` compute identical float64 dot products and accumulate retained contributions in the SAME sequential ascending order over the retained candidates, so results are BITWISE equal on identical reduced inputs (identical retained sets, cosine maxima, tie/winner metadata — no reduction-order divergence). The declared bound `rtol = atol = 1e-12` covers any future ordering divergence (chunking never changes individual cosine elements). MAP, MRR, NDCG, Recall, and discrimination are separate evaluation lenses.

### Phase 1 (Plan D) implemented surface — `search_views.py`

Implements the ledger `SearchViewRecord` (Plan A P2-S4; Plan D). Catalog-first public API: `materialize_search_view(catalog, stream_store, *, song_ids, backbone, run_id, working_memory) -> SearchViewRecord` (catalog is duck-typed via `getattr(catalog, "con", catalog)`; gathers ONLY observed `seg_meta.search_medoid_source_patch_idx` medoids; no audio/model/ONNX/CUDA calls; finite-only, failing closed on non-finite source data) and `record_search_view(research_con, record, *, run_id=None)`. `SearchViewRecord` carries `keyset_hash`/`content_hash`/`view_ref`/`row_addresses`/`vectors`/`weights` and no `search_view_hash`. Removed under P1-S2: `SearchViewKey`, `AnalysisCorpus`, `QueryKeyset`, `search_view_hash`-bearing keysets, `validate_search_view_keyset`, `StaleSearchViewError`, and the software-version triple. Views are single-backbone; config ids default to every canonical `seg_config` of the backbone.

**On-disk payload (disposable views).** Each view is written under the stream store's output root at `views/<keyset_hash>/` (`view_ref` is the root-relative `views/<keyset_hash>`), physically `vectors.npy` (float32 `[N, D]`, `allow_pickle=False`; row `i` = `row_addresses[i]`) plus `keys.json` (canonical keyset + ordered `rows` `[config_id, song_id, seg_id, medoid_source_patch_idx]`). Medoids are gathered ONLY by catalog `seg_meta.search_medoid_source_patch_idx` via `batch_gather`, never from ranges/copies/paths. `content_hash` = sha256 over `keyset_hash` + ordered row lines + little-endian float64 weights + little-endian float32 vector `tobytes()`, recomputable independently of the file bytes.

**Provenance.** `record_search_view` writes a canonical `keyset_hash|content_hash|view_ref` line into the existing `run_provenance.view_refs` (phase `analyze`, `retained=False`), deduped by keyset hash and preserving other runs incl. `retained` rows; no new table. Materialization ALWAYS regenerates (gathers + rewrites); identity is keyset/content validation against the CURRENT catalog, never file presence and never a durable `search_view_hash`. No `view_manifest`/second registry, no indexes, no PK/UNIQUE, no ANN/VSS (exact CPU v1).

### Phase 1 (Plan D) P1-S3 implemented surface — search-representation collapse (`catalog_identity.py`)

```python
@dataclass(frozen=True)
class SearchRepresentationClass:
    search_representation_hash: str
    canonical_config_id: int
    config_ids: tuple[int, ...]   # canonical first, ascending
    alias_ids: tuple[int, ...]    # non-canonical members, ascending (property)
    n_configs: int

search_representation_hash(catalog, config_id) -> str   # DD L263
collapse_search_representations(catalog) -> tuple[SearchRepresentationClass, ...]  # DD L266
exact_segmentation_hash(catalog, config_id) -> str      # DD L258 (identity/hash surface)
```

`collapse_search_representations(catalog)` recomputes, from CURRENT compact `catalog_song`
`search_leaf` rows on EVERY call, the deterministic equivalence classes of a catalog's
``seg_config`` rows keyed by :func:`search_representation_hash`
(``SHA256(encoder_version || scoring-input semantics || sorted search leaves)`` — the canonical
config fields such as ``threshold_effective`` are deliberately EXCLUDED).  Two distinct direct
thresholds that segment the SAME frozen streams into identical searchable medoid sets therefore
collapse into ONE class so the scorer runs once for all of them; structural differences never
prevent collapse when the actual scoring inputs match.  Each class canonical config is the lowest
member ``config_id``; members/aliases are sorted ascending; classes are sorted by canonical
``config_id``.  ``exact_segmentation_hash`` (``SHA256(encoder_version || canonical config fields ||
sorted exact leaves)``) additionally includes the canonical config fields, so search-collapsed configs still carry DISTINCT exact hashes and remain structurally distinguishable.  There is NO durable alias graph / alias column / alias file — equivalence classes are a pure read recomputed from stored search hashes every run.  ``catalog`` is a compact CatalogHandle / snapshot connection (duck-typed via ``getattr(catalog, "con", catalog)``).

**Plan D analyze DTO and scheduling contract.** ``analyze_catalog_corpus`` materializes one disposable all-config view for the run, then projects the canonical (lowest ``config_id``) rows for each current ``SearchRepresentationClass``. Each logical query/candidate scoring input executes once per class; alias rows are never appended to the candidate union, so they cannot double-count candidates, weights, winners, retained rows, or deltas. Distinct classes retain the ordinary bounded query/candidate loop and combine with the existing ``max_per_candidate_segment`` semantics; normal analysis does not retain a full N×N trace. ``CatalogAnalysisResult.config_ids`` is the sorted tuple of every participating config, while transient ``representation_classes`` carries each search hash's canonical ID and sorted aliases. ``n_candidate_rows`` and every ``PerQueryResult.candidate_keys`` count/reference canonical searchable medoid rows only, deterministically sorted; ``candidate_scores`` and ``winner_counts`` retain the existing finite corpus/winner schema. Alias configs inherit the canonical class's identical score, winner, and delta identity through this transient mapping; no alias-specific persisted rows or durable alias state is introduced, and structural/exact identity remains distinct through the catalog/report surfaces.

**Lazy attach + typed refusal (P1-S4).** ``analyze_catalog_corpus``/``run_catalog_analysis`` accept a compact ``CatalogHandle``, a snapshot connection, or a snapshot PATH string. A path is opened read-only at run time (lazy attach) and closed in ``finally``; a non-compact connection (no ``seg_config`` / no rows for the backbone), a missing snapshot, or a corrupt/non-DuckDB file raises the typed ``CatalogRefusalError`` (exported from ``common.catalog_analysis``) and fails CLOSED — there is NO silent skip and NO stale-catalog fallback. Writes stay strictly run-scoped: the analysis touches only its own (``run_id``, scope) rows and never issues a global DELETE of ``analyze_metrics`` or of retained/other-run rows (a re-run leaves retained + unrelated rows intact).

**Single source of truth.** The §C report path (`catalog_report._derive_transient_collapse`)
delegates to :func:`collapse_search_representations`, so report alias evidence and the Plan D
analysis path share one collapse implementation.  Spec tests: `tests/test_search_representation_collapse.py`.

## Shared heads, CTP, cleanup, and CLI

Head analysis uses frozen aligned head streams and exact catalog membership (including absorbed outliers), the ACTIVE labels `boundary_source="catalog"` and `head_pool_variant="shared_catalog_boundary"`, class-1 `act[1]`, finite outputs, and non-blocking provenance. Inclusive ranges cannot define head membership. **CTP is hard-disabled, non-runnable, and its whole legacy surface is DELETED (Plan E P1-S5)**: Plan A removed the `[archival_ctp]` switch and the strict `helpers/toml.py` loader rejects the section, so no config can enable CTP and no CTP work/config/vector/row occurs in any run; Plan E P1-S5 then deleted the retained CTP module/cache/table inventory (see the deletion inventory below). The older `effnet_ptc`/`shared_effnet_ptc_boundary` boundary labels were renamed to `catalog`/`shared_catalog_boundary` in the corrective pass.

Active artifacts are streams/head streams/registries/catalog/manifest/provenance/current analysis/docs. The former archival/dead classes — legacy flat/PTC/head/CTP caches and readers, compatibility tables, copied medoid vectors, obsolete tables/writers, and zero-caller APIs (incl. `classify.py`/`head_pooling.py`/`pooling.py`/`corpus.py` and the `strategy_*` modules) — were deleted outright in the Plan E P1-S5 hard cut (Wave 2b), so no archival/dead artifact remains to classify. Current-format cleanup scopes are `staging`, `stray`, and `views` (report-then-remove, current-format grammar + manifest relationships only); `reset --scope analysis` removes only the disposable `research.duckdb`(+WAL) and disposable views. The obsolete `dead`/`archival`/`analysis-run` scopes are gone from the CLI and their module-level table/cache deletion was completed in Plan E P1-S5 (Wave 2b); `cleanup_current` accepts only `staging`|`stray`|`views` and `reset` only `analysis`. Normal analysis never globally deletes Tier 1/2 results.

CLI boundaries are exactly the eight phases `ingest`, `embed`, `infer-heads`, `catalog`, `catalog-report`, `analyze`, `head-analysis`, and `report` plus the four maintenance commands `verify`, `reindex`, `cleanup`, and `reset`. Legacy aliases (`stratify`, `segment`, `classify`, `head`) and unknown commands exit `2`. Only the first three phases may discover audio/load models/create sessions/run ONNX. Derived phases work without audio/models/ONNX/CUDA and support `--verify`; a rollback-only canary over every surviving legacy PK/UNIQUE table runs when `--verify` is set or when a post-crash signature is detected (a surviving `<db>.wal` or any non-`completed` `run_provenance` row) before derived-phase reads, blocks on failure, and instructs EXPORT/IMPORT repair. SIGKILL is bookkeeping/order evidence, not power-loss durability proof.

One exclusive run lock (`fcntl.flock` non-blocking) guards every branch that opens the DB or mutates artifacts — all eight phases and verify/reindex/cleanup/reset. The lock file lives at `OUTPUT_ROOT/.run-lock` when the output root is local, else under the local temp dir keyed by a hash of the resolved DB path (never beside an unreliable non-local file). Contention exits `2` with a diagnostic; the lock is released on every exit path. `verify [--strict]` audits current-format manifests/payloads/digests/shape/finite and the current catalog, owns read-write WAL recovery/checkpoint of a WAL-bearing current catalog, and refuses corruption (commit markers are not part of verify's scope — `reindex` / `reconcile_current_manifests` validates them); `--strict` freshly rehashes every payload so a same-size tamper is caught. `reindex` is a thin public wrapper over `reconcile_current_manifests` and never opens audio/models/sessions. Exit codes: `0` success, `1` validation/refusal/corruption, `2` lock contention or usage.

### Canonical CPU shared-head analysis (Plan E Phase 1 corrective pass)

The active derived head-analysis surface is `common.head_analysis.run_shared_catalog_head_analysis`
(CPU-only). It is the sole home for canonical CPU head pooling; the legacy live-ONNX `classify.py`
(`run_shared_ptc_head_pooling`) and the top-level `head_pooling.py`
(`pool_head_outputs_over_ptc_boundaries`) were DELETED in Plan E P1-S5 (Wave 2b) and no longer
exist. The canonical runner contract is:

```python
run_shared_catalog_head_analysis(
    catalog: CatalogHandle,
    head_store: HeadStreamStore,
    *,
    config_ids: Sequence[int] | None = None,
    song_ids: Collection[str] | None = None,
    heads: Collection[str] | None = None,
    run_id: str,
) -> HeadAnalysisManifest
```

`catalog` is a compact `CatalogHandle` (or a duck-typed object exposing `.con`); reads resolve
`con = getattr(catalog, "con", catalog)` exactly as `analyze_catalog_corpus` does. The returned
`HeadAnalysisManifest` records `run_id`, the selected canonical `config_ids`, per-config/head/song
coverage counts (`n_songs`/`n_pooled`), finite status, and deterministic skip/error outcomes; it is
JSON-safe (no new PK/UNIQUE/index, no durable pooled vector). Pooled head values stay transient; the
only durable head-analysis sink is non-blocking coverage/skip provenance written by the caller into
`head_phase_provenance`. Skip/error reasons are recorded with a config-level scope `config:{config_id}`
and, for per-song skips, the scope grammar `config:{config_id}:song:{song_id}` (tests in
`tests/test_catalog_head_analysis.py` assert those reason scopes).

Membership is exact searchable `M_g`, reconstructed per `(config_id, song_id)` from the COMPACT
structural `seg_meta` ranges (`start_idx` inclusive, `end_idx` exclusive) minus `absorbed_indices`
via `helpers/segmentation.reconstruct_searchable_indices` — never an inclusive/absorbed-inclusive
range and never a `seg_membership` per-patch table (there is none). The signature carries no
silence-mask seam and no committed mask loader exists on this path, so reconstruction passes
`mask=None`, matching the catalog's own build semantics (structural span minus absorbed). Eligible
selected configs are COMPACT canonical (`canonical_config_hash` non-empty) with `semantics ==
"direct_l2"`, `bin_mode` in `temporal_global|temporal_perdim`, and `strategy_version ==
PTC_STRATEGY_VERSION`; without `config_ids` the runner selects exactly those eligible EffNet compact
configs. Gathered head values are read via `HeadStreamStore.batch_gather` over the exact union of
searchable source indices once per song, and per-head columns are sliced in canonical `dim_by_head`
order. The pooled head value is the class-1 `act[1]` channel (never `act[0]`); any head-medoid value
is an on-demand lookup of the catalog's observed `search_medoid_source_patch_idx` row from the same
gather — no coordinate-wise median and no synthetic value. The runner is finite, CPU-only, and fails
closed on non-finite input; it never discovers audio, loads a model/session, runs ONNX/CUDA, or runs
segmentation/CTP. It never mutates primary catalog/membership/analysis/winner rows.

### Head-phase provenance (Plan E Phase 1 corrective pass) — canonical-only

`head_phase_provenance` is the durable head-analysis sink. It has exactly these named columns and
nullability: `run_id TEXT NOT NULL`, `config_id INTEGER NULL`, `backbone TEXT NOT NULL`, `head TEXT
NOT NULL`, `bin_mode TEXT NOT NULL`, `threshold_configured DOUBLE NULL`, `threshold_effective DOUBLE
NULL`, `semantics TEXT NULL`, `boundary_source TEXT NOT NULL`, `head_pool_variant TEXT NOT NULL`,
`status TEXT NOT NULL`, `reason TEXT NULL`, `n_songs INTEGER NOT NULL`, `n_pooled INTEGER NOT NULL`,
`finite INTEGER NOT NULL`, `scoring_semantics_version INTEGER NOT NULL`, `reference_corpus_hash TEXT
NULL`, and `threshold DOUBLE NULL`. It has no `PRIMARY KEY`, `UNIQUE`, or index. `run_id` is an
integer-millisecond-stamped run identity supplied by the CLI caller (e.g.
`head-analysis-{started_at_ms}`); there is no `run_id='legacy'` concept, no archival migration, and no
archival append/build/query readers on this surface (the legacy 13-column to 18-column backup
migration and the archival `append_head_phase_archival_rows`, `build_archival_provenance_rows`,
`query_head_phase_done`, `load_head_phase_provenance_all`, and `is_canonical_row` helpers were deleted
with the P1-S2 corrective pass). The `threshold` column is retained only as a `NULL`-for-canonical
column.

The exact canonical-row predicate for readers, reports, fixtures, and coverage is `config_id IS NOT
NULL AND backbone = 'effnet' AND bin_mode IN ('temporal_global','temporal_perdim') AND
threshold_configured IS NOT NULL AND threshold_effective IS NOT NULL AND semantics IN ('direct_l2')
AND boundary_source = 'catalog' AND head_pool_variant = 'shared_catalog_boundary' AND
threshold IS NULL`. The canonical surface is EffNet-only (`backbone = 'effnet'`); the active bin modes
are the two `TEMPORAL_BIN_MODES` values and the semantics are `PTC_SEMANTICS` (`direct_l2`). Rows are
canonical-only; there is no archival/unclassified partition. Application
identity is `(config_id, backbone, head, bin_mode, threshold_configured, threshold_effective,
semantics, boundary_source, head_pool_variant)`, excluding `run_id`; incoming duplicate identities
are rejected, and a rerun transactionally replaces the existing current row for that identity.
Writing is canonical-only — no shim, alias, fallback, or dual-write. Pooled values remain transient,
and head analysis does not mutate catalog/membership, primary corpus/winner, or `analyze_metrics` rows.

## Report contract (schema v2 — seven sections, active catalog only)

The `report` phase (`_run_report` in `run.py`) is the executable entry point. It renders exactly
seven sections in this order: `summary`, `corpus`, `analysis`, `winners`, `head-analysis`,
`provenance`, `efficiency`. `summary` shows active catalog-result status per backbone (winner /
delta / factor summary or an explicit empty-active-results message); `corpus` shows active songs /
corpus health; `analysis` shows ONLY `analyze_metrics` rows with `strategy_type == 'catalog'`
(run_id / sim_metric / k / metric / value plus catalog strategy identity, score variant,
scoring-semantics version, view-content-hash provenance, canonical config id, and sorted alias
ids); `winners` shows deterministic winner / delta / factor tables per backbone; `head-analysis`
shows canonical `head_phase_provenance` per supported backbone with finite / status / coverage and
provenance; `provenance` shows active `run_provenance`, command lines, hashes, warnings,
reuse/refusal decisions, and limitations; `efficiency` shows retained `phase_timings`. Emitted keys
are active-only; no emitted section/table ID, title, key, warning, or value uses forbidden legacy
vocabulary or a retired phase name. `run.py` passes the selected completed report run scope into the
renderer/loader (or uses the active completed scope when none is supplied) and writes only
`report.json`/`report.html` without inference. The fixture/validator contract is an input to Plan F's
final evidence report — it is not that separate report.

## Verification

Required tests cover direct/legacy threshold tracks, exact membership/medoids, one-pass loads, hashes/aliases, bounded oracle equivalence, lifecycle/fault/corruption, negative boundaries, root relocation/export-import, stale invalidation, scale/memory, run-scoped migration/resets/schema, CTP zero rows, fixture/report validation, full research pytest, compileall, ruff format/check, and an explicit diff audit excluding `nomarr/` and `frontend/`.

## repair-plan Plan A baseline — implemented outcomes (Phases 1–2, 2026-09-02) — HISTORICAL

> **HISTORICAL — pre-corrective-pass record (superseded).** This section is a dated
> snapshot from the earlier *repair-plan* era, recorded before the corrective pass (the
> current Plan A) hard-cut the threshold/configuration foundation. It is **not** current
> contract and must not be read as asserting present-day module state. The corrective-pass
> Plan A — the §"Threshold and configuration contracts" section above and the appended
> deletion inventory ("Already removed in Plan A") — supersedes it. Nothing here is a
> binding baseline for current behavior; if a statement below conflicts with those current
> sections, it describes pre-cut (now-removed) surface only. Retained purely as a
> historical record for repair-plan traceability. In particular the following pre-cut
> sentences are superseded by corrective-pass Plan A: **L193–194** (`strategy_ptc/
> segment_fn` carrying ARCHIVAL `std_scaled` semantics — `make_segment_fn` is now
> direct-L2-only and the former `std_scaled` track is gone); **L215–218** (`std_scaled` as
> explicit opt-in requiring a recorded calibration basis — removed per the deletion
> inventory); **L219–221** (API home listing `validate_semantics` — that function no longer
> exists on `helpers/thresholds.py`); and **L223–226** (config hash "semantics-sensitive
> over a fixed field order" — `canonical_config_hash` takes no semantics input).

Concise contract-level record of what repair-plan Plan A shipped before the corrective
pass, cross-referencing the FINDINGS.md audit/reference sections. A full working-tree
rewrite is Plan F.

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
  (per-song `score_std` multiplier) and hard-disabled (non-runnable — its `[archival_ctp]`
  switch is removed, so it produces no rows in any run; deletion inventoried under Plan E).
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

## Plan A deletion inventory (authoritative for Plans B–E)

Plan A (this corrective pass) hard-cuts the threshold/configuration foundation
(`helpers/thresholds.py`, `helpers/toml.py`, `research_config.toml` and their direct
consumers) to the single finite direct-L2 contract and the strict current schema.
Everything below is a **recorded whole-tree deletion surface owned by a later
plan** (B–E). It is inventoried NOW so those plans can execute deletions from this
list; Plan A does not delete it. The whole-tree audit
(`tests/test_audit_forbidden_vocabulary.py`) allows these recorded surfaces to
retain their historical vocabulary and tightens as each entry is deleted (removing
an inventory entry makes any remaining hit in a retained file fail).

**Completion (Plan E P1-S5, Waves 1–3, 2026-09-05).** Every ``E``-owned whole-module/whole-file
row above now carries an ``EXECUTED (P1-S5)`` marker (or a dated ``EXECUTED (P1-Sn)`` marker from an
earlier plan) with the specific deletion or retained-stripped disposition. Only the two D-owned
retained-traceability rows and the path-derived B row remain unmarked by design. The audit allowlist
was re-censused after the deletions (Wave 3) so no entry is kept against a now-empty surface.

**Test-file surfaces.** Each deletion surface below also includes the `tests/` files
that mirror it (test the module(s) or import their symbols), per the DD "…and their
tests" qualifiers. A later plan deletes a row's module surface together with those
tests; the audit's allowlist tightens as each becomes removable. Representative test
homes are named in the relevant Notes below (e.g. CTP → `test_ctp_phase_gate.py` /
`test_ctp_segment_fn.py` and CTP-path negatives; ANN/FAISS → `test_similarity.py` /
`test_ann_seam_boundary.py`), but the qualifier is not limited to those examples.

### Whole-module / whole-file deletion surfaces (owner plan)

| Surface | Current location(s) | Owner | Notes |
|---|---|---|---|
| Legacy classify surface | `classify.py` | E | classifier + CTP head bins. **EXECUTED (P1-S5):** `classify.py` deleted (Waves 1–2b); retained classify-gate mirror tests migrated/deleted. |
| Legacy head pooling | `head_pooling.py`, `common/head_analysis.py`, `db/head_phase.py`, `db/flat.py`, `report/__init__.py` (head_pooling) | E | pre-catalog CPU head pooling (replaced by catalog head-analysis). **EXECUTED (P1-S5):** `head_pooling.py` deleted; `common/head_analysis.py` + `db/head_phase.py` RETAINED (canonical catalog head-analysis surface); `db/flat.py` RETAINED-stripped; `report/__init__.py` migrated to the seven-section catalog report contract. |
| CTP strategy + segment fn | `strategy_ctp/`, `classify.py`, `db/_schema.py` (ctp tables), `db/canary.py` | E | `[archival_ctp]` config already removed (Plan A); tests: `test_ctp_phase_gate.py`, `test_ctp_segment_fn.py`. **EXECUTED (P1-S5):** `strategy_ctp/` + `classify.py` deleted; `db/_schema.py` ctp-table DDL dropped (P1-S5 13-table removal); `db/canary.py` RETAINED (dynamic `duckdb_constraints()` enumeration; historical CTP labels removed from executable canary strings); retained classify-gate tests deleted. |
| PTC/binned legacy readers + weighted optimizer | `strategy_ptc/`, `strategy_binned/`, `strategy_global_pool/`, `helpers/binning.py`, `db/binned.py`, `cache/binned_ptc*.py`, `report/_binned.py` | E | threshold-specific copied-vector/keyset architecture; weighted/optimizer vocab. **EXECUTED (P1-S5):** `strategy_ptc/`, `strategy_binned/`, `strategy_global_pool/`, `db/binned.py`, `cache/binned_ptc*.py`, `report/_binned.py` deleted (strategy_binned whole package under authorized option (c)); `helpers/binning.py` RETAINED-stripped (legacy constants removed; the executable `PTC_BIN_MODES`→`TEMPORAL_BIN_MODES` constant now lives in `common/head_analysis.py`). |
| ANN / FAISS | `similarity.py` | D | `ANNIndex`, `ann_recall_sweep`, FAISS backend; tests: `test_similarity.py`, `test_ann_seam_boundary.py`. **EXECUTED (P1-S6):** similarity.py ANN surface + ANN tests deleted; row retained for E remnant audit. Scope note: the `ANNIndex` class, `ann_recall_sweep`, the optional FAISS/ANN backend (lazy `import faiss` / `_FAISS` flag / numpy-fallback warning), and the `faiss-cpu` research dependency were removed; `similarity.py` now contains ONLY exact CPU similarity/metrics (`cosine_matrix`, `l2_normalise`, `METRICS`, `_rankings_from_sim`, `compute_retrieval_metrics`, `DISC_HEAD_*`) plus the sklearn NDCG helper — none of the exact-CPU functions was deleted (all had live callers when P1-S6 executed — `strategy_binned/_process.py`, `common/analyze.py`, and the retrieval tests; the two named modules were themselves deleted in the Plan E P1-S5 hard cut, so current executable callers of these exact-CPU functions are the retrieval tests only). No retained test imported/executed the ANN symbols (test_similarity.py imports only exact-CPU functions and is RETAINED; test_ann_seam_boundary.py is a retained negative boundary test over the exact-CPU modules and needs no ANN symbols). Negative audit tightened: `faiss`/`hnsw`/`_faiss` added to the forbidden-token set and the `annindex`/`ann_recall_sweep` allowlist entries removed (zero residual executable hits), so any future executable ANN reference in a retained research file FAILS. |
| Matching-corpus manifests | `corpus.py`, `tests/test_corpus_manifest.py` | E (QA Round-1) | deterministic `MatchingCorpusManifest` / `build_matching_corpus` / `corpus_identity_hash` / `validate_matching_corpus`. **EXECUTED (P1-S5 post-QA):** zero retained callers (only the mirror test imported it); superseded by the compact catalog + Plan D/E `catalog_identity` catalog-first identity. `corpus.py` + `tests/test_corpus_manifest.py` deleted (whole file was corpus-only). Distinguish RETAINED `report/_corpus.py` (owns the `corpus` report section) and the retained `db` `corpus_state` table/functions. |
| Old caches | `cache/binned_ctp*.py`, `cache/flat_heads.py`, `cache/flat_vecs.py` (flat_vecs under strategy_global_pool), `cache/binned_ptc*.py`, `cache_identity.py` | E | CTP/PTC/flat head/vector caches. **EXECUTED (P1-S5):** `cache/*` (`binned_ctp*`, `binned_ptc*`, `flat_heads`, `flat_vecs`) and `cache_identity.py` deleted. |
| Dead zero-caller DuckDB tables | `db/_schema.py` (DDL: `pooled_vecs`, `head_results`, `head_agreement_rows`, `patch_features`, `binned_pair_sims`, `binned_classify_ctp`, `binned_calibration`, `binned_song_stats`, `truncation_robustness_rows`, `binned_ctp_vecs`, `binned_ptc_ctp_metrics`, `head_sim_corr_rows`); dead writer modules `db/binned.py` (`upsert_calibration`, `upsert_binned_song_stats`) and `db/truncation.py` (`upsert_truncation_robustness`) | E | DDL'd, zero live writers (`cleanup --scope dead` candidates); no producer writes them in normal runs. **EXECUTED (P1-S5, Wave 2b):** the twelve DDL blocks in `db/_schema.py` + writer modules `db/binned.py` (`upsert_calibration`/`upsert_binned_song_stats`) + `db/truncation.py` (`upsert_truncation_robustness`) deleted; the `stratified_corpus` table (same wave, no active writer/reader after `db/stratify.py` deletion) + `db/stratify.py` also removed; schema is now the ten retained tables. |
| Legacy run.py orchestration | `run.py` legacy orchestration (ModelCache/`_build_model_cache`, strategy key/decode helpers, `_load_{global_pool,ptc,ctp}_analyze_vecs`, `_install`, `_reset_db`/`_reset_cache_dirs`, `_build_ctp_segment_infra`, module/`_run_in_batches_fn`, legacy phase wrappers `_ingest`..`_classify`/`_stratify`/`_segment`/`_analyze`/`_report`, `_manifest_for`/`_ctp_enabled`/`_corpus_requirements`/`_build_backbone_manifests`, `_LEGACY_PHASES`, `PTC_STRATEGY_NAMES`/`_KNOWN_CTP_HEAD_NAMES`, `{GLOBAL_POOL,PTC,CTP}_ANALYZE_CFG`) | E (P1-S3 DONE) | **deleted in Plan E P1-S3** (run.py is now the 8-phase + `verify`/`reindex`/`cleanup`/`reset` CLI under one exclusive run lock); superseded imports removed. `common/analyze.py`, `common/stratify.py`, `report/_optimizer.py`, `db/analyze_scope.py`, `db/provenance.py`, `db/queries.py`, `db/songs.py`, `common/catalog_analysis.py`, `report/*.py` (binned/retrieval/summary/winners/heads/base) | E | old phase orchestration, stratify (not a phase), optimizer/weighted report sections |
| `search_view_hash` | `catalog_identity.py`, `catalog_report.py`, `search_views.py`, `db/catalog_metadata.py`, `db/provenance.py`, `common/catalog_analysis.py`, `common/embed.py`, `db/analyze_scope.py` (scope read/write incl. `corpus_state.latest_search_view_hash` persistence), `db/_schema.py` (corpus_state `latest_search_view_hash` column DDL) | D | **EXECUTED (P1-S2):** absent from final identity — every listed file stripped of the executable symbol; `search_views.py` rewritten catalog-first (`materialize_search_view(catalog, stream_store, *, song_ids, backbone, run_id, working_memory) -> SearchViewRecord` with keyset/content identity and run-scoped disposable views, no `SearchViewKey`/`AnalysisCorpus`/`QueryKeyset`/`validate_search_view_keyset`/`StaleSearchViewError`/software-triple); `corpus_state.latest_search_view_hash` column dropped from DDL + `corpus_state_columns`/`update_corpus_state`; `CatalogReport.search_view_hash` field and `ci.search_view_hash` fn removed (fingerprint/exact/search snapshot hashes carry the report hash axis); analyze-scope field renamed to `view_content_hash`; audit tightened (token now forbidden, zero allowlist entries); tests retargeted/deleted (`test_search_views.py` slimmed to catalog-first, strictness + stale-keyset negatives removed, `test_bounded_golden` view-identity block retargeted/deleted). Row retained for traceability. |
| Per-patch membership tables | `db/_schema.py` (`seg_membership`), `db/segmentation.py` (`calibration_record` column) | C | **EXECUTED (P1-S12):** research `seg_membership` removed; no per-patch membership is stored (compact `seg_meta` holds structural ranges + `absorbed_indices`; exact searchable membership is reconstructed on read). Row retained for traceability. |
| Alias machinery | `db/_schema.py`/`seg_config` alias_of_config_id, `db/segmentation.py`, `catalog_report.py` (alias rows), `generate_fixture_report.py` (`rep_a`/`rep_b` field strings) | C | **EXECUTED (P1-S12):** `alias_of_config_id`/alias machinery removed (compact `seg_config` is canonical-only; alias/collapse evidence is transient from hashes). Row retained for traceability. |
| `rep_a`/`rep_b` / weighted-reduction field strings | `bounded_scoring.py`, `cache/binned_ptc.py`, `cache_identity.py`, `report/_base.py`, `report/_binned.py`, `report/_heads.py`, `report/_retrieval.py`, `report/_summary.py`, `report/_winners*.py`, `generate_fixture_report.py`, `db/_schema.py`, `common/analyze.py`, `db/binned.py`, `strategy_binned/_process.py` | D/E | old optimizer/report field vocabulary. **EXECUTED (P1-S5):** weighted-reduction `rep_a`/`rep_b` field-vocabulary surfaces deleted with their modules (`bounded_scoring.py`, `cache/binned_ptc.py`, `cache_identity.py`, `db/binned.py`, `report/_binned.py`, `strategy_binned/_process.py`, `common/analyze.py`, and the legacy `generate_fixture_report.py`); retained report/analysis vocabulary is catalog-only (see the report-contract section). Remaining allowlist entries reference only docstring/prose traceability or deleted files (audit census — see Wave 3). |

**Plan E P1-S5 dispositions for the composite run.py row above.** The ``Legacy run.py
orchestration`` cell was deleted in Plan E P1-S3 (run.py is the frozen 12-command CLI). The
modules listed in its ``Current location(s)`` column split as follows in P1-S5:
``common/analyze.py``, ``common/stratify.py`` and ``report/_optimizer.py`` were DELETED (Waves
1–2b); ``common/catalog_analysis.py``, ``db/analyze_scope.py``, ``db/provenance.py`` are ACTIVE
(retained, not deletion surfaces); ``report/*.py`` were RETAINED and migrated to the seven-section
catalog contract; and ``db/queries.py`` + ``db/songs.py`` were RETAINED-stripped (dead-table
progress helpers / legacy writers removed). No row in this table is still owned-pending: every
row either carries an ``EXECUTED`` marker above (retained-stripped where noted) or is retained
for P1-S6 traceability.

### Path-derived / legacy-id vocabulary (owner plan)
`streams/store.py` `_classify_rowless`, `register_legacy`, `_family_versions`,
`_next_artifact_ref` (old artifact parser/adoption branches), plus their legacy name-parse
dependency `streams/publication.py` `parse_artifact_name` (legacy/versioned on-disk-name
branches) — owner B, conditional on the post-rebuild orphan check.

**DELETED in Plan B (P1-S2, completed):** B removed `register_legacy`,
`_family_versions`, `_next_artifact_ref`, and `_classify_rowless` from `streams/store.py`
and deleted the bare/`.vN`/legacy/versioned `parse_artifact_name` branches from
`streams/publication.py`. `parse_artifact_name` itself is RETAINED as the digest-only
parser (returns an `ArtifactIdentity` or `None` for bare/`.vN`/unknown names; it is not
deleted wholesale). B removed the matching B-owned stream/adoption/supersession/rowless
tests and their four audit-allowlist entries (`register_legacy`, `_classify_rowless`,
`_family_versions`, `_next_artifact_ref`), and the post-deletion orphan check confirmed no
residual executable hit anywhere in the retained non-test tree. The stream/head registry
row contract (`STREAM_REGISTRY_COLUMNS`/`HEAD_STREAM_REGISTRY_COLUMNS`, `STREAM_TABLE`/
`HEAD_STREAM_TABLE`, `row_tuple`/`from_row`) and `pending`/`ready`/`missing`/`corrupt`
statuses are explicitly retained as rebuildable cache/index metadata until Plan C migrates
catalog-side consumers and Plan E completes CLI/schema/final registry cleanup; they are not
part of B's deletion surface.

### Already removed in Plan A (no inventory needed)
`[archival_ctp]`, `[optimization]`, `[pooling.*]`, `[similarity]`, `[stratify]`,
`[binning]` config sections; `std_scaled`/calibration/p50 threshold semantics;
scaled-config opt-in in `resolve_threshold`; `canonical_semantics`,
`canonical_calibration_record`, `canonical_alias`, `canonical_threshold(_of)`
threshold helpers; permissive warn-and-default `{}` loader behavior.
