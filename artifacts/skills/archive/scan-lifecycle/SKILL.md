---
name: scan-lifecycle
description: The Nomarr library scan lifecycle — scan record schema (library_scans table), staleness/heartbeat semantics, scan-state pipeline transitions, progress-update cadence in workflows, and the recovery path (is_scan_stale / recover_stale_heartbeats). Load when working on scan progress, scan timeouts, stale-scan recovery, library_scans schema changes, or the scan workflows (scan_library_quick_wf / scan_library_full_wf / scan_setup_wf).
---

# Scan Lifecycle & Staleness

## Mental Model

Each library scan writes a row to the `library_scans` table (one per scan run, most recent wins via `get_scan` ordering by `id desc`). The pipeline axis (`pipeline_states.scan_state`) is the authoritative "is scanning" flag; the scan row carries timing and progress counters. `mark_scan_started` (component) writes the row; `update_scan_progress` (component) mutates counters; `mark_scan_completed` writes `finished_at`. Staleness is judged by `is_scan_stale`, gated only through `LibraryPipelineService.recover_stale_heartbeats` — which is **not wired at startup** (only `recover_stale_states` runs, `nomarr/app.py:361`). A heartbeat fix is inert until that recovery is invoked.

## Coverage

**Documented:** `library_scans` column set, full data path (component → facade → repo → primitives), heartbeat/staleness semantics and legacy `scan_heartbeat` key, progress-update cadence in both scan workflows, recovery methods and their wiring state, migration + test patterns for schema changes.
**Not yet documented:** play/stop API surface for scans, tag-apply progress (calibration_svc `_update_progress` is a separate no-heartbeat counter), worker health-heartbeat docs (`last_heartbeat` in health JSON — different subsystem, same staleness idea).
**Last extended:** 2026-08-17

## Key Findings

### `library_scans` table includes a heartbeat column
- **Location:** `nomarr/persistence/models/library_scan.py:14-23` (ORM; includes nullable `heartbeat_at`), baseline migration `alembic/versions/001_current_schema_baseline.py:178-201`
- **What:** Nullable `heartbeat_at` is persisted by the PostgreSQL scan row. The legacy Arango-era doc key `scan_heartbeat` is still dropped at the insert write boundary (`nomarr/persistence/database/scan_repo.py:31,63-68`).
- **Why it matters:** `_SCAN_COLUMNS` is derived from `_T.columns.keys()`, so the ORM column is included in the insert filter; writers can persist scan activity using the canonical `heartbeat_at` field.

### Staleness compares against `started_at`, not last activity
- **Location:** `is_scan_stale` `nomarr/components/library/scan_lifecycle_comp.py:259-287`
- **What:** Elapsed = `now_ms() − scan.started_at` (must be int; default timeout 300_000 ms). `update_scan_progress` (224-256) writes only status/progress/total/scan_error.
- **Why it matters:** Progress updates happen once per folder *after* the folder completes (`scan_library_quick_wf.py:106,195,217,241`; `scan_library_full_wf.py:116,196,250,273`; `scan_setup_wf.py:76`). A single huge folder, or the discovery phase between `mark_scan_started` and the first update, can exceed the 300 s window → scan falsely judged dead.

### Only caller of `is_scan_stale` is unwired
- **Location:** `recover_stale_heartbeats` `nomarr/services/infrastructure/pipeline_svc.py:147-173`; startup call `nomarr/app.py:361`; allowlisted as dead code `deadcode_allowlist.py:819`
- **What:** `recover_stale_heartbeats` (which transitions stale libs to `not_scanned` + writes `scan_error="Scan timed out: no heartbeat received"`) is never invoked; only `recover_stale_states` (missing-task recovery) runs at startup.
- **Why it matters:** Any heartbeat-based staleness fix is behaviorally inert until this method is wired (e.g., alongside line 361 or scheduled).

