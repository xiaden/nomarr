# Library Workflows

Workflows for library scanning, file synchronization, tag I/O, path reconciliation, orphaned tag cleanup, and tag validation.

## Responsibilities

- Full and incremental library scanning with folder-level caching
- Pre-scan validation and status management
- File-to-library synchronization (metadata + tags + entity graph)
- Audio file tag reading and removal
- Path reconciliation after configuration changes
- Orphaned tag cleanup and tag completeness validation

## Key Modules

 | Module | Purpose |
 | -------- | --------- |
 | `scan_library_full_wf.py` | Full scan — walks every folder ignoring cache, re-examines all files |
 | `scan_library_quick_wf.py` | Quick (incremental) scan — skips unchanged folders via mtime/file_count cache |
 | `scan_setup_wf.py` | Pre-scan validation — checks library exists, not already scanning; runs synchronously before dispatch |
 | `sync_file_to_library_wf.py` | Canonical file sync — upserts `library_files`, parses tags, seeds entity graph, rebuilds cache |
 | `file_tags_io_wf.py` | Read/remove namespaced tags from audio files on disk |
 | `reconcile_paths_wf.py` | Re-validate all library paths after config changes (mark/delete invalid) |
 | `cleanup_orphaned_tags_wf.py` | Remove orphaned tags with no file edges |
 | `validate_library_tags_wf.py` | Verify tag completeness for all ML heads; optionally mark incomplete files for re-tagging |

## Patterns

- **Scan dispatch**: Setup runs synchronously (catchable errors), actual scan dispatched as background task
- **Move detection**: Full scan detects moved files via content fingerprint before creating new records
- **Fast-path sync**: When `file_id` is known, `sync_file_to_library_wf` skips path-based upsert

## Architecture Rules

> **Workflows MUST NOT call persistence directly.** Workflows receive `Database` and pass it to components (`components/library/*`, `components/tagging/*`, `components/metadata/*`).

## Dependencies

- **Called by**: `services/domain/library_svc/` (scan, files, admin mixins)
- **Calls**: `components/library/*` (scanning, sync, metadata extraction), `components/tagging/*` (tag parsing), `components/metadata/*` (entity seeding, cache)
- **Receives**: `Database`, library_id, tagger_version, namespace
