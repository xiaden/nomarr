# Embedding Research Findings

Ongoing notes from research runs. Add findings as they emerge — don't wait for a "final" result.

> **Current-state note (Plan A corrective pass)**: entries below that discuss `std_scaled`,
> calibration/p50 scaling, or the old permissive config sections are HISTORICAL. The threshold
> contract is now a single finite direct L2 between normalized unit vectors (`configured ==
> effective`) in `helpers/thresholds.py`, and `helpers/toml.py` is a strict loader that rejects any
> scaled/calibration/optimizer/weighted/pooling config. The code does not read these historical
> notes at runtime.

---

## Open Questions / Deferred Experiments

### Distance metric for STD-threshold binning: cosine vs L2

- **Status**: Deferred
- **Context**: Calibration and `temporal_segment` currently use L2 distance (`global_dist`) and per-dimension Chebyshev distance (`perdim_dist`) as threshold metrics. These operate in unit-normed patch space.
- **Question**: Would cosine distance as the segment-boundary metric produce meaningfully different bin boundaries than L2 on unit vectors? (On unit vectors L2 and cosine are monotonically related, but Chebyshev/perdim is not — so the perdim mode is the more interesting case to test.)
- **Why deferred**: Don't want to add another combinatorial dimension mid-sweep. Revisit once the full 2547-song run is interpreted.

---

## Frozen observation-stream and segmentation-catalog decision (2026-09)

- **Status**: Approved design / implementation planning complete; no empirical corpus claim.
- **Scope**: Research tooling only: `scripts/embedding_research`, its tests/docs, and formal planning artifacts. The deferred production quantized-stream design and all `nomarr/`/`frontend/` paths are excluded.
- **Architecture**: A′ immutable float32 NumPy patch/head sidecars behind `StreamStore`, with DuckDB scalar registries and segmentation catalog. Sidecar paths are opaque artifact references, never identities. No Parquet, DuckDB BLOB, tar/Zarr, ANN v1, DuckDB 2.x transition, or new registry/catalog PK/UNIQUE constraints.
- **Threshold semantics**: The documented unit-vector direct L2 helper is authoritative for the new default: `threshold_effective == threshold_configured` under `direct_l2`. The old `std_thresh * p50` behavior is retained only as explicit `std_scaled` legacy compatibility, with both configured/effective values and calibration record persisted. Golden tests have separate legacy-fidelity and new-default tracks; hashes are exact while float matrices use documented tolerances.
- **Frozen lifecycle**: `embed` publishes immutable streams with staged write, file fsync, close, atomic rename, directory fsync, pending registry row, and reconcile to ready/missing/corrupt. `infer-heads` publishes complete patch-aligned head streams once. Legacy pre-registry sidecars are marked `legacy` with assumptions or re-embedded; they are never silently provenance-complete.
- **Catalog**: `seg_config`, `seg_meta`, and authoritative `seg_membership` replace threshold-specific copied vectors. Membership includes absorbed outliers; ranges are metadata only; segment/global medoids are observed source patch indices with deterministic smallest-index ties. All thresholds are evaluated in one stream load/pass. `catalog_fingerprint` is manifest-only and non-self-referential; search views carry no durable `search_view_hash` (removed under Plan D P1-S2) — identity is per-run disposable keyset/content; threshold aliases and structural changes are reported transiently. Planning arithmetic is approximately `10k × 100 × 10 ~= 10M` catalog rows, not an empirical result.

  > **Superseded (corrective-pass C — compact catalog):** the per-patch `seg_membership`
  > membership described above (a durable row per source patch incl. absorbed outliers) was
  > replaced by the compact durable catalog. It stores only structural `seg_meta` rows —
  > `[start_idx, end_idx)` ranges plus canonical sparse `absorbed_indices` — and exact
  > searchable membership is reconstructed on read from those rows against each song's
  > `audio_masks` searchable indicator (`[start, end) − absorbed − mask-silent`); no per-patch
  > membership is stored (P1-S12). The historical prose above is retained for traceability.
- **Analysis**: Each run regenerates disposable keyset/content-addressed medoid views (always re-gathered, never file-presence-reused; no `search_view_hash`). Catalog-first analysis uses bounded exact CPU scoring and streamed metrics; normal runs retain no N×N trace. Old flat/PTC/head/CTP caches are archival read-only compatibility paths owned by Plan E, not primary inputs.
- **Heads and CTP**: Head analysis pools frozen head streams over exact shared EffNet PTC membership and uses class-1 `act[1]`. Inclusive ranges cannot reintroduce absorbed outliers. CTP is phase-gated and disabled by default; a default run produces zero CTP work/rows and empty CTP tables are correct.
- **Cleanup and boundaries**: Active/archival/dead classification is explicit; resets are scoped (`staging`, `views`, `dead`, `archival`, `analysis-run RUN_ID`); Tier 1/2 results are protected. Only ingest/embed/infer-heads may access audio/models/ONNX/CUDA. Derived phases are CPU-only and portable. Post-crash `--verify` uses rollback-only canaries and requires EXPORT/IMPORT repair on failure.
- **Evidence limitation**: No current model/audio corpus run was available for this planning baseline. Fixture reports must be labeled synthetic. Any measured benchmark must state songs, patch distribution, dimension, backbone/model hash, hardware, software, peak RSS, elapsed time, and chunk budget.

> **Superseded (Plan E P1-S5 hard cut — the CTP / cache / reset-scope claims above):** bullets in
> this frozen-decision entry that describe CTP as phase-gated/disabled, flat/PTC/head/CTP caches as
> archival read-only compatibility paths, and the `dead`/`archival`/`analysis-run` reset scopes
> reflect the pre-hard-cut design. CTP and the legacy caches were DELETED outright (non-runnable,
> non-configurable) in the Plan E P1-S5 hard cut; `reset` is now `--scope analysis` only and
> `cleanup` accepts `staging`|`stray`|`views`; the shared-PTC boundary label was renamed
> `catalog`/`shared_catalog_boundary`. Retained for traceability.

## Completed Experiments

> **Historical research record (Plan E P1-S5 hard cut):** the experiment logs below predate the
> corrective pass and describe the retired research architecture — decile/bin metrics, the flat
> `global_pool` medoid baseline (`global_pool:{backbone}:medoid`), PTC/bin/truncation
> representations, the matching-corpus manifest (`corpus.py`) and matrix caches, and the Part D
> winner/factor grid. The flat/global-pool strategy, PTC/bin/truncation reps, CTP, `cache/*`,
> `corpus.py`, and their weight semantics were DELETED in the Plan E P1-S5 hard cut. These entries
> are retained only as a dated research record and are NOT current architecture.

### Amplitude-norm gating is harmful to disc scores — removed

- **Status**: Concluded (2026-05-25)
- **What was tested**: `amp_threshold_frac` controls an *amplitude-deviation boundary gate* inside `temporal_segment`. When `amp_frac > 0`, a segment boundary is also triggered if `|patch_norm − bin_amp_mean| > amp_frac × BACKBONE_NORM_IQR[backbone]`, independently of the cosine-distance check.
- **Config swept**: `amp_threshold_frac` ∈ {0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60} across effnet and musicnn.
- **Critical control**: `amp_frac = 0.0` (amplitude gate disabled; distance-only segmentation still runs).
- **Result — effnet**:
  - `amp = 0.0` (distance-only): `disc_general = 0.202` at `dist_thresh = 1.25`
  - `amp ∈ [0.25, 0.42]` (all amplitude-gated variants): `disc_general = 0.140 – 0.155`
  - Amplitude gating **reduced** effnet disc_general by **~25–30%** relative to distance-only.
- **Interpretation**: Embedding norm magnitude (raw vector energy before L2 normalisation) does not track musically meaningful transitions. Norm amplitude varies with signal energy / loudness, not with semantic content. Spurious amplitude-triggered splits fragment coherent segments into smaller bins and dilute the pooled embedding, degrading within-group similarity and collapsing the discriminability gap.
- **Decision**: Amplitude-based segmentation gating has been **permanently removed** from the codebase. `temporal_segment` and `temporal_segment_with_diagnostics` now respond only to cosine/L2 distance from the running segment centroid.
- **Related removal**: `AMP_THRESHOLD_FRAC`, `BACKBONE_NORM_IQR`, `resolve_amp_threshold()`, `amp_fracs_by_backbone_mode`, `opt_amp_candidates`, `_write_amp_sweep_summary()` all deleted.

---

### Noise metric removed: bin_div_std

**Status**: Concluded (2026-05-25)

`bin_div_std` measures the mean pairwise cosine distance between bin mean vectors for a given (song, backbone, bin_mode, std_thresh). High values confirm the threshold creates geometrically diverse windows but do not confirm semantic meaningfulness — any segmentation scheme that creates geometrically spread windows (including random) achieves equally high values. The metric provides no semantic quality signal and was removed from `binned_song_stats` and all DB writes.

### Explicit flat global-medoid baseline established

- **Status**: Established (2026-08)
- **What**: The flat (global-pool) pipeline now has an explicit **observed-patch global medoid**
  baseline for EffNet (`global_pool:effnet:medoid`) and an independent one for MusicNN
  (`global_pool:musicnn:medoid`). `pool_medoid` row-L2-normalizes the raw patches for cosine
  centrality, chooses the observed row with maximum mean cosine centrality, breaks ties to the
  smallest index, and returns the raw float32 patch — never a synthetic centroid.
- **Key distinction**: `rep_type="medoid"` (an observed per-bin segment representation) is
  allowed; `agg_method="medoid"` (aggregation-level) is intentionally rejected. The flat medoid
  is a *strategy* under `global_pool:{backbone}:medoid`, distinct from the per-bin binned medoid
  and from coordinate-wise `median`.
- **Cache identity**: each backbone's medoid is independently keyed at
  `cache/{backbone}/medoid/flat/{sid}.npy`; the two backbones are never cross-averaged.

### Matching-corpus manifest and versioned matrix-cache identity

