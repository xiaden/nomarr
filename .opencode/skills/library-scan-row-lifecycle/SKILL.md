---
name: library-scan-row-lifecycle
description: Lifecycle and semantics of library_scans table rows — per-scan in_progress row creation, the get_scan_record most-recent-row contract, which writers require an existing row, which readers tolerate None, legacy key bugs (files_total/completed_at), and scan axis transition gaps. Use when working on scan progress, scan status, scan history, start_scan, record_scan_progress, complete_scan, or the scan setup workflow.
---

# Library Scan Row Lifecycle

## Mental Model
There is no placeholder row at library creation. The scan setup workflow creates one new `library_scans` row per scan (`scan_setup_wf` → `mark_scan_started` → `start_scan`, status `in_progress`) before transitioning the pipeline axis; that row is then updated in place for progress/heartbeat/completion. `get_scan_record` returns the most recent row by `id DESC` regardless of status. The scan *pipeline axis* (pipeline_states table) is the source of truth for "scanning" vs "not_scanned"; the scan *row* holds progress counters and timestamps.

## Coverage
**Documented:** row creation point, writer contracts (ValueError on missing row), None-tolerant readers, legacy-key mismatches, SQL shape, and setup ordering.
**Not yet documented:** whether the scan axis ever reaches "scanned" post-completion (see Key Findings — appears to stay "scanning" until startup recovery); scan-history API endpoint existence (service method has no interface caller found).
**Last extended:** 2026-08-18

## Key Findings

### Per-scan row created by scan_setup before background task
- **Location:** `nomarr/workflows/library/scan_setup_wf.py:76-78` (`mark_scan_started`), `nomarr/services/domain/library_svc/scan.py:65,114` (setup runs synchronously before task dispatch)
- **What:** setup runs synchronously: `mark_scan_started` → `LibraryScansDb.start_scan` (library_scans.py:46-56) inserts a new `in_progress` row, then `transition_to_scanning` flips the pipeline axis. The full/quick workflows only `update_scan_progress` + `mark_scan_completed` after setup has returned.

### Writers require the row to exist
- **Location:** `nomarr/persistence/api/library_scans.py:58-81` (`record_scan_progress`), `:83-88` (`complete_scan`)
- **What:** both raise `ValueError` when `get_scan_record` returns None. Production callers: full wf (scan_library_full_wf.py:113,193,247,270), quick wf (scan_library_quick_wf.py:103,192,214,238), `pipeline_svc.recover_stale_states:116` and `recover_stale_heartbeats:172` — the latter two catch ValueError (state/row divergence after crash).
- **Why it matters:** any path that runs progress/complete writes without a preceding scan_setup will crash with ValueError.

### Readers that tolerate a missing row
- **Location:** `library_scan_state_comp.py:80-85` (get_scan_state), `library_records_comp.py:277-295` (_merge_scan_state), `scan.py:200-243` (get_status), `scan_lifecycle_comp.py:92-107` (check_interrupted_scan), `:246-276` (is_scan_stale), `:150-180` (get_library_scan_histories), `library_scans.py:90-94` (remove_scan)
- **What:** all return defaults / False / None when no row exists. Frontend never touches the table directly — reads merged library docs + work status.

### Legacy-key bug: scan_total/scanned_at always 0/None; "complete" status unreachable
- **Location:** `scan_repo.py:34-48` (_row_to_dto maps finished_at/files_found) vs `library_records_comp.py:289-291` and `scan.py:230-231` (read `files_total`/`completed_at`) and `library_scan_state_comp.py:48` (`_pipeline_state_to_scan_status` reads `completed_at`)
- **What:** row DTO never contains `files_total` or `completed_at` — legacy ArangoDB-era key names. `scan_total` is always 0, `scanned_at` always None, and the "complete" branch of `_pipeline_state_to_scan_status` is dead. Fix: read `files_found` / `finished_at`.
- **Why it matters:** UI scan totals and completion timestamps are silently always zero/null. Matches prior finding in log L94 (still unfixed).

### Scan axis never transitions to "scanned" in production
- **Location:** grep of `SCAN_COMPLETE` usage — defined in `pipeline_states.py:26`, but the only production transitions are to `SCAN_IN_PROGRESS` (scan_setup_wf:79) and `SCAN_NOT_SCANNED` (failure paths full_wf:272, quick_wf:240, pipeline_svc:114,170). `query.py:268` synthesizes "scanned" for display from set-membership only.
- **Observation (unverified downstream effect):** after a successful scan the axis may remain "scanning" until startup `recover_stale_states` flips it; `is_library_scanning` (scan_lifecycle_comp:45-61) may then block the next scan with `LibraryAlreadyScanningError` within the same server session. No test asserts axis state post-completion.

### SQL shape
- **Location:** `scan_repo.py:71-77` — `SELECT ... WHERE library_id = ? ORDER BY id DESC LIMIT 1`; no status filter, no joins; `library_scans` referenced only by ORM model + repo (no other SQL in persistence). `get_libraries_in_axis_state` reads pipeline_states, not library_scans. `remove_scan`/`truncate_scan_records` have no production callers.

## Critical Invariants
- Do NOT make `record_scan_progress` / `complete_scan` tolerate a missing row by silently skipping — setup ordering guarantees the row; silent skip would mask the real state/row divergence the pipeline recovery paths log.
- `library_scans` NOT NULL: library_id, scan_type, status, started_at. Scan setup supplies these fields before progress writes begin.

## Sources
- Files: scan_repo.py, library_scans.py, library_scan_state_comp.py, scan_setup_wf.py, scan_lifecycle_comp.py, library_records_comp.py, library_admin_comp.py, pipeline_svc.py, scan.py (library_svc), scan_library_full_wf.py, scan_library_quick_wf.py, query.py, work_status_comp.py, pipeline_states.py, alembic/versions/001_initial_v1_baseline_schema.py
- Commits: f3220c3a (helper removal)
- Logs: support-researcher L101, L95, L94
