# Canonical Raw Output Stream Persistence for ML Head Outputs — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-05-08  

---

## Scope

Redesign backend persistence for per-song ML head inference artifacts so canonical storage is the raw per-output segment score stream, enabling calibration and post-hoc retagging without rerunning ONNX inference.

---

## Problem Statement

Nomarr currently computes raw per-head segment scores during inference, but the persisted artifact is `segment_scores_stats` with per-label `label_stats`. The reconstruction path is therefore split-brain: classification heads pull pooled probabilities from persisted numeric tags while also pulling per-label standard deviation from `segment_scores_stats`; regression heads reconstruct from stored means/std. This is lossy, couples reconstruction to two persistence surfaces, and prevents future pooling or retagging strategy changes from being re-derived from the original segment stream.

The user position for this design is explicit and must be evaluated seriously: there is no need for anything besides a list of floats in a single document, connected by edges to the song and the label/output, and extra metadata creates more mess than it solves. The design must decide whether that minimal representation is sufficient, what minimum structure is unavoidable, and what should remain canonical versus derived.

User clarification record (2026-05-08):

- Do **not** preserve legacy derived summaries after cutover.
- There is only **one current version per output** in the current product; YAGNI applies.
- The remainder of this DD is accepted as written.

---

## Architecture

## Overview

Recommend making **raw per-output segment streams** the canonical persisted ML artifact. Canonical means the one persisted representation from which pooled probabilities/means, per-output variance, reconstruction, recalibration, and retagging are derived. Summary stats should no longer be the source of truth.

This design agrees with the user on the core direction and mostly agrees on representation: the cleanest normalized model is **one document per `(library file, ml_model_output)` stream** whose payload is just the float list. Existing `ml_model_outputs` vertices already provide first-class per-output identity, so the stream document does not need to repeat label, output index, head name, or file id in its body.

## Recommendation

### Canonical persistence choice

1. **Canonical:** raw per-output segment streams.
2. **Derived/materialized:** pooled numeric tags, mood tags, and any summary stats (`mean`, `std`, `min`, `max`).
3. **Not recommended as canonical:** grouped stats, flat stats, or a hybrid where stats and streams are both treated as equally authoritative.

Reasoning:

- Raw streams are the only lossless representation among the options.
- They allow post-hoc recalibration and retagging without rerunning inference.
- They eliminate the current split-brain reconstruction contract.
- They align naturally with existing `ml_model_outputs` vertices.
- A per-output stream doc lets Nomarr honor the user's minimal-data preference without storing in-doc label metadata.

### Exact data model

Add a new document collection:

- `ml_output_streams`

Add new edge collections:

- `file_has_output_stream` (`library_files -> ml_output_streams`)
- `output_has_stream` (`ml_model_outputs -> ml_output_streams`)

Recommended canonical document body:

```json
{
  "_key": "<deterministic hash>",
  "values": [0.1842, 0.2171, 0.9034, 0.7712]
}
```

Deterministic identity:

- Exactly one current canonical stream per `(file_id, output_id)`.
- `_key` is derived from `(file_id, output_id)` and the write path replaces stale values on reprocessing.
- This design intentionally does **not** preserve concurrent historical versions. If product requirements change later, version retention can be added as new work rather than pre-baked into the initial schema.

This means the minimum unavoidable structure is:

- ArangoDB system identity (`_key`/`_id`)
- graph edges to the file and output vertices
- the float list payload (`values`)

No additional domain metadata is required in the stream document body.

### Why per-output instead of per-head matrix

A single per-head matrix document would force Nomarr to persist either label order, output index order, or another head-local mapping structure inside the document. A per-output stream doc avoids that requirement because ordering/label identity already exists in `ml_model_outputs` and `model_has_output`.

That is the strongest argument in favor of the user's minimal representation: by choosing the per-output unit, Nomarr can keep the persisted payload nearly structure-free while still remaining reconstructable.

## Layer mapping

