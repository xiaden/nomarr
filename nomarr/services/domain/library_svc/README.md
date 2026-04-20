# Library Service

Composite service for library management, assembled from focused mixins. Handles library CRUD, scanning, querying, file operations, and entity navigation.

## Responsibilities

- Library administration (create, update, delete, configuration)
- Scan lifecycle (quick/full scan dispatch, status, cancellation, history)
- File search, tag discovery, and statistics
- File-level tag operations and path reconciliation
- Per-library vector config management

## Key Modules

 | Module | Purpose |
 | -------- | --------- |
 | `__init__.py` | Exports `LibraryService` and `LibraryServiceConfig` |
 | `admin.py` | `LibraryAdminMixin` — library CRUD, clear data, vector config, worker health checks |
 | `config.py` | `LibraryServiceConfig` dataclass — namespace, tagger_version, library_root |
 | `entities.py` | `LibraryEntitiesMixin` — entity navigation (placeholder) |
 | `files.py` | `LibraryFilesMixin` — file tags, reconciliation, path resolution, tag cleanup |
 | `query.py` | `LibraryQueryMixin` — stats, search, tag keys/values, work status, recently processed |
 | `scan.py` | `LibraryScanMixin` — quick/full scan dispatch, status, history, cancellation, validation |

## Patterns

- **Mixin composition**: `LibraryService` inherits from 5 mixins, each in its own module
- **Background dispatch**: Scans validate synchronously then dispatch via `BackgroundTaskService`
- **Scan status**: Uses `library.scan_status` field on the library document, not queue jobs

## Architecture Rules

> **Services MUST NOT call persistence directly.** Scan operations delegate to `workflows/library/*`, file operations delegate to components.

## Dependencies

- **Called by**: `interfaces/api/web/` endpoints, `NavidromeService`, `TaggingService`
- **Calls**: `workflows/library/*` (scan, reconcile, tags I/O), `components/library/*` (search, stats)
- **Receives**: `Database`, `LibraryServiceConfig`, `BackgroundTaskService`
