# Temporal Segment Embedding Research for Music Similarity — Design Document

**Status:** Draft  
**Author:** xiaden  
**Created:** 2026-05-17  

**Related Documents:**
- [ADR-001: Use ONNX Runtime for ML Inference](artifacts/decisions/ADR-001-use-onnx-runtime-for-ml-inference.md) — 
- [ADR-003: Pure Boolean State Graph for File Processing Pipeline](artifacts/decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) — 
- [ADR-004: Schema Refactor v1 Graph Normalization](artifacts/decisions/ADR-004-schema-refactor-v1-graph-normalization.md) — 

---

## Scope

Research pipeline only — `scripts/embedding_research/`. No changes to production Nomarr code. Outputs are DuckDB tables and markdown/PNG reports used to inform future architecture decisions, not to ship features.

---

## Problem Statement

Nomarr is a self-hosted music library manager that automatically analyses and tags tracks using ONNX neural network backbones (EfficientNet-based `effnet` at 1280 dims and MusicNN-based `musicnn` at 200 dims). These backbones produce a sequence of patch embeddings per song — one embedding vector per short time window (roughly 150–300 patches for `effnet`, 100–160 for `musicnn`). The current production similarity pipeline pools the entire patch sequence into a single whole-song vector (mean or median), discarding all temporal structure.

The core hypothesis is that **songs are not homogeneous**: verses, choruses, breakdowns, and outros have distinct sonic characters. A whole-song pool averages these together, potentially washing out the structure that makes retrieval accurate. If temporal segments can be identified and compared independently, similarity search may become more musically meaningful.

A prior attempt used centroid-distance binning (core/mid/periphery buckets) which was geometrically wrong — all patches on a unit sphere have similar distance to the origin, so everything fell into one bin. This design document describes the corrected approach: sequential temporal segmentation with data-driven threshold calibration, correlated against raw audio features.

---

## Architecture

## System Context

Nomarr runs in a Docker devcontainer. Audio is at `/workspace/.devcontainer/test-media/`. All research state is in a single DuckDB file at `scripts/outputs/embedding_research/research.duckdb`. Patch sidecars (raw `[n_patches × embed_dim]` float32 arrays) are pre-computed by a prior `embed` phase and stored as `.npy` files in `scripts/outputs/embedding_research/patches/{song_id}.{backbone}.npy`.

The research pipeline is driven by `scripts/embedding_research/run.py` with sub-commands: `embed`, `classify`, `analyze`, `report`, `embed_binned`, `analyze_binned`.

---

## Phase 1: Temporal Segmentation + Audio Feature Correlation

### Segmentation Algorithm

Patches are scanned sequentially. A running centroid is maintained over accepted patches in the current segment. When a patch's distance from the centroid exceeds the threshold:

- **Outlier window (≤3 patches):** examine the next 3 patches. If any return within threshold, the out-of-range run is labelled outliers (excluded from both segments); the segment continues.
- **Genuine break:** if all lookahead patches also exceed the threshold, close the current segment and start a new one.

Two distance modes:
- `temporal_global` — L2 (Euclidean) distance to centroid
- `temporal_perdim` — L-inf / Chebyshev (max per-dimension absolute deviation), more sensitive to any single dimension shifting dramatically

### Threshold Calibration

Before the main sweep, scan **all songs** (not a sample) to compute the empirical patch-to-centroid distance distribution. Store `p10/p25/p50/p75/mean/sigma` in `binned_calibration(backbone, dist_mode)`. Sweep six multipliers `[0.5, 0.75, 1.0, 1.5, 2.0, 3.0]` applied to the calibrated p50.

### Segment Pooling

For each detected segment, compute four representations from its raw patches:
- `mean` — arithmetic mean across patch axis
- `median` — per-dimension median
- `max` — per-dimension maximum
- `min` — per-dimension minimum

Both raw and L2-normalised variants of each are stored. This gives 4 pool strategies × 2 normalisations = 8 vectors per segment per (backbone, mode, thresh).

### Audio Feature Extraction

For each song, extract librosa features time-aligned with the patch grid:
- **RMS energy** — frame-level energy (intensity / silence detection)
- **Spectral centroid** — brightness proxy
- **Onset strength** — attack transient envelope
- **Chroma key** — 12-dim chroma vector, dominant key per frame
- **Beat alignment** — whether each patch window falls on a detected beat

Store in `patch_features(song_id, patch_idx, rms, spectral_centroid, onset_strength, chroma_key, on_beat)`.

At each detected segment break, record the delta in each audio feature. This produces a correlation analysis: "a distance jump of magnitude X in `effnet/temporal_global` corresponds to Y change in RMS / key shift / onset spike." This characterizes what the model is actually reacting to, and validates whether the threshold calibration is cutting at musically meaningful boundaries.

---

## Phase 2: Bin-Level Cross-Song Similarity

### Per-Pair Computation

For every pair of songs (A, B):

