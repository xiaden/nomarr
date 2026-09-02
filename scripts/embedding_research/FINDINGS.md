# Embedding Research Findings

Ongoing notes from research runs. Add findings as they emerge — don't wait for a "final" result.

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
- **Catalog**: `seg_config`, `seg_meta`, and authoritative `seg_membership` replace threshold-specific copied vectors. Membership includes absorbed outliers; ranges are metadata only; segment/global medoids are observed source patch indices with deterministic smallest-index ties. All thresholds are evaluated in one stream load/pass. `search_view_hash` is strict logical corpus identity; `catalog_fingerprint` is manifest-only and non-self-referential; threshold aliases and structural changes are reported. Planning arithmetic is approximately `10k × 100 × 10 ~= 10M` catalog rows, not an empirical result.
- **Analysis**: Each run regenerates disposable keyset-addressed medoid views. Catalog-first analysis uses bounded exact CPU scoring and streamed metrics; normal runs retain no N×N trace. Old flat/PTC/head/CTP caches are archival read-only compatibility paths, not primary inputs.
- **Heads and CTP**: Head analysis pools frozen head streams over exact shared EffNet PTC membership and uses class-1 `act[1]`. Inclusive ranges cannot reintroduce absorbed outliers. CTP is phase-gated and disabled by default; a default run produces zero CTP work/rows and empty CTP tables are correct.
- **Cleanup and boundaries**: Active/archival/dead classification is explicit; resets are scoped (`staging`, `views`, `dead`, `archival`, `analysis-run RUN_ID`); Tier 1/2 results are protected. Only ingest/embed/infer-heads may access audio/models/ONNX/CUDA. Derived phases are CPU-only and portable. Post-crash `--verify` uses rollback-only canaries and requires EXPORT/IMPORT repair on failure.
- **Evidence limitation**: No current model/audio corpus run was available for this planning baseline. Fixture reports must be labeled synthetic. Any measured benchmark must state songs, patch distribution, dimension, backbone/model hash, hardware, software, peak RSS, elapsed time, and chunk budget.

## Completed Experiments

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

Authoritative summary of the live research pipeline's semantics (Plans A–D). Where this conflicts
with older notes, this section wins.

- **Flat baseline — observed global medoid, not coordinate median.** The benchmark baseline is
  `global_pool:{backbone}:medoid`: `pool_medoid` row-L2-normalizes the raw patches for cosine
  centrality, picks the observed row with maximum mean cosine centrality (ties → smallest index;
  zero-norm rows excluded; single patch → `(0, 0.0)`), and returns that raw float32 patch — never a
  synthetic/coordinate centroid. The coordinate-wise synthetic `median` is a *different* strategy and
  is not the baseline. `rep_type="medoid"` is allowed; `agg_method="medoid"` is rejected.
- **Separate EffNet / MusicNN populations.** Each backbone resolves its own medoid, its own
  matching-corpus manifest, and its own report rows. The two backbones are never cross-averaged; a
  flat/binned comparison always compares the same backbone's configurations over the same song set.
- **Unit-vector temporal segmentation.** Segmentation operates on unit-normed patch vectors
  (`raw_all.normalize()`), thresholded by distance from the running segment centroid —
  `temporal_global` → L2, `temporal_perdim` → per-dimension Chebyshev. Amplitude gating was removed
  (2026-05-25); segmentation responds only to distance. Each song's patches are segmented
  independently; the number of segments per song varies with the patch stream.
- **Patch-count weights.** The weighted reductions treat weights as positive temporal patch-count
  weights — one weight per source bin (row) or target bin (column), equal to that bin's patch count.
- **Exact formulas** (float64 accumulation, returns Python `float`):
  - `target_weighted(S, w_target) = (1/n_A) * sum_a( sum_b(w_target[b]*S[a,b]) / sum_b(w_target[b]) )`
    — the mean over source bins of target-weighted row means.
  - `normalized_mean_pair_weighted(S, w_A, w_B) = sum_ab(w_A[a]*w_B[b]*S[a,b]) / (sum_a(w_A[a]) * sum_b(w_B[b]))`
    — the globally weighted bilinear mean.
  - `bidirectional_weighted(fwd, rev, w_fwd_tgt, w_rev_tgt) = (target_weighted(fwd, w_fwd_tgt) + target_weighted(rev, w_rev_tgt)) / 2`.
- **Directional / symmetric conditions.** `target_weighted` is directional: forward A→B and reverse
  B→A differ (fixture gives 0.6333333333 vs 0.6000000000). The reverse matrix is supplied separately
  — never derived by transposing the forward matrix. `bidirectional_weighted` is symmetric only when
  the reverse direction is supplied consistently; `normalized_mean_pair_weighted` is symmetric when
  weights correspond. Validation rejects non-2-D inputs, length-mismatched weights, and
  zero-total-weight inputs (`ValueError`).
- **Matching-corpus policy.** For each backbone, all flat and binned configurations compare the exact
  same song set — the canonically-sorted intersection present in every required dataset
  (`MatchingCorpusManifest`). A loader returning a different set or order is rejected
  (`validate_matching_corpus`) and the config is skipped with a recorded reason — never silently
  intersected or reordered. Unequal-corpus comparisons cannot occur.