- **Status**: Established (Plan C, 2026-09); intersection narrowed by the follow-on (Plans A–C)
- **What**: Every analyzed backbone now resolves a single deterministic
  **matching-corpus manifest** (`corpus.py`) — the canonically-sorted intersection of
  song IDs present in *every* required dataset. In the follow-on primary experiment this
  intersection is `flat:medoid` plus every selected PTC `(bin_mode, threshold, rep_type=medoid,
  score_variant)` sidecar; CTP is included only when the `[archival_ctp]` deferred/archival
  switch is explicitly enabled. All
  flat and binned configurations for a backbone compare that exact song set, so no
  reportable flat/binned row is emitted from unequal corpora. A loader returning a
  different set *or order* than the manifest is rejected by
  `validate_matching_corpus` and the config is skipped with a recorded `skip_reasons`
  entry — never silently intersected or reordered.
- **Cache identity**: representation-pair matrix caches are keyed on
  `matrix_cache_identity`, which embeds the scoring-semantics version
  (`SCORING_SEMANTICS_VERSION = 1`) **and** the matching-corpus hash alongside
  backbone/config/rep/metric. `versioned_cache_root` resolves `base/v{version}/{corpus_hash}`,
  so a stale corpus or a scoring-version change selects a different (orphaned) root: the
  old root stays on disk but is never read. Identical rep names over different arrays
  (different `corpus_hash`) therefore never collide.
- **Dead-path removal**: the write-only `sim_pairs` cache and the zero-caller
  `cache/sim.py` were removed; per-bin similarity matrices are composed in memory by
  `compute_agg_mats` and never cached to disk. `run.py` dropped the `--reset-sim-cache`
  flag and `sim_cache` reset directory.

### Winner/delta/factor benchmark grid (Part D)

- **Status**: Established (Plan D, 2026-09)
- **What**: The report now surfaces an auditable per-`(backbone, retrieval-group, metric-family, K)`
  benchmark grid instead of averaged composites. `_winners.py` enumerates every grid cell
  (`build_comparison_grid`), selects the deterministic winner per cell (`select_winner`, value ties
  broken by `TIE_BREAK_ORDER`), and emits one row per cell (`build_winner_delta_rows`) carrying the
  winner's decoded configuration, the explicit medoid baseline value, and `delta = winner - baseline`.
  `build_factor_summary` then groups wins/deltas per configuration factor (strategy type, flat
  strategy, pathway, head, bin mode, threshold, rep_a, rep_b, score_variant, ambiguity_variant,
  similarity metric) while retaining group x metric x K and the contributing strategy keys.
- **Schemas**: `WINNER_DELTA_COLUMNS` (33 cols) and `FACTOR_SUMMARY_COLUMNS` (10 cols) — see
  CONTRACTS.md §6. `section_winners` renders a `winner_delta_{backbone}` table and a
  `factor_summary_{backbone}` table per backbone.
- **Baseline policy**: each cell's baseline is exactly `global_pool:{backbone}:medoid` for the same
  backbone and K — never a max/median/mean across flat strategies and never a cross-backbone
  aggregate. The baseline reference is excluded from winner candidacy, so `delta` is negative when
  every configuration is worse than the medoid reference, zero on a tie, positive only when a
  configuration beats it.
- **No averaging**: no dimension (group, metric family, K, backbone, or hidden config) is averaged.
  `general` cells are gated by `_general_cell_valid` (general metric populated and, for MAP, >=2 of
  the per-group MAP components populated).
- **Corpus identity**: each winner row carries the matching-corpus `corpus_hash` and `corpus_size`
  when a per-backbone `MatchingCorpusManifest` is supplied.

### Noise metric removed: bin_flat_dist

**Status**: Concluded (2026-05-25)

`bin_flat_dist` is the maximum cosine distance of any bin from the flat pooled vector. A large deviation is equally consistent with musical signal (bins capture musically distinct segments) and segmentation noise (bins are artifacts of threshold choice). Without a ground-truth label anchoring the deviation magnitude, the value is uninterpretable. Removed from `binned_song_stats` and all DB writes.

## Architectural Notes

- Calibration (`_calibrate.py`) measures the distribution of patch→centroid distances per backbone and bin-mode. These stats inform STD-threshold selection but are not the similarity metric used for retrieval — retrieval uses cosine.
- `DIST_FNS` in `helpers/binning.py` maps bin-mode names to distance callables. Currently `temporal_global` → L2, `temporal_perdim` → Chebyshev.

## Final Semantics

> **[SUPERSEDED — Plan E P1-S5/P1-S6 (2026-09-05)]** This "Final Semantics" block predates the
> Plan E corrective-pass hard cut and several surfaces it describes as live were DELETED or
> renamed in that pass, so its "this section wins" authority no longer holds.  Surfaces marked
> **[historical — Plan E]** below are retired and described for traceability only; for the current
> live semantics see README.md (Writers / APIs, segmentation, catalog) and the module CONTRACTS.md.

- **[historical — Plan E P1-S5] Flat baseline — observed global medoid, not coordinate median.**
  The retired `global_pool` strategy defined the old benchmark baseline
  `global_pool:{backbone}:medoid`: `pool_medoid` row-L2-normalized the raw patches for cosine
  centrality, picked the observed row with maximum mean cosine centrality (ties → smallest index;
  zero-norm rows excluded; single patch → `(0, 0.0)`), and returned that raw float32 patch — never a
  synthetic/coordinate centroid.  The coordinate-wise synthetic `median` was a *different* strategy
  and not the baseline.  `rep_type="medoid"` was allowed; `agg_method="medoid"` was rejected.  (The
  `global_pool` strategy package was deleted in Plan E P1-S5; the current baseline is the
  deterministic catalog baseline — never a synthesized flat medoid.)
- **[historical — Plan E P1-S5] Separate EffNet / MusicNN populations.** Each backbone formerly
  resolved its own medoid, its own matching-corpus manifest, and its own report rows; the two
  backbones were never cross-averaged. The per-backbone matching-corpus manifest machinery
  (`corpus.py`, `MatchingCorpusManifest`) was deleted in Plan E P1-S5 (see the deletion inventory);
  corpus identity is now catalog-first.
- **Unit-vector temporal segmentation.** Segmentation operates on unit-normed patch vectors
  (`raw_all.normalize()`), thresholded by distance from the running segment centroid —
  `temporal_global` → L2, `temporal_perdim` → per-dimension Chebyshev. Amplitude gating was removed
  (2026-05-25); segmentation responds only to distance. Each song's patches are segmented
  independently; the number of segments per song varies with the patch stream.
- **[historical — Plan E P1-S5] Patch-count weights / weighted reductions.** The three legacy
  weighted reductions (`target_weighted`, `normalized_mean_pair_weighted`, `bidirectional_weighted`)
  treated weights as positive temporal patch-count weights — one weight per source bin (row) or
  target bin (column), equal to that bin's patch count — with exact float64 formulas and the
  directional/symmetric conditions (the reverse matrix was always supplied separately, never derived
  by transposing the forward matrix; validation rejected non-2-D inputs, length-mismatched weights,
  and zero-total-weight inputs). All three reductions — and their `strategy_binned/_weighted.py` and
  `tests/test_weighted_scoring.py` homes — were DELETED in Plan E P1-S5; none exists today (see the
  deletion inventory for the per-row EXECUTED dispositions).
- **[historical — Plan E P1-S5] Matching-corpus policy.** The retired `corpus.py` module enforced
  a matching-corpus policy: for each backbone, flat and binned configurations compared the exact
  same song set — the canonically-sorted intersection present in every required dataset
  (`MatchingCorpusManifest`); a loader returning a different set/order was rejected
  (`validate_matching_corpus`) and the config was skipped with a recorded reason — never silently
  intersected or reordered.  `corpus.py` (and its manifest machinery) was deleted in Plan E P1-S5;
  corpus identity is now catalog-first (Plan D/E `catalog_identity`).
- **[historical — Plan E P1-S5] Explicit baseline policy.** The explicit `global_pool:{backbone}:medoid`
  baseline was DELETED in Plan E P1-S5 along with the `global_pool` strategy. Delta/winner/headline
  claims are now measured against the deterministic catalog baseline — the lowest
  `(canonical_config_id, strategy_key)` active catalog class per `(backbone, sim_metric, k, metric)`.
  There is still no `dominance_rate`, composite-tuning-sensitivity, max/median/mean-across-flat
  fallback, or `flat_median_disc` metric.
- **[historical — Plan E P1-S5] Cache invalidation / versioning.** The similarity-matrix cache
  (`cache/sim.py`) was removed earlier; per-bin similarity matrices are composed in memory.  The
  representation-pair matrix caches keyed by `matrix_cache_identity` (scoring-semantics version
  `SCORING_SEMANTICS_VERSION = 1`, backbone, config, rep, metric, ordered song_ids, corpus hash)
  and resolved by `versioned_cache_root` (`base/v{version}/{corpus_hash}`) belonged to the deleted
  `cache_identity.py` cache layer, which Plan E P1-S5 removed — no on-disk analysis cache remains.
  (`SCORING_SEMANTICS_VERSION = 1` is still the live scoring-semantics version, now owned by
  `common/head_analysis.py`.)
- **Shared-boundary head pooling.** The `head-analysis` phase pools classifier head outputs over the
  shared compact-catalog boundaries only — `boundary_source="catalog"` and
  `head_pool_variant="shared_catalog_boundary"` (the older `effnet_ptc` / `shared_effnet_ptc_boundary`
  labels were renamed in the corrective pass) — never head-specific segmentation, never the CTP
  score-stream segmenter, never CTP cache paths. It is non-blocking and additive: provenance rows land
  only in `head_phase_provenance` and never mutate primary rows, the corpus, or the winner grid.

### Follow-on narrowed primary experiment (Plans A–C) — supersedes broad A–E claims

