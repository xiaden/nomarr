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