- **Explicit baseline policy.** All delta/winner/headline claims in the report are measured against
  the explicit `global_pool:{backbone}:medoid` baseline for the same backbone and K. There is no
  `dominance_rate`, no composite-tuning-sensitivity, no max/median/mean-across-flat fallback, and no
  `flat_median_disc` metric.
- **Cache invalidation / versioning.** The similarity-matrix cache (`cache/sim.py`) was removed;
  per-bin similarity matrices are composed in memory. Representation-pair matrix caches are keyed by
  `matrix_cache_identity` (scoring-semantics version `SCORING_SEMANTICS_VERSION = 1`, backbone,
  config, rep, metric, ordered song_ids, corpus hash). `versioned_cache_root` resolves
  `base/v{version}/{corpus_hash}`; stale corpora or a scoring-version change select a different
  orphaned root — old directories are never deleted, never read.
- **Shared-boundary head pooling.** The optional `head` phase pools classifier head outputs over the
  shared EffNet PTC cache boundaries only (`boundary_source="effnet_ptc"`,
  `head_pool_variant="shared_effnet_ptc_boundary"`) — never head-specific segmentation, never the CTP
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
  authoritative formulas (they are now labeled `legacy_weighted_hypothesis` comparisons); CTP as
  a primary pathway (deferred/archival).
- **Exact per-threshold configurations** (each reported separately, never collapsed): bin modes
  `["temporal_global", "temporal_perdim"]`; distance thresholds `[0.95, 1.0, 1.05, 1.1, 1.15, 1.2,
  1.25, 1.3, 1.35, 1.4, 1.45, 1.5]`; `rep_type="medoid"`; primary score variant
  `max_per_candidate_segment`; comparison vs the observed `global_pool:effnet:medoid` baseline;
  similarity cosine on unit vectors.
- **Exact score hypotheses and ambiguity policies**: primary =
  `first_index + retain_all_candidate_segments` (one contribution per candidate segment,
  collisions visible, denominator = all candidate weights); documented alternative =
  `equal_tie_split + unique_source_max` (tied source maxima split credit, colliders dropped but
  kept in the trace, denominator shrinks to retained weights). The three legacy weighted
  reductions (`target_weighted`, `bidirectional_weighted`, `normalized_mean_pair_weighted`) remain
  implemented and numerically tested but are labeled `legacy_weighted_hypothesis` — never
  authoritative primary semantics.
- **CTP isolation**: CTP source, caches, and archival loaders remain available but are disabled
  from default primary analysis (`[archival_ctp] enabled=false`): CTP requirements never
  constrain the primary corpus and CTP rows/winners never enter the primary report grid.
- **Corpus construction and hashes**: the primary corpus is the stratified candidate universe
  intersected with `flat:medoid` and every selected PTC `(bin_mode, threshold, rep_type=medoid,
  score_variant)` sidecar, canonically sorted and hashed with backbone, membership, eligibility
  dimensions, scoring-semantics version, and boundary configuration. The completed A–E repair
  recorded fixture hashes (effnet `3012791ebac8655c`, musicnn `f93bd6f21eee1e99`, size 5); the
  follow-on regenerated fixture report (Phase 2/3) re-derives corpus identity — those numbers are
  superseded here, not re-pinned in this docs phase.
- **Phase 2 regeneration (this step)**: the narrow fixture report was regenerated and its
  matching-corpus manifests re-derived. The EffNet corpus hash came out **`3012791ebac8655c`**
  (size 5) — identical to the previously recorded value, confirming the matching-corpus hash is
  deterministic across the narrow regeneration. The MusicNN corpus hash (`f93bd6f21eee1e99`, size
  5) is only computed under the explicit opt-in (`--include-musicnn-ctp`) and is unchanged. The
  validator passes against the regenerated report (exit 0).
- **Synthetic vs real**: fixture report values are deterministic synthetic in-memory data (no
  ONNX models / audio available) and must not be read as measured corpus conclusions; measured
  conclusions require a real embed/segment/classify/analyze run.

---

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
      variant and its tie/collision policy (`first_index + retain_all_candidate_segments`), the
      documented alternative (`equal_tie_split + unique_source_max`), and label the three legacy
      weighted reductions as `legacy_weighted_hypothesis` (never primary semantics).
- [ ] **CTP isolation** — state that CTP is deferred/archival (`[archival_ctp] enabled=false`), that
      CTP requirements never constrain the primary corpus, and that CTP rows/winners never enter the
      primary report grid.
- [ ] **Corpus algorithm and hashes** — state the primary corpus construction (stratified universe
      ∩ `flat:medoid` ∩ each PTC sidecar), the corpus hash/size used, and that all compared
      configurations ran on the exact same song set (or a clearly declared derived subset).
- [ ] **Head phase** — state the shared EffNet PTC boundary (`boundary_source="effnet_ptc"`,
      `head_pool_variant="shared_effnet_ptc_boundary"`), that it is optional/non-blocking, and that
      it never alters primary rows, the corpus, or the winner grid.
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
