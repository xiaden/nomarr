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

### Noise metric removed: bin_flat_dist

**Status**: Concluded (2026-05-25)

`bin_flat_dist` is the maximum cosine distance of any bin from the flat pooled vector. A large deviation is equally consistent with musical signal (bins capture musically distinct segments) and segmentation noise (bins are artifacts of threshold choice). Without a ground-truth label anchoring the deviation magnitude, the value is uninterpretable. Removed from `binned_song_stats` and all DB writes.

## Architectural Notes

- Calibration (`_calibrate.py`) measures the distribution of patch→centroid distances per backbone and bin-mode. These stats inform STD-threshold selection but are not the similarity metric used for retrieval — retrieval uses cosine.
- `DIST_FNS` in `helpers/binning.py` maps bin-mode names to distance callables. Currently `temporal_global` → L2, `temporal_perdim` → Chebyshev.
