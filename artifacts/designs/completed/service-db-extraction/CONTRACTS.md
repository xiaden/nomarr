# Service DB Extraction — Contracts Ledger

**Design Document:** [DD-service-db-extraction-scan-filewatcher](../../pending/DD-service-db-extraction-scan-filewatcher.md)

---

## Architectural Rules

- **ADR-003**: No thin pass-through wrappers. Each component function must add value (projection, aggregation, error handling, or domain logic).
- **ADR-004**: Scan metadata in `library_scans` model; pipeline state is authority for active scanning.
- **ADR-013**: Push domain logic to components, not LibraryService growth.
- Services may hold `db: Database` and pass to components — the rule is "no direct `db.collection.*` calls in services."

---

## Collections & Methods

### Plan A: scan_lifecycle_comp additions

 | Method | Signature | Purpose |
 | -------- | ----------- | -------- |
 | `get_scanning_library_ids` | `(db: Database) -> set[str]` | Return set of library IDs in PIPELINE_SCANNING state |
 | `get_library_scan_histories` | `(db: Database, limit: int \ | None = None) -> list[dict[str, Any]]` | Return scan history records for all libraries (including disabled) |

### Plan B: library_watch_config_comp (NEW file)

 | Method | Signature | Purpose |
 | -------- | ----------- | -------- |
 | `list_watchable_libraries` | `(db: Database) -> list[dict[str, Any]]` | Return libraries eligible for watching: `{_id, root_path, watch_mode}` projection |
 | `get_library_watch_config` | `(db: Database, library_id: str) -> dict[str, Any] \ | None` | Return `{root_path, watch_mode, is_enabled}` projection for one library |

### Plan B: pipeline_svc.recover_stale_states extension

 | Change | Detail |
 | -------- | -------- |
 | Absorbed responsibility | For each stale-scanning library, also call `db.libraries.update_scan_status(library_id, status="idle", error="Scan interrupted by server restart")` |
 | Return shape | Unchanged: `dict[str, int]` — metadata reset folds into existing `scanning` counter |

### Plan C: UpdateLibraryMetadataComp usage

 | Usage | Detail |
 | ------- | -------- |
 | `UpdateLibraryMetadataComp(self._db).update(library_id, watch_mode=new_mode)` | Replaces `db.libraries.update_library(library_id, watch_mode=new_mode)` in `switch_watch_mode` |

---

## DTOs

No new DTOs. `LibraryScanStatusResult` assembly remains inline in `get_status()`.

---

## Decisions

- `resolve_library_for_scan` already exists in `scan_lifecycle_comp` — reuse, don't duplicate
- `self.db` → `self._db` rename deferred to Plan C (atomic with rewiring)
- Constructor signature of `FileWatcherService` is unchanged (20 test + 1 production call sites preserved)
- `update_watch_mode` routes through existing `UpdateLibraryMetadataComp.update()`, not a new function