| Component | Layer | Responsibility |
| --- | --- | --- |
| `ml_output_streams` persistence operations | persistence | Upsert, fetch, delete stream docs and edges via schema/facade-backed persistence |
| `ml_output_stream_store_comp` (new) | component | Convert write payloads into persistence-shaped docs/edges; bulk read streams for reconstruction |
| `tagging_reconstruction_comp` update or replacement | component | Reconstruct `HeadOutput` objects from raw streams instead of `numeric_tags + segment_scores_stats` |
| `write_calibrated_tags_wf` | workflow | Recompute pooled values/std from streams, apply calibration, regenerate derived tags |
| discovery worker deferred-write path | service orchestration | Persist raw streams after inference; stop canonicalizing to `segment_scores_stats` |

## Read/write workflow

### Write path

1. `run_single_head()` continues returning raw segment scores already available in memory.
2. The deferred write payload is reshaped from `head_name -> (segment_scores, labels)` to a persistence-ready mapping that can resolve **output ids**.
3. The discovery worker persists one `ml_output_streams` document per output activation with the stream values list.
4. The worker also continues writing derived numeric tags and tag-to-output edges as materialized query surfaces.
5. No canonical `segment_scores_stats` document is written.

### Reconstruction and calibration path

1. Load all `ml_output_streams` docs for the file.
2. Traverse `output_has_stream` back to `ml_model_outputs`, then via `model_has_output` to group outputs by head/model.
3. Order outputs by `output_index`.
4. For each output stream, recompute:
   - pooled value (same pooling rule used by live inference)
   - standard deviation across segments
5. For classification heads, build the probability vector from pooled per-output values and the stability vector from recomputed std.
6. For regression heads, use the single output stream's recomputed mean/std.
7. Apply calibration before tier assignment, then regenerate `HeadOutput` objects and derived mood tags.

This removes the need to consult stored numeric tags as reconstruction inputs. Numeric tags may still be kept as derived, query-friendly materializations.

## Tradeoffs and evaluation of the user position

### Where the design agrees

The design agrees that canonical persistence should be as close as possible to **"just the float list"** and that attaching extra per-doc metadata (label name, head name, output index, file id, num_segments, mean/std snapshots, pooling strategy fields) mostly duplicates graph information or stores values that are directly derivable.

### Minimum disagreement

The only required disagreement is structural, not philosophical:

- a canonical persisted artifact cannot literally exist as an unaddressable bare list; it still needs database identity and graph linkage;
- the system must define whether there is one active stream per `(file, output)` or multiple versions;
- if multiple versions are ever retained simultaneously, version identity must exist somewhere, ideally in key derivation or edge structure rather than as extra document body metadata.

So the minimum additional structure required is **graph identity**, not domain metadata.

### Costs of the recommended model

- More documents than per-head storage: mostly 2 docs per two-output classification head instead of 1 stats doc.
- Reconstruction now performs lightweight recomputation (`mean`, `std`, pooling) at read time.
- Some library-wide AQL analytics against precomputed `label_stats` become less direct.

### Why those costs are acceptable

- ONNX inference remains by far the expensive step; recomputing simple statistics from stored float arrays is cheap by comparison.
- Calibration and retagging are bounded workflows and can trade modest CPU for much cleaner persistence semantics.
- If library-wide analytics later need acceleration, Nomarr can recompute them from canonical streams or add temporary derived caches as an optimization. Those caches are explicitly non-canonical and should not be preserved as part of the primary persistence model.

## Migration strategy

This should be a **forward-only breaking migration**.

1. Add `ml_output_streams`, `file_has_output_stream`, and `output_has_stream`.
2. Add persistence facade bindings for the new collections.
3. Stop writing new `segment_scores_stats` docs in the discovery worker.
4. Update calibration/reconstruction workflows to read streams.
5. Invalidate old canonical data by marking affected files for retagging/reprocessing.
6. Delete legacy `segment_scores_stats` data after the cutover rather than preserving parallel derived summaries.

Do **not** attempt to migrate old `segment_scores_stats` into raw streams. That information is irreversibly lossy; backfill would fabricate detail the database no longer has.

Because Nomarr is alpha, a hard cutover with reprocessing is justified and cleaner than maintaining dual persistence paths.

## What changes

### Collections / edges

- New: `ml_output_streams`
- New: `file_has_output_stream`
- New: `output_has_stream`
- Deprecated from canonical path: `segment_scores_stats`, `file_has_segment_stats`

