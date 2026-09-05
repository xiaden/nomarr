---
name: library-scan-lifecycle
description: Library scan lifecycle in Nomarr — scan record persistence (library_scans table), progress updates, heartbeat/staleness detection, and recovery. Use when working on scan start/progress/complete, is_scan_stale, recover_stale_heartbeats, update_scan_progress, mark_scan_started/completed, or the library_scans schema.
---

# Library Scan Lifecycle

## Mental Model

Each library scan is a row in `library_scans` (SQLAlchemy `LibraryScan` in `nomarr/persistence/models/library_scan.py`, exposed to callers as a domain `LibraryScan` value via the `LibraryScansDb` persistence facade). A parallel `pipeline_states` row holds per-axis pipeline state (`scan_state` field) — the authoritative "is this library scanning" flag; the scan record is supporting data. Scan writes flow: workflow → `nomarr/components/library/scan_lifecycle_comp.py` → `db.library` domain facade (`nomarr/persistence/api/library_scans.py`) → `ScanRepository` (`nomarr/persistence/database/scan_repo.py`). `LibraryPipelineService.recover_stale_heartbeats` (`nomarr/services/infrastructure/pipeline_svc.py`), called once at startup from `nomarr/app.py`, resets any library whose scan has missed its heartbeat.

The domain facade is **`Library`-keyed** (natural `name` identity), not int-id keyed — callers never pass or receive storage row ids. Components in `nomarr/components/library/` are the only writers; the scan workflows (`scan_library_quick_wf`, `scan_library_full_wf`, `scan_setup_wf` under `nomarr/workflows/library/`) drive scan runs.

Column timestamps are wall-clock ms via `now_ms()` (`nomarr/helpers/time_helper.py`). `started_at` is set once at scan start and never changes; `heartbeat_at` is refreshed on every progress write so long-running scans are not mistaken for dead.

## Coverage

**Documented:** `library_scans` columns + single schema baseline, domain-facade write path (`start_scan` / `record_scan_progress` / `complete_scan` / `get_scan`), heartbeat semantics, staleness check, the resolved progress-alias mapping, stale-write guard, recovery wiring, and `_row_to_dto` behavior.
**Not yet documented:** tag-extraction pass of the two-pass scan; scan status API surface details.
**Last extended:** 2026-09-04

## Key Findings

### `library_scans` table (single schema baseline)
Schema lives in the **single** baseline `alembic/versions/001_current_schema_baseline.py` (the only migration file — there is no longer a 001→004 chain; `heartbeat_at`/`finished_at`/`error` are present from the start). Columns (`nomarr/persistence/models/library_scan.py`):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int PK | autoincrement |
| `library_id` | int FK | → `libraries.id`, NOT NULL |
| `scan_type` | str | `quick`/`full`, NOT NULL |
| `status` | str | NOT NULL (e.g. `in_progress`, `completed`) |
| `started_at` | int ms | NOT NULL |
| `heartbeat_at` | int ms \| None | nullable liveness probe |
| `finished_at` | int ms \| None | nullable, set on completion |
| `files_found` | int | NOT NULL default 0 |
| `files_processed` | int | NOT NULL default 0 |
| `error` | str \| None | nullable |

`_row_to_dto` (`scan_repo.py`) maps a SQLAlchemy `Row` to a `LibraryScanRow` TypedDict (`nomarr/helpers/dto/repo_dto.py`) with explicit fields `id, library_id, scan_type, status, started_at, heartbeat_at, finished_at, files_found, files_processed, error` — all present under the single baseline, so no KeyError on old schemas.

### Domain facade write path (`LibraryScansDb`, keyed by domain `Library`)
- `start_scan(library, scan_type, started_at)` — `ScanRepository.create_scan({library_id, scan_type, status:"in_progress", started_at, heartbeat_at: started_at})`, so a new scan has a heartbeat immediately. Requires an existing library (`_resolve_library_id`).
- `record_scan_progress(library, *, heartbeat_at, status=None, progress=None, total=None, scan_error=None)` — raises `ValueError` if **no scan row exists** (never auto-creates); maps `progress→files_processed`, `total→files_found`, `scan_error→error` and writes through `ScanRepository.update_current_scan`. Returns the updated `LibraryScan`.
- `complete_scan(library, finished_at)` — writes `{status:"completed", finished_at}` via `update_current_scan`.
- `get_scan(library)` — returns the most recent scan row as a domain `LibraryScan`, or `None`.

