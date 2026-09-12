# Calibration Workflows

Multi-step workflows for generating, applying, importing, and exporting histogram-based mood calibrations. Calibration maps raw ML model scores to normalized mood tags using percentile-derived thresholds.

## Responsibilities

- Generate per-label histogram calibrations from current DB state (sparse uniform, 10K bins)
- Apply calibration to tagged files (DB-only mood tag rewrite, no ML inference)
- Load calibrations from DB with version-based caching
- Export calibration bundles to JSON files (single or per-model-directory)
- Import calibration bundles from JSON files into the database

## Key Modules

 | Module | Purpose |
 | -------- | --------- |
 | `generate_calibration_wf.py` | Single-pass histogram generation across all model labels; drift metrics (APD, SRD, JSD, median/IQR) |
| `apply_calibration_wf.py` | Batch apply calibration to file paths with chunked processing, live per-file DB reads, concurrent per-file calibration compute, and deferred DB flush |
| `write_calibrated_tags_wf.py` | Per-file calibration apply — reconstructs `HeadOutput` from canonical output streams + calibration, re-aggregates mood tags |
 | `calibration_loader_wf.py` | Load calibrations from `db.ml` calibration state (natural `(model_id, head_name, label)` identity); version-hash-based caching |
 | `export_calibration_bundle_wf.py` | Export to bundle JSON (single file or per-model directory structure) |
 | `import_calibration_bundle_wf.py` | Import from bundle JSON; upserts calibration state via `db.ml`, updates global version |

## Patterns

- **Batch context**: `BatchContext` carries shared invariants plus deferred writes; DB reads stay live per file
- **Chunked batching**: `apply_calibration_wf` processes files in chunks (default 1000) to bound peak RAM and flush sizes
- **Owner sequence (binding):** computation → tag-owner mood publication including the public `CalibrationMoodMarker` → separate locator hash/state update → downstream filesystem reconciliation (`STATE_TAGS_NOT_FRESH`). Non-`UPDATED`/`UNCHANGED` owner statuses never advance to the hash/state or reconciliation steps, and `AMBIGUOUS_COMMIT` is never retried by a caller
- **Self-contained single-file caller:** `write_calibrated_tags_wf` without a `batch_ctx` is a self-contained calibration caller. On a successful mood publication it records the calibration hash and marks the located song `STATE_TAGS_NOT_FRESH` (only when currently `STATE_TAGS_CURRENT`) for downstream filesystem reconciliation, matching the batch path
- **Deferred flush:** Batch callers defer typed `MoodReplacementCommand`s, published via `replace_mood_tags_batch`, and locator hash updates via `update_file_calibration_hashes_batch`; `apply_calibration_wf` owns the per-chunk flush and the corresponding `STATE_TAGS_NOT_FRESH` marking. The unused legacy `save_mood_tags*` names were removed by Q3-J.
- **Idempotent:** Generation always computes from current state; apply skips files whose `calibration_hash` matches, subject to separate locator hash/state

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** Workflows receive `Database` and pass it to components. Direct persistence access in these modules uses the `Database` abstraction layer (domain intents), not raw SQL queries.

## Dependencies

- **Called by**: `services/domain/calibration_svc.py`, `services/domain/tagging_svc.py`
- **Calls**: `components/ml/calibration/*`, `components/tagging/*`, `persistence/` (via `Database`)
- **Receives**: `Database`, models_dir, namespace, config parameters