### Components / workflows / services

- `nomarr/components/ml/inference/ml_head_pipeline_comp.py`
  - keep returning raw segment scores; adjust deferred write payload to resolve per-output streams cleanly
- `nomarr/services/infrastructure/workers/discovery_worker.py`
  - replace `compute_segment_stats()` + `upsert_segment_stats_batch()` with raw stream persistence
- `nomarr/components/tagging/tagging_reconstruction_comp.py`
  - reconstruct from raw streams rather than from numeric tags plus stored stats
- `nomarr/workflows/calibration/write_calibrated_tags_wf.py`
  - load streams, recompute pooled values/std, then calibrate and aggregate
- `nomarr/persistence/database/segment_scores_stats_aql.py`
  - no longer part of the canonical tagging pipeline; remove from active canonical flows after cutover
- `nomarr/components/ml/inference/ml_segment_stats_store_comp.py`
  - superseded by stream-store logic; do not preserve it as part of the primary post-cutover design

## Canonical vs derived

### Canonical

- per-output raw segment streams in `ml_output_streams`

### Derived (non-canonical; may be materialized transiently if needed)

- pooled numeric tags used for query/search/UI convenience
- `HeadOutput` reconstruction products
- mood tags / tiered mood tags
- summary statistics such as `mean`, `std`, `min`, `max`
- any future grouped summaries or analytics caches

These derived artifacts are disposable outputs of the current tagging/calibration policy, not archival records to preserve through the migration.

## Direct answers to the design questions

1. **Canonical persistence should be raw segment streams**, not grouped stats, flat stats, or a hybrid with co-equal authority. Do **not** preserve legacy derived summaries through the cutover.
2. **Exact model:** one `ml_output_streams` document per `(library file, ml_model_output)` with `values: list[float]`, plus edges from the file and output vertices.
3. **Can it really be just a float list doc?** Almost yes. The document body can be just the float list, but graph identity and deterministic uniqueness are unavoidable.
4. **Calibration and post-hoc retagging** should read streams, recompute pooled values/std, apply calibration, reconstruct `HeadOutput`s, and then rewrite derived tags without rerunning ML.
5. **Current changes required:** discovery worker write path, stream persistence facade/store component, reconstruction component, calibration workflow, and migration/removal of `segment_scores_stats` from canonical reads.
6. **Migration strategy:** forward-only hard cutover with reprocessing; do not attempt lossy backfill from stats, and do not preserve legacy derived summaries.
7. **Derived vs canonical:** only raw output streams are canonical; stats, pooled values, numeric tags, and mood tags are derived.
8. **Versioning stance:** assume only one current version per output in the current product. Do not add multi-version retention design now.

## Research grounding

This recommendation is grounded in the currently shipped code paths:

- `run_single_head()` already returns raw segment arrays for classification heads.
- `discovery_worker` currently computes `label_stats` from those arrays during deferred writes.
- `write_calibrated_tags_wf` and `tagging_reconstruction_comp` currently depend on `segment_scores_stats` for std and numeric tags for pooled values, creating the split-brain contract this design removes.

---

## Design Goals

- Eliminate split-brain reconstruction between numeric tags and segment stats
- Preserve enough information for calibration and retagging without rerunning ONNX inference
- Honor the user's preference for minimal persisted structure
- Fit Nomarr's normalized graph persistence model and descriptor-based database facade
- Keep alpha-era migration simple, forward-only, and architecture-first

---

## Constraints

- Must follow Nomarr dependency direction (`interfaces -> services -> workflows -> components -> persistence/helpers`)
- Must fit graph-normalized persistence conventions already established in ADR-004 and later persistence refactors
- Must use forward-only migration rather than baseline schema edits
- Must treat `ml_model_outputs` as the authoritative per-output identity surface
- Current shipped heads are mostly 2-output classification heads; regression heads effectively have one value per segment

---

## Resolved User Answers

1. **Do not preserve** legacy derived summaries after cutover.
2. There is only **one current version per output** in the current product; YAGNI applies.
3. The remainder of this DD is accepted as written.

## Remaining Open Question

1. Exact edge naming for the new output-stream relations

---