- **Supersedes** the broad A–E default grid (multiple default backbones, all flat strategies,
  cross-product representations, weighted reductions as final formulas, and CTP as a primary
  pathway) and its fixture numbers. Where this subsection conflicts with older notes or fixture
  values, this subsection wins.
- **Removed dimensions** (from default primary analysis): default backbones other than EffNet
  (MusicNN is now explicit opt-in only, via `backbones=["effnet","musicnn"]`); flat strategies
  other than `medoid`; PTC representations other than `medoid`; weighted reductions as
  authoritative formulas (briefly labeled `legacy_weighted_hypothesis` comparisons before their
  P1-S5 deletion); CTP as a primary pathway (deferred/archival, then deleted in P1-S5).
- **[historical — Plan E P1-S5] Exact per-threshold configurations** (each reported separately,
  never collapsed): bin modes `["temporal_global", "temporal_perdim"]`; distance thresholds `[0.95,
  1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5]`; `rep_type="medoid"`; primary score
  variant `max_per_candidate_segment`; comparison was measured against the then-observed
  `global_pool:effnet:medoid` baseline (that baseline no longer exists — deleted in Plan E P1-S5);
  similarity cosine on unit vectors.
- **Exact score hypotheses and ambiguity policies**: primary =
  `first_index + retain_all_candidate_segments` (one contribution per candidate segment,
  collisions visible, denominator = all candidate weights); documented alternative =
  `equal_tie_split + unique_source_max` (tied source maxima split credit, colliders dropped but
   kept in the trace, denominator shrinks to retained weights).  The three legacy weighted
   reductions (`target_weighted`, `bidirectional_weighted`, `normalized_mean_pair_weighted`) were
   implemented and numerically tested but labeled `legacy_weighted_hypothesis` — never authoritative
   primary semantics; their `strategy_binned/_weighted.py` home was deleted in Plan E P1-S5, so these
   reductions no longer exist.
- **[historical — Plan E P1-S5] CTP isolation**: the CTP source, caches, and archival loaders are no
  longer "available but disabled" — the whole CTP legacy surface (`strategy_ctp/`, the
  `[archival_ctp]` switch, CTP caches/tables, and the archival loaders) was DELETED in Plan E P1-S5.
  CTP rows/winners never enter the primary report grid because no CTP surface exists.
- **Corpus construction and hashes**: the retired primary corpus was the stratified candidate
  universe intersected with `flat:medoid` and every selected PTC `(bin_mode, threshold,
  rep_type=medoid, score_variant)` sidecar, canonically sorted and hashed with backbone, membership,
  eligibility dimensions, scoring-semantics version, and boundary configuration.  The stratified
  universe and `corpus.py` were removed in Plan E P1-S5; corpus selection is now the cataloged
  compact-snapshot corpus.  The completed A–E repair
  recorded fixture hashes (effnet `3012791ebac8655c`, musicnn `f93bd6f21eee1e99`, size 5); the
  follow-on regenerated fixture report (Phase 2/3) re-derives corpus identity — those numbers are
  superseded here, not re-pinned in this docs phase.
- **[historical — Plan E P1-S5] Phase 2 regeneration**: as recorded in the dated Plan A–C
  planning note, the narrow fixture report was regenerated and its matching-corpus manifests
  re-derived; the corpus manifest machinery and CTP — including the opt-in `--include-musicnn-ctp`
  flag — were deleted in the Plan E P1-S5 hard cut, so this record is superseded. The EffNet corpus
  hash came out **`3012791ebac8655c`** (size 5) — identical to the previously recorded value,
  confirming the matching-corpus hash is deterministic across the narrow regeneration. The MusicNN
  corpus hash (`f93bd6f21eee1e99`, size 5) was only computed under the then-explicit opt-in
  (`--include-musicnn-ctp`) and was unchanged. The validator passed against the regenerated report
  (exit 0).
- **Synthetic vs real**: fixture report values are deterministic synthetic in-memory data (no
  ONNX models / audio available) and must not be read as measured corpus conclusions; measured
  conclusions require a real embed/segment/classify/analyze run.

---

## Head-analysis corrective pass (2026-09-05) — P1-S1 / P1-S2

The corrective pass canonicalized CPU head analysis and made head-phase provenance canonical-only.

- The canonical CPU runner is now `common.head_analysis.run_shared_catalog_head_analysis(catalog,
  head_store, *, config_ids, song_ids, heads, run_id) -> HeadAnalysisManifest` — it accepts a
  compact `CatalogHandle` (or an object exposing `.con`) rather than a bare connection, reconstructs
  exact searchable `M_g` membership from COMPACT structural `seg_meta` (minus `absorbed_indices`, no
  mask seam, no `seg_membership`) and gathers source-index rows once per song via
  `HeadStreamStore.batch_gather`. Pooled head values are the class-1 `act[1]` channel and stay
  transient. The old public `pool_head_outputs_over_ptc_boundaries`, `HeadBoundaryPoolResult`, and
  `run_shared_ptc_head_pooling` (common/head_analysis) were removed; the executable `std_scaled`
  semantics predicate was dropped (head semantics is `direct_l2`-only).
- `db/head_phase.py` is canonical-only: legacy statuses/readers (`query_head_phase_done`,
  `append_head_phase_archival_rows`, `build_archival_provenance_rows`, `is_canonical_row`,
  `load_head_phase_provenance_all`) and the `run_id='legacy'` concept were deleted, along with the
  13-col->18-col `migrate_head_phase_provenance` (backup-first) migration. `run_id` is an
  integer-ms CLI-supplied identity; the `threshold` column is NULL-for-canonical only. `run.py`'s
  head-analysis phase now calls `run_shared_catalog_head_analysis`; the legacy `_head_phase`
  archival glue was removed (its archival sinks are gone). `classify.py`/`head_pooling.py` LEGACY
  interim surfaces are untouched here and remain until their separate retirement (both were later
   deleted outright in the Plan E P1-S5 hard cut recorded below).

## Final Verification Note (Plan E — report inspection & quality gate)

> **SUPERSEDED by the follow-on (Plans A–C).** This note describes the OLD broad A–E fixture
> report (16 sections, dual EffNet+MusicNN defaults, old corpus hashes, old disc values, and the
> unified_disc_bar quirk). The follow-on narrows the primary experiment and regenerates the
> fixture report/validator in Phase 2/3. Treat every fixture number/hash here as superseded; the
> contract-level follow-on statements (narrow primary, per-threshold configs, hypotheses, CTP
> isolation, corpus algorithm, head phase) are recorded in the "Follow-on narrowed primary
> experiment" subsection above. Do not re-pin the old fixture values here.

This section records the evidence from the final verification gate (Plan E), including the
inspection of the generated fixture report and the unresolved limitations that remain. It is a
research-verification note, not a claim that production behavior changed.

### Generated fixture report — inspection evidence

- **Corpus size / hashes.** The deterministic fixture corpus is **5 songs / 3 artists / 3 albums**.
  Per-backbone corpus hashes (matching-corpus manifests): **effnet = `3012791ebac8655c`**, **musicnn =
  `f93bd6f21eee1e99`**, size **5** for both. These hashes match across all compared rows in the
  generated report.
- **Backbone separation.** EffNet and MusicNN are visibly separate: every corpus-bearing section
  (winners, per-backbone, threshold-sweep, bin-mode-comparison, flat-binned-corr, summary) carries
  per-backbone subsections/rows (`winners-effnet`/`winners-musicnn`, `backbone-effnet`/`backbone-musicnn`,
  etc.). Each backbone resolves its own `global_pool:{backbone}:medoid` baseline; the two are never
  cross-averaged. Summary: effnet medoid disc_genre 0.5155 → best binned 0.5705 (+0.0550); musicnn
  0.5596 → 0.6146 (+0.0550).
- **Exact K values evaluated.** {5, 10} — every winner-delta cell is per `group × metric × K`; the
  winner_delta table (33 columns) enumerates 34 winner cells per backbone and the factor_summary
  table (10 columns) 374 factor rows per backbone.
- **Explicit medoid baseline.** `baseline_strategy_key == global_pool:{backbone}:medoid` on all 34
  winner rows per backbone; summary exposes `flat_medoid_disc_genre`; winners description names the
  medoid explicitly.
- **Mechanical + manual inspection.** `validate_fixture_report.py` confirmed schema_version 2, all 16
  sections carrying the full v2 key set, all expected group×metric×K winner cells, per-backbone medoid
  baselines, consistent corpus hashes, and no `disc_album` / no hidden `config="flat"`. Manual reading
  of report.json (section-by-section) confirmed readable config identity, correct directional-aggregate
  and temporal-weight wording, ties/nulls/warnings rendered understandably (null identity → "—",
  tie-break key readable), and no chart/table silently mixing corpora.
- **JSON/HTML hygiene.** report.json round-trips via `json.load` (schema_version 2, 16 sections) and
  contains **zero** NaN/Infinity/-Infinity literals. The report.html viewer escapes all DB-derived text
  via `esc()` (`& < > "`) and uses `textContent` for titles/status.

### Medoid numerical tie-break behavior (observed patch)

- **Smallest-index first-max.** The flat medoid picks the observed raw patch with maximum mean cosine
  centrality; ties resolve to the **smallest index** (zero-norm rows excluded; a single-patch song
  yields `(0, 0.0)`). This is the observed patch, never a synthetic/coordinate centroid.

### Unresolved limitations

- **Fixture vs real pipeline.** The inspected report is a **deterministic in-memory fixture** — no
  ONNX models (`/app/models` absent), no audio (`test-media` has 0 files), and the pre-existing research
  DB is stale for the current contract (lacks medoid-baseline and weighted rows, non-matching
  per-backbone corpora). The fixture drives the *real* `report.run()` + all 16 section builders, so the
  report structure/semantics are verified, but **no measured corpus conclusions are claimed**. A real
  end-to-end run requires the models/audio environment and remains a future step.
