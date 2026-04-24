# Service DB Extraction — Implementation Plans

**Design Document:** [DD-service-db-extraction-scan-filewatcher](../../pending/DD-service-db-extraction-scan-filewatcher.md)

## Plans

 | Plan | Title | Steps | Dependencies |
 | ------ | ------- | ------- | -------------- |
 | A | scan.py DB Extraction | 12 | None |
 | B | Pipeline Recovery Absorption + Watch Config Component | 9 | None |
 | C | file_watcher_svc DB Extraction | 10 | B |

## Dependency Graph

```
A (scan.py extraction) ──────────────────────────────────→ DONE

B (pipeline recovery + watch config comp) ──→ C (file_watcher_svc rewiring) → DONE
```

## Execution Rounds

Round 1: A, B (no mutual dependencies — parallelizable)
Round 2: C (depends on B for library_watch_config_comp + pipeline_svc recovery)

## Per-Part Scope

### Part A: scan.py DB Extraction

Add `get_scanning_library_ids` and `get_library_scan_histories` to `scan_lifecycle_comp.py`. Delete dead code (`_has_healthy_library_workers`, `_is_scan_running` + 2 unit tests). Replace `_get_library_or_error` with `resolve_library_for_scan`. Rewire `get_status` and `get_scan_history` to use component functions. Zero `self.db.*` calls remain in scan.py.

### Part B: Pipeline Recovery Absorption + Watch Config Component

Create `library_watch_config_comp.py` with 2 read-only functions (`list_watchable_libraries`, `get_library_watch_config`). Absorb `_reset_stale_scan_statuses` logic from file_watcher_svc into `pipeline_svc.recover_stale_states()`. Delete `_reset_stale_scan_statuses` method and its test class. Must complete BEFORE Plan C removes DB calls from file_watcher_svc.

### Part C: file_watcher_svc DB Extraction

Rename `self.db` to `self._db`. Replace all 5 remaining `db.libraries.*` calls with component function calls (`library_watch_config_comp` for reads, `UpdateLibraryMetadataComp` for writes). Add benign-race comment. Create unit tests for new component. Zero `db.collection.*` calls remain in file_watcher_svc.

## Notes

- Plans A and B both add exports to `library/__init__.py` — if executed in parallel, the second to merge resolves the additive conflict
- Phase ordering constraint: stale recovery must be absorbed into pipeline_svc (Plan B) BEFORE DB calls are removed from file_watcher_svc (Plan C)
- `self.db` → `self._db` rename in file_watcher_svc is in Plan C to keep the rename + rewiring atomic
