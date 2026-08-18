---
name: library-scan-lifecycle
description: Library scan lifecycle in Nomarr — scan record persistence (library_scans table), progress updates, heartbeat/staleness detection, and recovery. Use when working on scan start/progress/complete, is_scan_stale, recover_stale_heartbeats, update_scan_progress, mark_scan_started/completed, or the library_scans schema.
---

# Library Scan Lifecycle

## Mental Model
Each library scan is a row in `library_scans` (SQLAlchemy `LibraryScan` in
`nomarr/persistence/models/library_scan.py`, mapped to DTO `LibraryScanRow`
in `nomarr/helpers/dto/repo_dto.py`). A parallel `pipeline_states` row holds
per-axis state (`scan_state` field), which is the authoritative "is this
library scanning" flag. Components in `nomarr/components/library/` are the
only writers; workflows (`nomarr/workflows/library/scan_library_*_wf.py`)
drive scan runs; `LibraryPipelineService.recover_stale_heartbeats`
(`nomarr/services/infrastructure/pipeline_svc.py`), called once at
startup from `nomarr/app.py`, resets any library whose scan has missed its
heartbeat.

Column timestamps are wall-clock ms via `now_ms()` (`nomarr/helpers/time_helper.py`).
`started_at` is set once at scan start and never changes; `heartbeat_at`
(added by migration `004_add_library_scan_heartbeat`) is refreshed on every
`update_scan_progress` call so long-running scans are not mistaken for dead.

## Coverage
**Documented:** scan record CRUD path (component → `LibraryDb.scans` facade →
`LibraryScansDb` → `ScanRepository` → SQL primitives), heartbeat semantics,
staleness check, progress write path, migration chain 001→004.
**Not yet documented:** tag-extraction pass of the two-pass scan; scan status
API surface details.
**Last extended:** 2026-08-17

## Key Findings

### Heartbeat & staleness (implemented, uncommitted at review time)
- `update_scan_progress` injects `payload["heartbeat_at"] = now_ms().value`
  unconditionally — the payload is never empty, so the old `if payload:`
  guard is dead code.
- `is_scan_stale(db, library_id, timeout_ms=300_000)` prefers
  `scan["heartbeat_at"]`, falls back to `scan["started_at"]` for old rows
  (NULL heartbeat), returns False if neither is an int. State must be
  `scan_state == "scanning"` first (`SCAN_IN_PROGRESS`).
- `mark_scan_started` sets `heartbeat_at` = `started_at` at insert, so new
  scans have a heartbeat immediately.
- `recover_stale_heartbeats` (startup, app.py:363) transitions stale
  scanners to `SCAN_NOT_SCANNED` and writes `scan_error="Scan timed out: no
  heartbeat received"`.

### Progress-write payload keys do NOT match schema columns (verified)
`update_scan_progress(progress=..., total=..., scan_error=...)` passes
`progress`/`total`/`scan_error` straight through `LibraryScansDb.update_scan`
→ `ScanRepository.update_scan` → `update_by_field` → `update(table).values(**data)`
with **no column filtering** (only `ScanRepository.create_scan` filters via
`_SCAN_COLUMNS`, derived from the ORM table). The table columns are
`files_processed`/`files_found`/`error`. Verified with SQLAlchemy 2.0.52:
`CompileError: Unconsumed column names: progress`. `map_persistence_exceptions`
catches only NoResultFound/IntegrityError/OperationalError, so this propagates.
Either a translation layer is missing (all hops checked — none translates), or
every progress/error write currently fails at runtime; the heartbeat write
rides the same plumbing. Fix must include progress→files_processed,
total→files_found, scan_error→error mapping or the heartbeat write alone
cannot succeed.

### Scan record write path
`db.library.add_scan` → `LibraryScansDb.add_scan` → `create_scan` (filters
payload to `_SCAN_COLUMNS`). `db.library.update_scan` → `LibraryScansDb.update_scan`
→ updates existing record by `scan["id"]`, or **creates a new record** if none
exists — the create branch needs `scan_type`/`status`/`started_at` (all NOT
NULL); an update-only call (e.g. heartbeat-only payload) in that branch raises
IntegrityError.

### Migration conventions
Alembic (`alembic/versions/`), handwritten (not autogenerate), slug revision
IDs, chained `down_revision`. Chain: `001_initial` → `002_add_ml_model_fields`
→ `003_unique_worker_claim_keys` → `004_add_library_scan_heartbeat`.
`alembic/env.py` targets `Base.metadata`. Startup applies via
`prepare_database_workflow` → `alembic upgrade head` subprocess (fail-fast),
BEFORE service init — so code may assume migrated schema. The legacy
`nomarr/migrations/` V*.py system is a no-op tracking layer. One parallel
task's pattern: also patch `001` baseline for fresh DBs; the heartbeat fix
did NOT patch the baseline (fresh DBs get the column from 004 — fine, just
inconsistent).

## Critical Invariants
- `pipeline_states.scan_state` is the authoritative scanning flag; the scan
  record is supporting data. `is_scan_stale` requires `scan_state == "scanning"`.
- `_row_to_dto` does `m["heartbeat_at"]` — KeyError if the DB predates
  migration 004 and code is deployed without running alembic (prod is safe
  because startup runs `alembic upgrade head` first).
- `started_at` is immutable once set; heartbeat is the mutable liveness probe.
- Test DBs get schema via `Base.metadata.create_all` (tests/integration/conftest.py),
  so ORM changes appear automatically in tests.

## Sources
- `nomarr/components/library/scan_lifecycle_comp.py` (mark_scan_started, update_scan_progress, is_scan_stale, mark_scan_completed, on_scan_complete_pipeline_hook)
- `nomarr/persistence/database/scan_repo.py`, `nomarr/persistence/api/library_scans.py`, `nomarr/persistence/api/library.py`
- `nomarr/services/infrastructure/pipeline_svc.py` (recover_stale_states, recover_stale_heartbeats)
- `nomarr/workflows/library/scan_library_quick_wf.py`, `scan_library_full_wf.py`, `scan_setup_wf.py`
- `alembic/versions/004_add_library_scan_heartbeat.py`, `001_initial_v1_baseline_schema.py`
- `nomarr/persistence/sql/primitives.py`, `nomarr/persistence/sql/exceptions.py`
- Tests: `tests/unit/components/library/test_scan_lifecycle_comp.py`, `tests/unit/persistence/database/test_scan_repo.py`, `tests/unit/services/infrastructure/test_pipeline_svc.py`