- **unified_disc_bar medoid-bar quirk (RESOLVED in QA fix cycle 1).** The unified flat-vs-binned
  discrimination bar chart previously rendered only the binned bars per backbone; the medoid baseline bar
  was absent because `flat_medoid_value` received the reindexed frame (`flat_df.reindex(...)` drops
  `strategy_key`, making `canonical_flat_baseline` yield no rows). Fixed in
  `report/_retrieval.py` `section_unified_table` by calling `flat_medoid_value(flat_df, ...)` on the
  **un-reindexed** flat frame (which retains `strategy_key` / `strategy_type`), then regenerating the
  fixture report. The mechanically re-validated report now renders all four bars: **effnet** medoid
  `0.5155` / binned `0.5705`; **musicnn** medoid `0.5596` / binned `0.6146`.
- **Pre-existing ruff findings.** `ruff check` reports 25 findings (ARG001/ARG002, PERF401, SIM115,
  RUF002) in the research tree; all are pre-existing in git HEAD of the changed files (verified against
  HEAD blobs) and none are introduced by this repair. `mypy` excludes `^scripts/` by config, so research
  scripts are not type-checked by design.

---

## Final-report checklist (follow-on — durable gate)

Before a follow-on report/findings entry is considered final, it MUST state each of the following
explicitly. Any item left unstated is a gap, not an acceptable omission. (This checklist is durable:
it stays in effect for every follow-on report, not just the current plan.)

- [ ] **Removed dimensions** — name every dimension removed from the default primary experiment
      (e.g. default backbones other than EffNet, flat strategies other than `medoid`, PTC
      representations other than `medoid`, weighted reductions as authoritative formulas, CTP as a
      primary pathway).
- [ ] **Threshold configurations** — list every configured bin mode and distance threshold as its
      own configuration (never collapsed by averaging), with `rep_type="medoid"` and the primary
      score variant named.
- [ ] **Score hypotheses and ambiguity policies** — name the primary `max_per_candidate_segment`
      variant and its tie/collision policy (`first_index + retain_all_candidate_segments`) and the
      documented alternative (`equal_tie_split + unique_source_max`). There are no weighted-reduction
      hypotheses to label: the three legacy weighted reductions were deleted in Plan E P1-S5 and must
      not appear under any `*_hypothesis` label.
- [ ] **CTP isolation** — state that CTP is fully DELETED (non-runnable and non-configurable, Plan E
      P1-S5): no `[archival_ctp]` switch exists and the strict `helpers/toml.py` loader rejects any
      such config section, so CTP rows/winners can never enter the primary report grid.
- [ ] **Corpus algorithm and hashes** — state the primary corpus construction (the full ingested
      song registry, or an explicit config-level selection, cataloged through the compact
      segmentation catalog), the corpus hash/size used, and that all compared configurations ran on
      the exact same song set (or a clearly declared derived subset).
- [ ] **Head phase** — state the shared catalog boundary (`boundary_source="catalog"`,
      `head_pool_variant="shared_catalog_boundary"`), that it is non-blocking/additive, and that it
      never alters primary rows, the corpus, or the winner grid.
- [ ] **Evaluation lenses** — state that MAP, MRR, NDCG, Recall, and discrimination are evaluation
      lenses, not optimization objectives, and are never collapsed into one composite.
- [ ] **Tests and gates** — list the tests/gates run (pytest suite incl. `-x` early exit, compileall,
      ruff format/check, fixture generation + validation, strict-JSON finite check, no `disc_album`
      check) and separate pre-existing findings from follow-on regressions.
- [ ] **Synthetic vs measured** — explicitly label fixture numbers as deterministic synthetic data
      when no real model/audio run is available, and separate them from any measured corpus
      conclusions.
- [ ] **No production diff** — assert that only `scripts/embedding_research` (code/tests/docs) and
      the approved planning artifacts changed, and that no file under `nomarr/` or `frontend/` was
      modified.

---

## Part A audit — active / archival / dead inventory (2026-09-02)

> **Plan E P1-S5 supersession note (2026-09-05)**: the `[ACTIVE]`/`[ARCHIVAL]`/`[DEAD]`
> dispositions below were assigned against the pre-hard-cut code on 2026-09-02. Many rows name
> surfaces since deleted in the Plan E P1-S5 hard cut — `classify.py`/`head_pooling.py`/`pooling.py`/
> `corpus.py`, the `strategy_*` modules, `cache/*`, and the `binned_calibration`/`binned_song_stats`/
> `stratified_corpus` tables. Those rows are NOT live inventory; treat their labels as historical
> (see the CONTRACTS deletion inventory and the README `[Historical — Plan E P1-S5]` rows for the
> landed state).

> **Plan-B delivery supersession note (2026-09-04)**:The two rows below marked
> **[ACTIVE primary writer]** / **[ACTIVE primary reader]** — `common/embed.py` `_embed_song`
> bare `np.save` sidecar write at `config.patches_path` and `common/segment.py`
> `np.load(sidecar)` reads — are SUPERSEDED by Plan B delivery.  The writer is now digest-only
> `store.publish` (stream) + `store.publish_observation_group` (patch-aligned mask + commit
> marker) per song, and retained readers (incl. `common/segment.py`) resolve current payloads
> through the `CurrentStreamResolver`/`make_current_stream_resolver` seam
> (`streams/store.py`), never by direct `np.load` of a sidecar path.  Those two rows are
> retained only as a historical audit record and are NOT live inventory.  See the README
> "Current-reader seam" entry and both CONTRACTS ledgers for the landed contract.

Cross-check of the DD static lists and the SKILL 2026-09-02 addendum against the live
`scripts/embedding_research` code (DuckDB written vs DDL'd-unwritten, FS cache layout). Dispositions:
**[ACTIVE]** = primary/current; **[ARCHIVAL]** = legacy read-only compatibility, never a primary input;
**[DEAD]** = zero live producer and zero/only-test consumer, a deletion candidate (Plan E owns removal —
nothing deleted in this audit).

### Threshold surfaces (PTC path)
- **helpers/binning.py `global_dist` (L70–76)** — **[ACTIVE primary default]**. Docstring is
  authoritative: *"IMPORTANT: For temporal_global, threshold is a direct unit-vector L2 distance (not a
  std multiplier)."* `perdim_dist` (L79) = per-dimension Chebyshev. These are the segmentation distance
  functions used today (dd. `direct_l2` default semantics: `threshold_effective == threshold_configured`).
- **strategy_ptc/segment_fn.py `make_segment_fn` (L112) / `segment_fn` (L131)** — **[ACTIVE PTC writer,
  ARCHIVAL-compat threshold semantics]** in one surface. Live behavior at L139–150: per `(bin_mode)`,
  `base_threshold` defaults `0.1`; if a cached calibration row's `mode_cal["p50"]` is finite and nonzero,
  `base_threshold = p50`; then `threshold = std_thresh * base_threshold` (L150) — the **std_scaled
  std_thresh × p50 multiplier path**. Because `_calibrate` (below) has zero live callers, no
  `binned_calibration` rows exist in a normal run, so `_load_cached_calibration` (L136) returns `None` and
  the *effective* threshold is currently `std_thresh × 0.1` — not a real p50 and not the direct-L2
  configured value. This is the exact R2 configured-vs-effective contradiction Phase 2 owns; **behavior
  unchanged here (capture only)**.
- **strategy_binned/_calibrate.py `_calibrate` (L38) → `upsert_calibration` (L85)** — **[DEAD writer]**
  zero production callers (computation of the p50 distribution is never invoked by the live pipeline);
  only the read side `_load_cached_calibration` is live (strategy_ptc/segment_fn.py:136).
- **strategy_binned/_optimize.py `_eval_threshold` (L157) / `optimize_std_threshold` (L418)** — **[ARCHIVAL /
  manual-only]**. Pure in-memory golden-section/grid search; treats `threshold = dist_thresh` as a direct
  cosine/Chebyshev distance value (not std_multiplier); writes no caches. Zero production callers (tests
  `tests/test_binned_process.py` only). `[optimization]` config block is not read by any production code —
  declarative/reserved, enforced by tests. Its stale synthetic `rep_type="median"` was repaired in this
  part (see P1-S3).

### Cache / persistence surfaces
- **common/embed.py `_embed_song`/sidecar write (L80)** — **[ACTIVE primary writer]** bare float32
  `_np.save(sidecar, embeddings.astype(np.float32))` at `config.patches_path` = `patches/{sid}.{bb}.npy`;
  deliberately kept out of DuckDB. This is the frozen immutable patch-stream producer seam (Plan B wraps it).
- **common/segment.py `segment` (L92 read)** — **[ACTIVE primary reader]** `np.load(str(sidecar),
  allow_pickle=False).astype(np.float32)`; drives `segment_fn` + `cache_write_fn` per strategy. This is
  where each FS cache writer is invoked per song.
- **cache/flat_vecs.py `save_pooled` (L49) / `load_matrix` (L138)** — **[ARCHIVAL].** flat pooled sidecars
  `cache/{bb}/{strategy}/flat/{sid}.npy` are superseded by frozen flat medoid head streams in Plan B; the
  legacy reader `load_matrix` is retained for read-only golden comparison. Writers: strategy_global_pool
  segment_fn/_embed. Readers today: run.py analyze, classify.run_flat.
- **cache/binned_ptc.py** (`save`, `load_bin_stats`, `load_norm_pair`, ...) — **[ARCHIVAL]** legacy
  threshold-specific copied PTC vectors (`cache/binned_ptc/{tag}/{bb}/{bin_mode}/{thresh}/{sid}.npz`
  incl. `pool_*_raw/norm`, medoid idx/centrality). Writer strategy_ptc/segment_fn; readers run.py analyze,
  classify, strategy_ptc. Read-only golden once segmentation catalog (Plan C) lands.
- **cache/binned_ptc_heads.py / cache/binned_ctp_heads.py** — **[ARCHIVAL]** head-phase pools; the
  `effnet_ptc` head phase (Plan A′ head phase) is ACTIVE/additive but reads via classify's
  `run_shared_ptc_head_pooling` over these boundaries. `cache/binned_ctp*.py` — **[ARCHIVAL/DEAD-leaning]**:
  CTP is disabled by default (`[archival_ctp] enabled=false`), so CTP caches only accrue under the explicit
  archival opt-in.
