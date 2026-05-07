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
| `apply_calibration_wf.py` | Batch apply calibration to file paths with chunked processing, live per-file reads, and concurrent file writes |
 | `write_calibrated_tags_wf.py` | Per-file calibration apply — reconstructs `HeadOutput` from DB tags + calibration, re-aggregates mood tags |
 | `calibration_loader_wf.py` | Load calibrations from `calibration_state` collection; version-hash-based caching |
 | `export_calibration_bundle_wf.py` | Export to bundle JSON (single file or per-model directory structure) |
 | `import_calibration_bundle_wf.py` | Import from bundle JSON; upserts to `calibration_state`, updates global version |

## Patterns

- **Batch context**: `BatchContext` carries shared invariants plus deferred writes; DB reads stay live per file
- **Chunked batching**: `apply_calibration_wf` processes files in chunks (default 1000) to bound peak RAM and flush sizes
- **Deferred flush**: Mood tags and calibration hashes accumulate in `BatchContext` then flush in bulk
- **Idempotent**: Generation always computes from current state; apply skips files whose `calibration_hash` matches

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** Workflows receive `Database` and pass it to components. Direct collection access in these modules uses the `Database` abstraction layer, not raw ArangoDB queries.

## Dependencies

- **Called by**: `services/domain/calibration_svc.py`, `services/domain/tagging_svc.py`
- **Calls**: `components/ml/calibration/*`, `components/tagging/*`, `persistence/` (via `Database`)
- **Receives**: `Database`, models_dir, namespace, config parameters