### Progress-alias mapping is RESOLVED (was: "keys don't match schema columns")
Historically `update_scan_progress` passed `progress`/`total`/`scan_error` straight to an `update(...).values()` with no column filtering, colliding with the real columns `files_processed`/`files_found`/`error` (`CompileError: Unconsumed column names`). **This is fixed in current code.** The facade (`record_scan_progress`, `library_scans.py`) maps the aliases to real column names, and `ScanRepository.update_scan` / `update_current_scan` (`scan_repo.py`) defensively normalize the same `progress`/`total`/`scan_error` aliases and filter to `_SCAN_COLUMNS` (derived from the ORM table). Verified against `nomarr/persistence/api/library_scans.py` and `nomarr/persistence/database/scan_repo.py`.

### Stale-write guard
`ScanRepository.update_current_scan(library_id, scan_id, fields)` runs the update only while `scan_id` is still the library's latest scan (`MAX(id)` correlated predicate). A caller that read an older row before another scan started gets a **no-op**, and the facade raises `ValueError("...the scan is no longer current")` rather than silently mutating scan history.

### Heartbeat & staleness
- `update_scan_progress` (comp) always injects `heartbeat_at = now_ms().value` via `record_scan_progress`, so a progress write doubles as the heartbeat.
- `is_scan_stale(db, library, timeout_ms=300_000)` returns `False` unless the pipeline `scan_state == "scanning"` (`SCAN_IN_PROGRESS`); then prefers `scan.heartbeat_at`, falls back to `scan.started_at` if heartbeat is not an int, and returns `False` if neither is an int. `elapsed > timeout_ms` ⇒ stale.
- `mark_scan_completed` calls `complete_scan(library, now_ms().value)` then transitions the pipeline scan axis to `SCAN_COMPLETE`.

### Recovery wiring (`app.py` → `pipeline_svc`)
Startup (`nomarr/app.py`) constructs `LibraryPipelineService` and calls `recover_stale_states()` then `recover_stale_heartbeats()` (~lines 351/353). `recover_stale_heartbeats(timeout_ms=300_000)` (`pipeline_svc.py:153`) transitions stale scanners to `SCAN_NOT_SCANNED` and writes `scan_error="Scan timed out: no heartbeat received"`.

## Critical Invariants
- `pipeline_states.scan_state` is the authoritative scanning flag; the scan record is supporting data. `is_scan_stale` requires `scan_state == "scanning"`.
- `started_at` is immutable once set; `heartbeat_at` is the mutable liveness probe.
- `record_scan_progress` / `complete_scan` require an existing scan row (raise `ValueError` otherwise) and refuse stale writes via the latest-row guard.
- Domain-facade callers use `Library` (natural name) identity — never raw `library_scans` row ids.
- Test DBs get schema via `Base.metadata.create_all` (tests/integration/conftest.py), so ORM changes appear automatically in tests.

## Sources
- `nomarr/components/library/scan_lifecycle_comp.py` (`mark_scan_started`, `update_scan_progress`, `is_scan_stale`, `mark_scan_completed`, `on_scan_complete_pipeline_hook`, `transition_to_scanning`, `check_interrupted_scan`)
- `nomarr/persistence/api/library_scans.py` (domain facade), `nomarr/persistence/api/library.py`
- `nomarr/persistence/database/scan_repo.py`, `nomarr/persistence/models/library_scan.py`, `nomarr/helpers/dto/repo_dto.py` (`LibraryScanRow`)
- `nomarr/services/infrastructure/pipeline_svc.py` (`recover_stale_states`, `recover_stale_heartbeats`), `nomarr/app.py` (startup wiring)
- `nomarr/components/library/library_scan_state_comp.py` (`get_pipeline_state`, `transition_pipeline_axis`)
- `nomarr/workflows/library/scan_library_quick_wf.py`, `scan_library_full_wf.py`, `scan_setup_wf.py`
- `alembic/versions/001_current_schema_baseline.py` (single baseline)
- Tests: `tests/unit/components/library/test_scan_lifecycle_comp.py`, `tests/unit/persistence/database/test_scan_repo.py`, `tests/unit/services/infrastructure/test_pipeline_svc.py`