### Scan row read path (for schema changes)
- **Location:** repo DTO `LibraryScanRow` `nomarr/helpers/dto/repo_dto.py:58-69`; row mapping `_row_to_dto` `scan_repo.py:34-47` (field-by-field explicit — a new column MUST be added here or it is silently absent); facade `nomarr/persistence/api/library_scans.py` (`get_scan` 38-40, `add_scan` 42-44, `update_scan` 46-52 creates-if-missing); component `ensure_scan_state`/`get_scan_state` `nomarr/components/library/library_scan_state_comp.py:66-96`.
- **Why it matters:** Add the heartbeat in all four places: ORM model, `LibraryScanRow`, `_row_to_dto`, plus writers.

### Legacy-key readers are stale (adjacent latent bug)
- **Location:** `nomarr/services/domain/library_svc/scan.py:229-232` and `nomarr/components/library/library_records_comp.py:212-217`
- **What:** Both read legacy doc keys `files_total` / `completed_at` which have no `library_scans` columns (real columns: `files_found`, `finished_at`) → API `scan_total`/`scanned_at` are always 0/None. `_pipeline_state_to_scan_status` in `library_scan_state_comp.py:31-49` also still reads `scan_doc.completed_at`.
- **Why it matters:** Not required for the heartbeat fix, but any scan-row schema work should note readers still keyed on the pre-PostgreSQL doc shape; `_DEFAULT_SCAN_FIELDS` (`library_scan_state_comp.py:20-28`) still lists `scan_heartbeat`/`files_total`/`completed_at`.

### Migration pattern (Alembic)
- **Location:** `alembic/env.py` (target_metadata = Base.metadata), `alembic/versions/001_current_schema_baseline.py` (revision `baseline_20260830`, no parent revision)
- **What:** The complete current schema is created by one baseline revision. Migrations run automatically at container startup (`docker` skill) — no manual step.
- **Note:** Pre-baseline PostgreSQL databases are unsupported and must be recreated. The baseline contract is covered by `tests/unit/persistence/migrations/test_current_schema_baseline.py`.

### Test patterns for scan code
- **Location:** `tests/unit/components/library/test_scan_lifecycle_comp.py` (component; `test_update_scan_progress_delegates_to_database_facade:351-367` asserts the EXACT payload `{"progress":5,"total":12,"scan_error":"boom"}` — breaks when a heartbeat field is added; **no `is_scan_stale` test exists**); `tests/unit/persistence/database/test_scan_repo.py` (real `pg_session` fixture; `test_create_scan_drops_legacy_keys_at_write_boundary:53-83` asserts legacy `scan_heartbeat` dropped — unaffected by a new `heartbeat_at` column); `tests/unit/persistence/api/test_library_db.py:973-1030` (MagicMock delegation tests — unaffected); `tests/unit/services/infrastructure/test_pipeline_svc.py:154-188` (covers `recover_stale_states` only, no `recover_stale_heartbeats` coverage); characterization `tests/characterization/test_persistence_facade_characterization.py:139-183` snapshots `LibraryDb_get_scan`/`LibraryDb_update_scan` — snapshots self-create at `tests/characterization/snapshots/` (conftest.py:356-382), so a new row field changes the baseline on next run.

## Critical Invariants

- `_SCAN_COLUMNS` insert filter (`scan_repo.py:31`) auto-includes newly added ORM columns, but the **update** path (`update_by_field`) does NOT filter — any non-column key raises a compile error. Never pass non-column keys through `db.library.update_scan`.
- `_row_to_dto` is explicit — every new `library_scans` column must be mapped there and in `LibraryScanRow`.
- `is_scan_stale` must fall back to `started_at` when `heartbeat_at` is absent (legacy rows / pre-migration rows / scans before the first progress write) — otherwise pre-first-update scans immediately look stale.
- `now_ms()` is wall-clock epoch ms (`nomarr/helpers/time_helper.py`); do not mix with `internal_s()`/`internal_ms()` monotonic clocks used for duration stats.
- Component/facade boundary: workflows and pipeline_svc call the component (`mark_scan_started`, `update_scan_progress`, `is_scan_stale`); only `scan_lifecycle_comp` touches `db.library.*` scan intents.

## Sources

- Files: the 20+ files listed above (components, workflows, persistence layers, tests, alembic versions)
- `nomarr/persistence/PERSISTENCE.md`, skill `.opencode/skills/persistence-domain-model/SKILL.md`
- No ADR/DD covers scan staleness (adr_search "scan stale heartbeat" → empty)