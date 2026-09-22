# Processing Workflows

Workflows for the ML tagging pipeline and file tag writing. These are the core data processing workflows that transform audio files into tagged library entries.

## Responsibilities

- Run the full ML inference pipeline for a single audio file (embedding → heads → aggregation)
- Write calibrated tags from database state to audio files on disk

## Key Modules

 | Module | Purpose |
 | -------- | --------- |
 | `process_file_wf.py` | Full ML pipeline — validate path, compute embeddings per backbone, run heads in parallel, aggregate mood tiers, persist results |
 | `write_file_tags_wf.py` | Mode-filtered tag writing — read DB tags, filter by mode (none/minimal/full), write to audio file via `TagWriter`, and classify external-file recovery |

## Patterns

- **Parallel heads**: All model heads for a backbone run in parallel after embedding extraction
- **Mode filtering**: `write_file_tags_wf` filters tags based on library `file_write_mode` (none clears, minimal writes mood-tier only, full writes all)
- **Atomic writes**: File tag writing uses `TagWriter` with safe atomic writes to prevent corruption
- **External-file recovery**: A modified file is compared by fingerprint. Same-fingerprint recovery can rebaseline the file or refresh database projections according to the requested mode. A different fingerprint is staged through `replacement_stage` during the enclosing reconciliation pass; ordinary candidates finish first, then the old song row is atomically replaced and the new row is left with initialized hydration/tag-write debt.
- **Run accounting**: A staged replacement is excluded from the remainder of the same reconciliation run, is not counted as a physical write success, and contributes fresh replacement debt to `remaining`. Consequently, a run may terminate with `outcome="partial"` rather than claiming a full drain.
- **Deferred persistence**: When `db` is provided, `process_file_wf` persists results; without it, returns results only

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** `process_file_wf` receives `Database` and passes it to components. `write_file_tags_wf` reads from DB via the abstraction and writes to disk via `components/processing/*`.

## Dependencies

- **Called by**: `services/infrastructure/workers/discovery_worker.py` (process), `services/domain/tagging_svc.py` (reconcile/write)
- **Calls**: `components/ml/audio/*` (loading, preprocessing), `components/ml/inference/*` (ONNX execution), `components/ml/onnx/*` (session caching), `components/tagging/*` (aggregation, tag writing), `components/processing/*` (file writes)
- **Receives**: `ProcessorConfig`, `ONNXModelCache`, `Database`, file path
