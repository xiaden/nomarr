# ML Calibration

Score calibration normalizes raw model outputs so scores from different models are comparable on a [0, 1] scale.

## Responsibilities

- Compute p5/p95 percentiles from database histograms for each model label
- Apply min-max calibration to raw scores: `(raw - p5) / (p95 - p5)`
- Manage calibration state (versioning, convergence tracking, reconciliation)
- Export/import calibration data for cross-instance sharing
- Track global calibration version hash for cache invalidation

## Key Modules

| Module | Purpose |
|--------|----------|
| `ml_calibration_comp` | Histogram-based percentile derivation, min-max calibration application, sidecar export/import, global hash computation |
| `ml_calibration_state_comp` | Persistence of calibration state documents, version tracking, batch file hash updates, convergence status, reconciliation info |

## Patterns

- **Stateless computation:** `generate_calibration_from_histogram` always recomputes from current `file_tags` — no cached results.
- **Sparse histograms:** Uses 10,000-bin histograms (0.0001 resolution) with only non-zero bins stored, bounding memory regardless of file count.
- **Convergence detection:** Tracks p5/p95 deltas between runs; a head converges when `|delta| < 0.01` for both.
- **Global version hash:** Changes when any head's calibration changes, used to detect which files need recalibration.

## Dependencies

- **Upstream:** Called by `workflows/` (calibration workflow, tag reconciliation)
- **Downstream:** Calls `persistence/` for DB reads/writes (calibration_state, meta, file_tags collections)