- **cache/flat_heads.py** — **[ACTIVE]** the current classifier head-output sidecar cache
  (`cache/{bb}/heads/...`); written by classify.run_flat/run_binned, read by analyze/stratify/head phase.
- **cache_identity.py `matrix_cache_identity` (L39) / `versioned_cache_root` (L105)** — **[DEAD functions]**
  zero production callers (tests only). `SCORING_SEMANTICS_VERSION = 1` (L36) is **[ACTIVE]** (imported by
  run.py, classify.py). `cache/sim.py` + `sim_pairs` were already removed (Plan C) — confirmed absent.
- **pooling.py `STRATEGIES` / `select_global_medoid_index` (L83)** — **[ACTIVE primary]** flat pooling now
  includes **medoid** (observed source patch, max-mean-cosine centrality, ties→smallest index). The old
  claim in the SKILL body that medoid is absent is stale; superseded by the 2026-09-02 addendum.
- **classify.py** (run_flat L629, run_binned L754) — **[ACTIVE]** head inference; touches audio
  (discover_audio) — the hard inference boundary Plan A′/R5 formalizes (only ingest/embed/infer-heads may
  touch audio/ONNX/CUDA).
- **head_pooling.py + db/head_phase.py + report/_heads.py** — **[ACTIVE additive]** shared-boundary head
  phase; writes only `head_phase_provenance` (additive provenance), never mutates primary rows.

### DuckDB — written vs DDL'd-unwritten (db/_schema.py + per-repo writers)
- **[ACTIVE written]** `songs`, `analyze_metrics` (+`trace_*` scalars), `song_retrieval_metrics`,
  `stratified_corpus`, `phase_timings`, `head_phase_provenance`.
