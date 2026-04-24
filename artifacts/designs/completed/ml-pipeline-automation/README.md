# ML Pipeline Automation — Implementation Parts

**Design Document:** [DD-ml-pipeline-automation](../../pending/DD-ml-pipeline-automation.md)

## Parts

 | Part | Title | Depends On | Layers |
 | ------ | ------- | ----------- | -------- |
 | A | Persistence Layer + Migration | None | persistence, migration |
 | B | Library Settings + Scan Lifecycle Hooks | A | helpers/dto, persistence, components, workflows, services |
 | C | Pipeline Service + Calibration Trigger | A, B | services/infrastructure, services/domain |
 | D | Worker Idle-Path Integration | A, C | components/workers, services/infrastructure |
 | E | API Endpoints + Renames | A, C | interfaces, services/domain, helpers/dto |
 | F | Frontend + Dashboard | E | frontend, interfaces, services, components |
 | G | Documentation + Cleanup | A-F | docs, services/infrastructure |

## Dependency Graph

```
  A (Persistence + Migration)
  ├── B (Library Settings + Scan Hooks)
  │   └── C (Pipeline Service)
  │       ├── D (Worker Idle-Path)
  │       └── E (API + Renames)
  │           └── F (Frontend)
  └───────────────────────────────────┐
                                      G (Docs + Cleanup)
```

## Execution Rounds

- **Round 1:** A (no dependencies)
- **Round 2:** B (depends on A)
- **Round 3:** C (depends on A, B)
- **Round 4:** D, E (depend on C; independent of each other)
- **Round 5:** F (depends on E)
- **Round 6:** G (depends on all)

## Per-Part Scope

### Part A: Persistence Layer + Migration

Create `LibraryPipelineStatesOps` in `nomarr/persistence/database/library_pipeline_states_aql.py` mirroring the `FileStatesOperations` pattern. Implement `transition_state`, `get_state`, `get_libraries_in_state`, `bulk_transition`. Wire into `Database` class. Write V023 migration that creates `library_pipeline_states` vertex collection (10 singletons), `library_has_pipeline_state` edge collection, adds `library_auto_write: false` to all library docs, and derives initial state edges from file state counts. Unit tests for all persistence operations.

### Part B: Library Settings + Scan Lifecycle Hooks

Add `library_auto_write: bool` field to `LibraryDict` and propagate through library create/update path (persistence → components → services → interfaces). Insert initial `idle` pipeline state edge on library creation. Add scan lifecycle pipeline state transitions: `* → scanning` on scan start, `scanning → ml_running` or `scanning → idle` on scan completion. Add `on_complete` hook capability to scan ManagedTask dispatch. Tests for settings propagation and scan hook transitions.

### Part C: Pipeline Service + Calibration Trigger

Create `LibraryPipelineService` in `nomarr/services/infrastructure/pipeline_svc.py`. Implement startup recovery (recover stale `scanning`, `calibrating`, `applying`, `writing` states). Implement calibration trigger logic — bulk transitions `awaiting_calibration → calibrating`, dispatch via BTS, with DB-backed calibration guard. Wire `post_generation_hook` to transition `calibrating → applying → writing/write_ready`. Wire apply completion callback branching on `library_auto_write`. Wire write completion callback for `writing → done` + Navidrome rescan. Register in `app.py` startup lifecycle.

### Part D: Worker Idle-Path Integration

Add idle-path library completion check to `DiscoveryWorker.run()`. When worker goes idle (`discover_and_claim_file` returns None), run per-library AQL count query for `ml_running` libraries with 0 untagged files. Transition completed libraries to `too_small` or `awaiting_calibration` based on file count vs `INTERNAL_CALIBRATION_MIN_FILES`. Fire calibration trigger via `LibraryPipelineService`. Tests for idle-path detection and state transitions.

### Part E: API Endpoints + Renames

Rename `TaggingService.reconcile_library()` → `write_tags_to_files()`. Rename `ReconcileTagsResult` → `WriteTagsResult`. Rename route `/reconcile-tags` → `/write-tags`, response types accordingly. Delete `GET /{id}/reconcile-status` endpoint and `ReconcileStatusResponse`. Add `GET /{id}/pipeline` endpoint returning `PipelineStatusResponse`. Implement reactive `library_auto_write` toggle (immediate `write_ready → writing` on enable; `writing → write_ready` on disable). Create `LibraryPipelineStatusDTO`. Tests for endpoints and reactive behavior.

### Part F: Frontend + Dashboard

Update frontend API client: rename functions and routes. Add pipeline state badge to library cards. Add per-library progress indicators to dashboard (touch work-status backend path). Add `library_auto_write` toggle to library create/edit forms with confirmation dialog. Frontend tests.

### Part G: Documentation + Cleanup

Delete `INTERNAL_CALIBRATION_AUTO_RUN` and `INTERNAL_CALIBRATION_CHECK_INTERVAL` from config_svc and their re-exports. Update `PERSISTENCE.md`, `docs/dev/architecture.md`, `docs/dev/workers.md`, `docs/dev/domains.md`, `docs/dev/migrations.md`. Add user docs for pipeline automation. Final integration tests.
