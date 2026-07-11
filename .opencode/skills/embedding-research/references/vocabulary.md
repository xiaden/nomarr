# Vocabulary — Backbones, Strategies, Pathways, and Heads

Full definitions and conventions for the embedding research pipeline's core concepts.

---

## Backbones

ONNX audio feature extractors. Currently: `effnet`, `musicnn`. Each produces a sequence of patch vectors (typically 128-D or 1280-D) for a given audio file.

---

## Flat Strategies

Each patch sequence is pooled into a **single embedding vector** per song.

Available strategies: `mean`, `trimmed_10`, `trimmed_20`, `median`, `max_norm`, `l2norm_mean`. The single vector is L2-normalised before storage and similarity computation.

- **`mean` is nomarr's production strategy.** It is the mandatory comparison baseline.
- Flat strategies are indexed in `strategy_flat/`. Metrics land in `retrieval_rows`.

---

## Binned (PTC) Strategies

The patch sequence is **temporally segmented** into bins using an L2-distance threshold. Each bin is independently pooled into a representative vector (`mean`, `median`, `medoid`, `max`, `min`). Similarity between two songs is the aggregated score across all bin-vs-bin comparisons.

- Segmentation algorithm: `temporal_global` (one shared threshold) or `temporal_perdim` (per-dimension Chebyshev). Configured in `research_config.toml → [binning]`.
- Metrics land in `binned_retrieval_rows`.

---

## PTC — Pool-Then-Classify

The **standard** head inference pathway:
1. Pool all patches into one vector (using the pooling strategy).
2. Run the ONNX head on that single vector.
3. Result: one activation `[p0, p1]` per song per head.

This is what nomarr does today for tag authoring. PTC scores are stored in `head_results` with `pathway = 'ptc'`.

---

## CTP — Classify-Then-Pool

The **experimental** pathway:
1. Run the ONNX head on every individual patch to get `[n_patches, 2]` activations.
2. Pool those per-patch activations into one vector using the same pooling strategy.
3. Result: one pooled activation `[p0, p1]` per song per head.

CTP scores are stored in `head_results` with `pathway = 'ctp'`. The `ptc_ctp_rows` table records which pathway produces better discriminability per `(backbone, head, strategy)`. The `binned_ptc_ctp_metrics` table records alignment between PTC and CTP scoring on binned segments.

CTP is **experimental** — if it does not outperform PTC on discriminability, it is not worth the computational cost.

---

## Heads

Binary ONNX classifiers attached to a backbone. Each head takes a backbone embedding vector and returns `[p_class0, p_class1]`. Examples: `mood_happy`, `genre_electronic`, `tonal_atonal`.

**`act[1]` is always the positive-class score. Never use `act[0]`.**

---

## What to Compare Against

| Research question | Baseline |
|---|---|
| Better sim search? | `retrieval_rows` where `strategy="mean"` and `sim_metric="cosine"` |
| Better pooling strategy? | Same — `mean/cosine` is the floor |
| Binned vs flat? | `binned_retrieval_rows` vs `retrieval_rows` for the same backbone |
| CTP vs PTC? | `ptc_ctp_rows.ptc_disc` vs `ctp_disc` per head |
| Binned segmentation threshold? | Row with same backbone/rep/metric at the numerically adjacent threshold |

A strategy is a **candidate replacement** only if it beats `mean/cosine` on `disc_general` **and** maintains comparable `map_k`. `disc_score` alone is insufficient — `disc_general` incorporates artist, genre, and head discriminability and is the single summary metric used for ranking.