- **[DEAD — DDL'd, no live writer]** `pooled_vecs`, `head_results` (upsert_head 0 callers), `head_agreement_rows`,
  `patch_features`, `binned_pair_sims`, `binned_classify_ctp`, `truncation_robustness_rows`, `binned_ctp_vecs`,
  `binned_ptc_ctp_metrics`, `head_sim_corr_rows` (upsert fns exist, zero production callers).
- **[ACTIVE writer, semantics to migrate]** `binned_calibration` + `binned_song_stats` (writers
  `_calibrate`/`_process._compute_song_stats` live in the calibrate/optimize code path but the calibrate
  producer is unreachable today — see above). `analyze_metrics` global `DELETE` at run.py:675 is the R11
  run-scoping hazard Phase 2/Plan D replaces (run-scoped, backup-first). Matches DD/SKILL addendum lists
  exactly; no DDL'd-but-unwritten discrepancy beyond the classification above.
- **Report read surfaces** (`report/_*.py`) read DuckDB scalars (`analyze_metrics`,
  `song_retrieval_metrics`, `head_phase_provenance`), matching-corpus manifests, and optimizer CSV curves —
  no direct FS cache imports. **[ACTIVE]**.

### Direct-L2 helper vs std_scaled path (cross-check)
The live PTC writer computes `std_thresh × base_threshold` (segment_fn.py:150) where `base_threshold`
defaults `0.1` and equals `p50` only when a (never-produced) calibration row exists. Meanwhile the
segmentation distance contract (helpers/binning.py:70–76) and the config's `[binning]` comment both
describe thresholds as **direct unit-vector L2 distances**. These two coexist today because the live
`std_scaled` path's calibration table is empty in practice. This is the primary evidence for Phase 2's
`direct_l2` default (`threshold_effective == threshold_configured`) with `std_scaled` retained as explicit
legacy compatibility. No behavior changed in this audit.

### Live PTC "median" vs observed medoid (P1-S3 context)
- Flat `pooling.py` medoid = observed row (max-mean-cosine). Per-bin binned medoid
  `strategy_binned/_constants.py _BIN_POOL_STRATEGIES["medoid"]` = observed patch closest to the segment
  centroid; per-bin `"median"` = **synthetic coordinate-wise** `np.median` (`selected_global_idx=None`).
- `_pool_segment` (`strategy_binned/_pool.py`) emits payloads only for `_BIN_POOL_STRATEGIES ∩ REP_TYPES`;
  under the shipped default `pooling.rep_types = ["medoid"]` only the observed medoid is emitted — the
  synthetic `median` rep is absent from the default pool surface.
- `_constants.validate_optimizer_representation` (new, this part) rejects the stale
  `[optimization.strategy].rep_type = "median"` synthetic optimizer rep; shipped config is now `"medoid"`.

---

## Part A legacy-fidelity reference capture (2026-09-02)

Reference behavior recorded BEFORE any threshold-default change (Phase 2), so golden legacy tests can pin
it. **No behavior changed; values marked "synthetic" are fixture data, not measured corpus results.**

### (1) Legacy PTC threshold = std_thresh × per-bin_mode p50 calibration
- Site: `strategy_ptc/segment_fn.py` `segment_fn` L139–150.
- Exact formula: for a `(bin_mode, std_thresh)` strategy,
  `effective_threshold = std_thresh × base_threshold`, where
  `base_threshold` = `mode_cal["p50"]` if a cached `binned_calibration` row for that backbone+bin_mode
  exists and that p50 is finite and nonzero, else `0.1` (L140, L145–146). The calibration row is read from
  DuckDB `binned_calibration` (table: `backbone, dist_mode, p10, p25, p50, p75, mean_d, sigma_d,
  n_patches`).
- Calibration value population: `strategy_binned/_calibrate.py _calibrate` measures the patch→centroid
  L2-distance distribution per (backbone, bin_mode) and upserts percentiles (p50 used here). This producer
  has **zero live callers** today, so in a normal pipeline no rows exist → `_load_cached_calibration`
  returns `None` → `base_threshold = 0.1` → effective threshold = `std_thresh × 0.1`. (This is precisely
  the R2 configured-vs-effective gap; Phase 2 resolves it.)
- Configured `dist_thresholds` (research_config.toml `[binning]`): `[0.95, 1.0, 1.05, 1.1, 1.15, 1.2,
  1.25, 1.3, 1.35, 1.4, 1.45, 1.5]` (with a live calibration p50, legacy effective thresholds would be
  these values × p50; with no calibration, ×0.1).
- Segmentation then calls `temporal_segment(norm_patches, threshold, DIST_FNS[bin_mode])`
  (segment_fn.py:151) over **unit-normed** patches (`UnitTensor(patches)`, L149). Observed dtype/shape:
  patch sidecars are bare float32 arrays (`common/embed.py:80`), shape `(n_patches, dim)`; unit-normed
  copy same shape float32. `temporal_segment` yields per-song segments; pooling/medoid payloads are
  float32 observed rows (see inventory). Synthetic fixture values only — no measured corpus calibration
  claimed.

### (2) Direct-L2 helper contract
- `helpers/binning.py global_dist` L70–76: `L2 = ||patch − centroid||` over **unit vectors**; docstring is
  the authoritative statement that `temporal_global` thresholds are **direct unit-vector L2 distance, not
  a std multiplier**. `perdim_dist` (L79) = per-dimension Chebyshev. This is the reference the new
  `direct_l2` default aligns to (`threshold_effective == threshold_configured`).

### (3) dtype / shape and documented rtol/atol policy
- FS sidecars and segment/pool vectors are float32. DuckDB `analyze_metrics` scalars and weighted
  reductions accumulate in float64 and return Python `float`. Golden comparison policy: **hashes exact**;
  **float matrices tolerance-bounded** (documented per-fixture rtol/atol, not bit-identity). No
  bit-identity claim is made for float arrays; identical-input cosine self-similarity yields exactly `1.0`
  only where the formula provably does (see Part B weighted tests). Max recorded float diffs are fixture
  tolerance claims, not measured corpus values.

### (4) Fixtures/tests that encode legacy behavior
- `tests/test_ptc_segment_fn.py`, `tests/test_temporal_segment.py`, `tests/test_binned_process.py`
  (calibration/optimizer thresholds), `tests/test_ctp_segment_fn.py`, `tests/test_segment.py`,
  `tests/test_binned_process.py` cache-identity tests. These pin the current std_scaled/segment semantics
  and must be separated into legacy-fidelity (golden) vs new-default (`direct_l2`) tracks in Phase 2/3;
  none change in this part. The fixture corpus is deterministic synthetic (5 songs / 3 artists / 3 albums);
  corpus hashes effnet `3012791ebac8655c`, musicnn `f93bd6f21eee1e99` (size 5) are recorded only for the
  synthetic fixture, not measured runs.

### Part A code/tests added in this part
- `research_config.toml`: `[optimization.strategy] rep_type = "median"` → `"medoid"` (observed source
  medoid, never synthetic median). `[archival_ctp] enabled=false`, `[optimization] enabled=false`, and the
  EffNet/observed-medoid/direct-L2/cosine primary defaults were already in place and are now test-pinned.
- `strategy_binned/_constants.py`: new `validate_optimizer_representation` (rejects stale synthetic
  `"median"`, unknown names) + module-level import guard reading the shipped `[optimization.strategy]`.
- `requirements.txt`: `duckdb>=0.10.0` → `duckdb>=1.5,<2.0`.
- `db/_schema.py`: new `require_supported_duckdb()` (library-version gate 1.5 ≤ v < 2.0, fails loudly),
  `_duckdb_version_tuple()`, and `storage_version_label()` (storage-format version is an opaque label, never
  numerically compared). Wired into `run.py main()` (covers every pipeline phase) and
  `generate_fixture_report.py main()`.
- New tests: `tests/test_duckdb_version_boundary.py` (10); `tests/test_binned_process.py` additions
  (optimizer-rep validator + observed-medoid/no-synthetic-median pool); `tests/test_toml.py` shipped-config
  `rep_type == "medoid"` assertion.

## Plan A implemented outcomes (Phases 1–2, 2026-09-02)

This section records what Plan A (threshold/contract baseline) actually shipped before any
stream/catalog implementation, so later plans and QA can reconstruct the decisions from
evidence. The per-file test/code additions are itemized in "Part A code/tests added" above; this
is the outcome summary.

### (1) Active / archival / dead inventory (P1-S1)
The full per-surface disposition with file:line evidence is in the "Part A audit" section above
(active primary vs archival read-only vs dead candidate). Contract-level summary is in
CONTRACTS.md §Plan A baseline. Nothing was deleted — removal is Plan E's decision. Key dead
candidates: the `binned_calibration` producer `_calibrate` (zero live callers, so calibration
rows never exist in a normal run), the tests-only `_optimize` search functions, and the
tests-only `matrix_cache_identity`/`versioned_cache_root` (with `SCORING_SEMANTICS_VERSION=1`
active). The DuckDB DDL'd-but-unwritten tables and the archival FS caches are enumerated there.

### (2) Captured legacy references (P1-S2)
Captured BEFORE any threshold-default change so golden legacy tests can pin it; full detail in
the "Part A legacy-fidelity reference capture" section above. Legacy effective threshold was
`std_thresh × base_threshold` (p50 when a calibration row existed, else the silent `0.1`
default) — precisely the R2 configured-vs-effective contradiction Phase 2 resolved. Tolerance
policy recorded: hashes exact; float matrices tolerance-bounded (documented rtol/atol), no bit
identity.

### (3) P2 threshold decision — direct_l2 default; std_scaled explicit-only
- New default for the PTC primary path is `direct_l2`: `threshold_effective ==
  threshold_configured` exactly, no multiplier, no DB calibration lookup, no `0.1` fallback.
  `std_scaled` remains only as an EXPLICIT legacy-fidelity track requiring a recorded
  calibration basis (`statistic` + finite positive `value`); effective = configured × basis is
  recorded, and requesting it without a basis raises loudly (`ValueError`) rather than silently
  scaling.
- Module home: `helpers/thresholds.py` (pure: no DuckDB/IO/audio). `strategy_ptc/segment_fn.py`
  `make_segment_fn(con, *, semantics="direct_l2", calibration_records=None)` routes thresholds
  through it; the running-centroid segmentation algorithm was preserved exactly (only
  threshold-application semantics changed). The strategy_ctp per-song score_std scaled path is
  ARCHIVAL and left untouched.
- Canonical identity/encoding: `canonical_float` = shortest round-trip repr, exponent expanded
  to fixed-point, `-0.0 → 0.0`; config hash is semantics-sensitive over a fixed field order
  (sha256). Canonical functions take NO path parameter — identity is pure content, never
  path-derived (R3/R9). Legacy on-disk cache-path encoders (`threshold_key`,
  `canonical_threshold`) are unchanged so archival/legacy cache readers keep resolving (no
  orphaned reads).

### (4) P1-S4 dependency / version boundary
- `duckdb>=0.10.0` → `duckdb>=1.5,<2.0`. `require_supported_duckdb()` gates the duckdb LIBRARY
  version to `1.5 ≤ v < 2.0` at every research CLI phase startup (fails loudly otherwise);
  `storage_version_label()` treats the storage-format version as an opaque LABEL, never parsed
  or numerically compared. The library gate and the storage label are distinct: a hypothetical
  2.x storage version passes as a label while a 2.x library is rejected. DuckDB 2.x is a
  separately approved follow-up.

### Tests / gates run at phase end
`python -m pytest scripts/embedding_research/tests/ -q` green (see report for final count);
ruff check + ruff format --check clean on changed files; compileall on changed Python files;
`git diff --stat` shows no `nomarr/` or `frontend/` path.

## P1-S4 — collapse-aware analyze scheduling (Plan D)

**Observation (uncertainty: none).** Delivered the AMENDED §D analyze scheduling in
`common/catalog_analysis.py`. Findings worth recording:

- **Collapse scope = whole backbone snapshot, projected to participants.** ``run_catalog_analysis``
  recomputes ``collapse_search_representations`` from the CURRENT compact rows every run (the S3
  single source of truth), then projects classes down to the participating configs. Only the
  lowest-``config_id`` canonical rows of each class enter the query/candidate union; aliases never
  trigger a second ``materialize_search_view`` or ``score_bounded_exact`` call. Confirmed on the
  real scheduler with a two-threshold fixture: configs collapse to one class and the alias config
  never appears in any candidate view fed to ``score_bounded_exact``.
- **``config_ids`` = ALL participating configs; ``representation_classes`` is transient.** The new
  DTO field carries each class's canonical id + sorted aliases and is NOT persisted — no durable
  alias table/column exists.
- **Lazy attach + typed refusal.** ``analyze_catalog_corpus`` accepts a handle, a snapshot
  connection, or a snapshot PATH string (opened read-only and closed in ``finally``). A missing /
  corrupt / non-compact catalog raises the typed ``CatalogRefusalError`` and fails CLOSED — no
  silent skip, no stale fallback. Test note: DuckDB's single-writer rule means a path-based lazy
  open of a snapshot the harness already holds read-write must wait until that handle is closed
  (the determinism test closes the harness handle before the read-only path open).
- **Run-scoped deletion only.** A re-run deletes/replaces only its own (run_id, scope) rows;
  retained provenance and other runs' ``analyze_metrics`` rows survive. No global DELETE anywhere
  in the analyze path.
- **Zero-searchable songs.** A metadata-only song (zero searchable medoids under every config) is
  excluded from queries and candidates automatically — ``materialize_search_view`` emits no rows
  for it and ``run_catalog_analysis`` filters ``cfg.song_ids`` to songs present in the canonical
  view rows. Verified with an all-zeros silence mask (mask semantics: 1=searchable).

## P1-S6 — similarity.py ANN surface deletion (exact-CPU-only)

Plan D P1-S6 deleted the ANN/FAISS surface from `similarity.py`, leaving the module exact-CPU
only. Deleted: the `ANNIndex` class, `ann_recall_sweep`, the optional FAISS backend (lazy
`import faiss` / `_FAISS` flag / numpy-fallback `warnings.warn`), the now-unused `RawVector`
and `warnings` imports, and the `faiss-cpu` research dependency in
`scripts/embedding_research/requirements.txt`. Retained intact (all had live callers at the time —
`strategy_binned/_process.py`, `common/analyze.py`, retrieval tests; both modules were later
deleted in the Plan E P1-S5 hard cut below): `cosine_matrix`,
`l2_normalise`, `METRICS`, `_rankings_from_sim`, `compute_retrieval_metrics`, `DISC_HEAD_*`,
and the sklearn NDCG helper.

Test census: **no retained test ever imported or executed the ANN symbols.** `test_similarity.py`
imports only exact-CPU functions (all synthetic retrieval/discrimination/within-cross tests) and
was RETAINED. `test_ann_seam_boundary.py` is a retained negative boundary test scanning the
exact-CPU modules for live ANN code and needs no similarity ANN symbol — retained. No ANN unit
tests existed to delete, so the full-suite count is unchanged (1143 passed / 1 skipped).

Negative-audit tightening (`test_audit_forbidden_vocabulary.py`): the `annindex`/`ann_recall_sweep`
allowlist entries (previously `{similarity.py}`) were REMOVED and `faiss`, `hnsw`, `_faiss` were
added to the forbidden-token set with zero allowlist entries — a whole-tree audit pass (7 tests)
now FAILS on any future executable ANN reference in a retained research file. Zero executable ANN
references remain in the retained non-test tree (remaining textual hits are module docstring /
CONTRACTS.md inventory / audit-token-scan definitions only, which the tokenizer excludes).

Verification census (all green on the D-derived surface — search_views.py, common/catalog_analysis.py,
bounded_scoring.py, scoring_harness.py, catalog_report.py): no legacy weighted reduction / rep_a / rep_b
executable vocabulary; no CTP call; no old-cache (`flat_vecs`/`flat_heads`/`binned_ptc*`/`binned_ctp*`/
`cache_identity`) call; no audio/model/ONNX/CUDA reference — the only remaining mentions of those
terms in the derived files are historical prose/comments, which the audit tokenizer excludes (audit
already enforces their executable absence since none is allowlisted for these files). E-owned files
(`run.py`, `common/analyze.py`, `strategy_*`, `cache/*`, `report/*`) retain their legacy vocab per
policy — residual-E, not touched here. (`common/analyze.py`, `strategy_*`, and `cache/*` were
subsequently deleted in the Plan E P1-S5 hard cut; `report/*` was re-migrated to the schema-v2
seven-section contract.)

## Plan E P1-S3 / P1-S4 — frozen-CLI hard cut + maintenance (2026-09-05)

**Delivered CLI graph.** `run.py` now exposes exactly 12 commands under one exclusive run lock:
the eight phases `ingest`, `embed`, `infer-heads`, `catalog`, `catalog-report`, `analyze`,
`head-analysis`, `report` plus maintenance `verify`, `reindex`, `cleanup`, `reset`. Legacy aliases
(`stratify`, `segment`, `classify`, `head`) and unknown commands exit `2`. Superseded run.py
orchestration/loaders/model-cache/legacy phase wrappers were deleted outright (no archival-callable
fallback); removed imports confirmed dead by caller census.

**Lock.** Non-blocking `fcntl.flock(LOCK_EX|LOCK_NB)` on `OUTPUT_ROOT/.run-lock` (local output
root) or a local-temp lock keyed by `sha256(resolved DB path)` when the output root is on a
different device (never beside an unreliable non-local file). Contention exits `2` with a
diagnostic; `_RunLock.__exit__` releases on every path.

**verify / reindex / cleanup / reset.** `verify [--strict]` is current-format-only and owns WAL
recovery/checkpoint of a WAL-bearing current catalog; strict freshly rehashes payloads (same-size
tamper caught). `reindex` wraps `reconcile_current_manifests` (current-FS only, no audio/models).
`cleanup --scope {staging|stray|views}` is report-then-remove of current-format grammar+manifest
candidates with `--dry-run` default for staging/stray; legacy/bare/`.vN` never classified.
`reset --scope analysis` removes only disposable `research.duckdb`(+WAL)+views and is proven to
byte-preserve `corpus/streams/heads/audio_masks/observation_commits/catalogs`.

**Follow-on (P1-S4 reopen, 2026-09-05):** derived-phase catalog resolution is now authoritative.
`run.py` `_open_derived_catalog` -> `catalog_storage.open_current_catalog` (the ad-hoc
`_open_latest_catalog_snapshot` newest-mtime seam was deleted); `_run_catalog` now durably publishes
the built snapshot via `publish_catalog_snapshot` writing `catalogs/<catalog-id>/` +
`catalogs/current.json` last. A WAL-bearing / missing / incomplete / corrupt / mismatched EXISTING
current catalog is a typed refusal routed to `verify` (exit 1; `--strict` fail-fast) per DD L272-273;
only the true no-current-catalog-yet case (no `catalogs/current.json`) warns+skips. Proofs (c) catalog
isolation and (f) disposability/reindex/analyze reuse equality added in `test_proofs_publish_reuse.py`;
`conftest` compact-catalog builder and the phase4 dispatch/verify-strict seeders now publish a real
`current.json`. Fix: `streams/reindex.py` catalog scan now accepts the canonical catalog manifest's
INTEGER `schema_version` (`str(...) != "1"`), so reindex no longer flags every published catalog.

**Deferred to P1-S5 (name each, intentionally not done here):** whole-module deletion of
`classify.py`, `head_pooling.py`, `strategy_ctp/`, legacy `strategy_ptc`/`strategy_binned` readers
and optimizers, `cache/*`, `cache_identity.py`, `db/{flat,binned,truncation,canary,stream_registry}.py`
dead-table DDL, `report/*` legacy, wholesale `common/{stratify,segment,analyze}.py`, and the obsolete
cleanup scopes' module-level deletion. The 3 surviving classify-gate tests in `test_ctp_phase_gate.py`
remain green and are P1-S5-bound. Deleted test files/subjects are recorded in the P1-S4 step annotation.

## Plan E P1-S5 hard cut — corrective pass (2026-09-05)

Recorded here are the plan-level outcomes of step **P1-S5** in plan
`TASK-frozen-observation-corrective-pass-E-head-cli-hard-cut` ("Frozen Head Analysis, CLI
Maintenance, and Hard-Cut Deletion"). The step deleted or migrated every remaining hard-cut legacy
surface, corrected the schema and report contracts, and restored the fixture/validator to the
current schema. Work was executed in three waves; all gates were green at each wave boundary.

### Wave structure

- **Wave 1** (prior worker session): head-label alignment; canonical-only `common/head_analysis.py`
  and `db/head_phase.py`; deleted `common/analyze.py`, `common/segment.py`, `common/stratify.py`,
  `pooling.py`, `strategy_ctp/`, `strategy_ptc/`, `strategy_global_pool/`, `db/binned.py`,
  `db/truncation.py`, and legacy caches. Green 871 passed / 1 skipped.
- **Wave 2a** (prior worker): report rewrite toward the catalog contract (report `_heads` replaced,
  `_binned`/`_optimizer`/`_truncation` deleted); green baseline 801 passed / 2 skipped.
- **Wave 2b** (this pass): Exec-Planner AMEND execution — 13-table DDL drop, `db/stratify.py`
  deletion, `helpers/binning.py` strip, the `PTC_BIN_MODES`→`TEMPORAL_BIN_MODES` rename in
`common/head_analysis.py`, canary cleanup, and a
  full `generate_fixture_report.py` / `validate_fixture_report.py` rewrite; green 798 passed / 1
  skipped.
- **Wave 3** (this pass): documentation refresh (CONTRACTS.md / README.md / FINDINGS.md), audit
  allowlist census, final whole-tree gates, and the P1-S5 completion mark.

### Exec-Planner AMEND (2026-09-05)

Planning identified a report/DDL/fixture gap between the plan text and the codebase reality, and
amended step P1-S5 in seven points: (1) a binding seven-section report contract
(`summary`/`corpus`/`analysis`/`winners`/`head-analysis`/`provenance`/`efficiency`); (2) active
analysis/identity/grouping/baseline rules (decode `catalog:{backbone}:{score_variant}:v{version}:{keyset}`,
SearchRepresentationClass collapse, deterministic catalog baseline — never a synthesized flat
medoid); (3) a report-module census (retain/rewrite `_base`/`_retrieval`/`_summary`/`_winners`/
`_winners_report`; retain `_corpus`/`_efficiency`; replace `_heads`; delete `_binned`/`_optimizer`/
`_truncation`); (4) removal of twelve dead tables from schema + tests; (5) fixture/validator/
report-test rewrite to schema-v2 with EffNet **and** MusicNN populations and
`validate_fixture_report(path) -> None`; (6) canary / binning / stratify / cleanup decisions; and
(7) coupled verification of the regenerated fixture and live `report` command.

### Deviations from whole-file deletion

Several surfaces were **retained-stripped** rather than deleted because an active owner survives:

- `db/flat.py` — RETAINED-stripped (the run-scoped `analyze_metrics` / `song_retrieval_metrics`
  writer surface is active); legacy flat/PTC helpers removed.
- `helpers/binning.py` — RETAINED-stripped (temporal-segmentation algorithms + distance constants
  live on); legacy-only members removed.  (The executable `PTC_BIN_MODES`→`TEMPORAL_BIN_MODES`
  constant now lives in `common/head_analysis.py`, not here.)
- `db/canary.py` — RETAINED (post-crash rollback-only canary over surviving PK/UNIQUE tables,
  enumerated dynamically from `duckdb_constraints()`); historical CTP labels removed from
  executable canary strings.
- `db/songs.py`, `db/queries.py` — RETAINED-stripped (active `upsert_song` / `query_analysis_done`
  retained; legacy dead-table writers/progress helpers removed).
- `report/*` — RETAINED and migrated to the seven-section catalog contract (not whole-module
  deletion).
- `strategy_binned/` (whole package) — deleted under the authorized option (c) override of the
  superseded GK3 Blocked note.

### Deleted-file census summary

Waves 1–3 deleted: `classify.py`, `head_pooling.py`, `pooling.py`, `cache/*` (flat/binned
heads+vectors, `binned_ptc*`, `binned_ctp*`) + `cache_identity.py`, `strategy_ctp/`, `strategy_ptc/`,
`strategy_binned/`, `strategy_global_pool/`, `common/analyze.py`, `common/segment.py`,
`common/stratify.py`, `db/binned.py`, `db/truncation.py`, `db/stratify.py`, legacy `report/_binned.py`
`_optimizer.py` `_truncation.py`, and the legacy `generate_fixture_report.py` / `validate_fixture_report.py`
(replaced). Schema: the thirteen `pooled_vecs`, `head_results`, `head_agreement_rows`,
`patch_features`, `binned_pair_sims`, `binned_classify_ctp`, `binned_song_stats`,
`truncation_robustness_rows`, `binned_ctp_vecs`, `binned_ptc_ctp_metrics`, `head_sim_corr_rows`,
`binned_calibration`, and `stratified_corpus` tables were physically dropped (no replacement /
compatibility DDL); the retained schema is exactly ten tables.

### Gate numbers (final, 2026-09-05)

Full research suite `python -m pytest scripts/embedding_research/tests/ -q`:
**798 passed / 1 skipped / 0 failed**. The single remaining skip is the pre-existing documented
OPT-IN block-layer durability test in `tests/test_stream_write_proxy.py` (no replay harness exists
here) — the Wave-2a second skip (the legacy `ctp` fixture test) was removed by restoring that test
under an active name. Net suite delta vs the Wave-2a 801/2/0 baseline: −5 stratify tests removed,
+2 passed / −1 skip from the fixture-test restore ⇒ 798 passed / 1 skipped. Forbidden-vocabulary
audit: **7 passed** (allowlist re-censused after the deletions; no entry weakened, none removed
against a still-live surface, no tokens added). `compileall` clean; `ruff format --check` clean;
`ruff check` clean on all Wave-2b/3 changed files (the only whole-tree finding is a pre-existing
`PERF401` in `config.py`, untouched and out of scope); CLI `--help` lists exactly 12 commands
(8 phases + verify/reindex/cleanup/reset); import smoke of every retained touched module clean.
`P1-S5` marked complete after Wave 3.


## Plan E P1-S6 — whole-tree negative audit + proof gate (2026-09-05)

Final PASS/FAIL gate of the Plan-E hard cut
(`TASK-frozen-observation-corrective-pass-E-head-cli-hard-cut`). Re-audited the complete
research tree independently (no code edits; tree exactly as left by P1-S5). Result: **PASS —
zero executable violations**, every positive proof green, P1-S6 marked complete.

### Sweep scope + method

- Ran the executable gate `tests/test_audit_forbidden_vocabulary.py` (**7 passed**): layer-1
  foundation (`helpers/thresholds.py`, `helpers/toml.py`, `research_config.toml`) executable-clean;
  layer-2 whole-non-test-tree NAME-token regression guard, allowlist = {`std_scaled`→
  common/head_analysis.py, `rep_a`/`rep_b`→validate_fixture_report.py}.
- Independent targeted grep sweep (word-boundary + substring, case-insensitive) across all
  production `.py`/`.toml`, tests, and the emitted fixture `report.json` for every parts-CONTRACTS
  §"Forbidden surfaces after Plan E/F" surface (std_scaled, calibration/p50 runtime, archival_ctp,
  rep_a, rep_b, search_view_hash, ANNIndex, ann_recall_sweep, FAISS/ANN/hnsw/_faiss backends, CTP
  implementation/switch/tables, classify.py, head_pooling.py, old run.py orchestration, old artifact
  parser/adoption/supersession branches, register_legacy/_classify_rowless/_family_versions/
  _next_artifact_ref, threshold-specific copied caches/tables, per-patch durable membership, old
  optimizer/truncation paths) plus the 13 dropped-table names (pooled_vecs, head_results,
  head_agreement_rows, patch_features, binned_pair_sims, binned_classify_ctp, binned_song_stats,
  truncation_robustness_rows, binned_ctp_vecs, binned_ptc_ctp_metrics, head_sim_corr_rows,
  binned_calibration, stratified_corpus) in DDL-or-reader-or-writer.

### Zero-executable-hits result

- No executable forbidden surface found. Every production-source occurrence of a forbidden token is
  (a) docstring/comment prose (non-executable traceability — allowed), (b) a runtime
  **negative-absence** guard (e.g. `catalog.py` `if "seg_membership" in present: errors.append(...)`
  validates a snapshot contains NO per-patch table; `validate_fixture_report.py` rejects emitted keys
  containing `rep_a`/`rep_b`/`global_pool`/`ptc`/`ctp`), or (c) an allowlisted entry. The lone
  substring false-positive was `bounded_scoring.py` local var `rep_all` (contains "rep_a" only as a
  substring — unrelated to the forbidden field vocabulary).
- Report/fixture **emitted** vocabulary is catalog-only: report sections are exactly
  summary/corpus/analysis/winners/head-analysis/provenance/efficiency (report/__init__.py L328-334);
  the only `global_pool/ptc/ctp/rep_a/rep_b` string occurrences in the report/fixture surface live in
  validate_fixture_report.py's reject-list. The regenerated fixture `report.json` (schema_version 2)
  carries exactly those 7 sections, a `SYNTHETIC FIXTURE — no empirical retrieval claim.` warning, and
  no forbidden key/token.
- Deleted modules are physically absent from disk (classify.py, head_pooling.py, pooling.py,
  cache/*, cache_identity.py, strategy_ctp|ptc|binned|global_pool/, common/{analyze,segment,
  stratify}.py, db/{binned,truncation,stratify}.py, report/{_binned,_optimizer,_truncation}.py). Full
  suite + import smoke + compileall confirm no retained module imports a deleted surface.

### Positive-proof citations (test file::test)

- **(a) exact 12-command CLI** — verified live: `python -m scripts.embedding_research.run --help`
  lists exactly ingest/embed/infer-heads/catalog/catalog-report/analyze/head-analysis/report +
  verify/reindex/cleanup/reset; legacy alias `stratify` → exit 2 ("retired/legacy phase name") and
  unknown `bogus` → exit 2. Tests: test_phase4_dispatch_boundaries::test_cli_exposes_exactly_eight_phases_in_order
  / test_cli_phase_runners_map_exactly_the_eight_phases / test_resolve_command_rejects_each_legacy_alias /
  test_resolve_command_rejects_unknown_command; test_maintenance_proofs::test_cli_help_lists_all_twelve_commands /
  test_cli_legacy_alias_exits_2 / test_cli_unknown_command_exits_2.
- **(b) catalog-only active metrics** — analyze writes + report reads ONLY `strategy_type='catalog'`:
  db/analyze_scope.py::write_catalog_analyze_rows (L183) writes strategy_type `"catalog"`;
  report/_retrieval.py::query_analyze_metrics `WHERE strategy_type = ?` with CATALOG_STRATEGY_TYPE=
  `"catalog"` (report/_base.py L76). Tests: test_report::test_query_analyze_metrics_catalog_only_never_legacy_allowlist;
  test_report_command_smoke::test_report_command_smoke_seven_sections_catalog_only (analysis
  subsection titles exactly {effnet,musicnn}).
- **(c) separate EffNet/MusicNN never cross-averaged** — test_report_medoid_baseline::test_effnet_musicnn_independent_never_cross_averaged;
  test_report_command_smoke (winner/analysis subsections keyed per-backbone);
  test_validate_fixture_report::test_full_fixture_validates_effnet_and_musicnn_populations.
- **(d) one execution per equal representation; aliases preserved sorted, never duplicated** —
  test_analyze_collapsed_once::test_analyze_executes_one_materialize_and_per_class_scorer_calls /
  test_scorer_seam_feeds_one_canonical_input_per_logical_pair_across_two_classes;
  test_search_representation_collapse::test_one_materialize_and_one_scorer_execution_per_collapsed_class;
  report test_report_medoid_baseline::test_equal_representation_collapse_single_class_no_duplicate_rows
  + test_report_command_smoke L88 (alias config 5 carried, not duplicated); alias-sorted
  test_report::test_scope_recorded_alias_ids_and_canonical.
- **(e) synthetic fixture/no-empirical labeling** — validator CLI on the live fixture
  `/workspace/scripts/outputs/embedding_research/report/report.json`: `OK: ... satisfies the
  schema-v2 fixture-report contract`, exit 0; fixture carries the SYNTHETIC warning (no empirical
  retrieval claim). Test: test_validate_fixture_report::test_full_fixture_validates_effnet_and_musicnn_populations.
- **(f) retained phase_timings + upsert_phase_timing + dynamic duckdb_constraints canary +
  detect_post_crash** — test_canary::test_canary_enumerates_every_pk_unique_table_from_duckdb_metadata /
  test_post_crash_detected_from_surviving_wal_file / test_post_crash_detected_from_non_completed_run_provenance;
  db/_schema.py keeps phase_timings (PK run_ts,phase) + upsert_phase_timing as the active efficiency
  source.
- **(g) seven-section report contract emitted by the live report command** —
  test_report_command_smoke::test_report_command_smoke_seven_sections_catalog_only (exact 7 ids in
  order, zero forbidden vocab in every emitted section, report.json/report.html written, live
  `report_run` path, no inference).
- **(h) durability/reuse proofs green** — test_proofs_publish_reuse::test_c_wal_bearing_current_refused_by_derived_phases_with_verify_directive
  + test_f_research_db_delete_reindex_rerun_reuse_equality; test_maintenance_proofs::test_strict_verify_flags_samesize_tamper_only_under_strict
  / test_reset_analysis_removes_only_disposable_db_and_views (DB deletion/reindex/analyze/head-analysis
  reuse with zero segmentation/inference recomputation).

### Gate numbers (2026-09-05)

- `python -m pytest scripts/embedding_research/tests/ -q`: **798 passed / 1 skipped / 0 failed**
  (single skip = pre-existing documented OPT-IN block-layer durability skip, test_stream_write_proxy.py).
- `python -m pytest scripts/embedding_research/tests/test_audit_forbidden_vocabulary.py -q`: **7 passed**.
- `python -m compileall scripts/embedding_research`: clean.
- `ruff format --check scripts/embedding_research`: clean.
- `ruff check scripts/embedding_research`: exactly 1 finding — pre-existing `config.py:195 PERF401`
  (manual-list-comprehension), recorded as out-of-scope debt, not fixed.
- Fixture validator CLI: OK (exit 0).
- `python -m scripts.embedding_research.run --help`: 12 commands; import smoke of
  run/cleanup/verify/db/db.flat/db.head_phase/db.canary/db.queries/db.songs/report/common.head_analysis/
  common.catalog_analysis/helpers.binning/helpers.thresholds/helpers.toml/generate_fixture_report/
  validate_fixture_report: OK.

### Scoped-diff audit

`git diff HEAD --name-only`: **zero paths under `nomarr/` or `frontend/`**. All changed paths are
under `scripts/embedding_research/**` (production + tests + docs + regenerated external fixture —
Plans A-E corrective work) OR the documented PRE-EXISTING out-of-scope dirt
(docs/dev/skills/*, pyproject.toml, scripts/diagnostics/agent_dashboard/*, scripts/human-scripts/*
+ tests/unit/scripts/test_validate_skills.py), which predates this plan and is excluded from the
corrective-pass work product. `artifacts/plans/**` and `artifacts/designs/**` planning artifacts are
gitignored (not present in the diff). No embedding_research change reaches production/frontend.

### ptc-token-constant rationale (deferred-residual judgment)

- `SCORING_SEMANTICS_VERSION` (=1; owner common/head_analysis.py, local pins in bounded_scoring.py/
  search_views.py) — ACTIVE scoring-semantics version; DB-persisted `scoring_semantics_version`; not
  a forbidden token; RETAIN.
- `PTC_SEMANTICS` = frozenset({"direct_l2"}) (common/head_analysis.py) — ACTIVE canonical
  threshold-semantics set; its VALUE `direct_l2` is the sole surviving semantics; the constant NAME is
  an internal identifier, never emitted as report/fixture vocabulary, and is not a forbidden token (the
  audit forbidden set has no `ptc` NAME token; only CTP/archival_ctp surfaces are forbidden and are
  gone). RETAIN.
- `PTC_STRATEGY_VERSION` (=1, helpers/thresholds.py) — ACTIVE config-strategy version used in
  canonical_config_hash and the canonical head-phase predicate; not a forbidden token; integer value,
  never emitted legacy vocabulary. RETAIN.
- None of the three violates any audit forbidden token or parts-CONTRACTS forbidden surface, and none
  is emitted vocabulary. Renaming DB-persisted version semantics is not worker-authorizable; recorded
  as PASS with rationale. (Note: the `std_scaled` audit allowlist entry for common/head_analysis.py
  protects only a prose-comment occurrence at head_analysis.py L85 — the tree has zero executable
  `std_scaled`.)

### Tree state handed to Plan F

Research tree is executable-clean of every forbidden surface; canonical 10-table schema; catalog-only
seven-section report + regenerated external fixture/validator green; frozen 12-command CLI; all
semantic/durability proofs green. Plan F (tests/docs/release gate) consumes this as its input
baseline. Only residual audit-recorded debt: `config.py` PERF401 (out-of-scope), prose-only
traceability occurrences of removed vocabulary in docstrings, and the intentionally historical
CONTRACTS/README sections.