```
Song A has N_a segments × 4 representations (mean/median/max/min)
Song B has N_b segments × 4 representations

For each (rep_A, rep_B) in {mean, median, max, min} × {mean, median, max, min}:  [16 combos]
  For each sim_metric in {cosine, l2, dot}:                                        [3 combos]
    Compute N_a × N_b similarity matrix (bin-vs-bin)
    Aggregate with {mean, median, max, min}:                                       [4 combos]
    → 1 scalar sim score

Total per pair: 16 × 3 × 4 = 192 sim scores
```

The bin-vs-bin matrix captures: "what is the most similar part of song B to part X of song A?" The aggregation then answers: "overall, how similar are these two songs when compared part-by-part?"

### Computational Strategy

2386 songs → ~2.84M unique pairs. Each pair requires up to `N_a × N_b` dot products per metric (typically 16×16 = 256 per metric). This is computed per-pair in Python loops with NumPy batching — no full matrix materialised in memory.

For each pair, the 192 scores are written to `binned_pair_sims(song_a, song_b, backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, score)`.

### Retrieval Evaluation

For each of the 192 combinations, build the full song×song similarity matrix and compute:
- **MAP@10** — mean average precision at k=10 for same-artist retrieval
- **Discriminability** — KL divergence or mean-gap between within-artist and cross-artist sim distributions
- **STD spread** — standard deviation of sim scores within vs across artist clusters

Results stored in `binned_retrieval_rows` (existing table, extended).

---

## Phase 3: Reporting

Every metric captured:

**Per-song:**
- Bin count per (backbone, mode, thresh)
- Patch count distribution across bins
- Within-song bin diversity (pairwise bin distances, STD)
- Outlier patch counts
- Audio feature deltas at each segment break

**Per combination (192 per backbone/mode/thresh):**
- MAP@10, P@1, discriminability
- Within-artist vs cross-artist sim score distributions (mean, STD)
- Ranking across all 192 combinations

**Summary:**
- Best combination per backbone, ranked by discriminability
- Comparison against whole-song pooling baseline
- Heatmaps: rep_type_A × rep_type_B discriminability by metric
- Feature correlation table: which audio features predict segment breaks

---

## Downstream Model Implications

If bin-level comparison outperforms whole-song pooling, the research outputs directly inform three candidate model architectures:

1. **Multi-Instance Learning (MIL)** — songs as bags of segment embeddings; train a learned aggregation function on same/different-artist supervision
2. **Cross-attention similarity** — transformer cross-attention between segment sets to find most-aligned parts (soft matching)
3. **Set metric learning** — learn a distance function directly over temporal segment sets

The best-performing `(rep_type, sim_metric, agg_method)` combination from this sweep would seed the architecture choice and initialisation strategy for the learned model.

---

## Design Goals

1. **Characterize what the embedding models are sensitive to.** Correlate detected segment breaks with raw audio features (RMS energy, spectral centroid, onset strength, chroma key, beat alignment) to understand whether the model is finding musically meaningful boundaries.

2. **Evaluate whether bin-level similarity outperforms whole-song similarity.** For each combination of bin representation (mean/median/max/min), similarity metric (cosine/L2/dot), and cross-song aggregation (mean/median/max/min), compute same-artist retrieval MAP@10 and discriminability. Compare against the whole-song baseline already in the DB.

3. **Identify the optimal segmentation configuration.** Sweep six threshold multipliers (0.5×–3.0× the calibrated median patch distance) and two distance modes (L2 global, L-inf per-dimension) to find the setting that produces the most musically coherent and retrieval-useful segments.

4. **Produce a complete dataset for downstream model training.** If bin-level comparison outperforms whole-song pooling, the full matrix of per-pair bin similarity scores becomes training data for a learned aggregation model (Multi-Instance Learning, cross-attention, or set metric learning).

---

## Constraints

- Must run inside the `nomarr-dev` Docker devcontainer
- No GPU assumed — all inference via ONNX CPU runtime
- Memory: patches never all loaded simultaneously — one song at a time
- DuckDB is the only storage layer — no Postgres, Redis, or external services
- librosa must be available in the devcontainer Python environment
- The `embed` phase (whole-song patch extraction) is pre-completed for all 2386 songs and must not be re-run
- All schema changes must be forward-only migrations (no editing `ensure_schema`)

---

## Open Questions

1. **Audio feature time alignment:** Librosa operates on raw audio at a fixed sample rate; the embedding model operates on mel spectrogram frames. Exact patch-to-frame alignment depends on the model's hop size. How precisely can we align librosa frames to embedding patch indices without access to the model's internal preprocessing parameters?

2. **Pair score storage volume:** 2.84M pairs × 192 scores = ~546M rows in `binned_pair_sims`. At ~40 bytes/row this is ~21GB. Is full storage acceptable, or should we compute metrics on-the-fly and discard per-pair scores after evaluation?

3. **Calibration scope:** Calibration currently uses up to 500 songs. The design calls for all songs. Does using the full corpus for calibration meaningfully change the p50 threshold, or does it converge quickly enough that 500 is sufficient?

4. **Outlier window size:** The current OUTLIER_WINDOW=3 was chosen heuristically. Should this be part of the sweep, or fixed?

5. **Learned model viability:** If MIL or cross-attention is pursued, what supervision signal is available beyond artist identity? Album, genre, mood tags from the existing Nomarr head classifiers?

---
