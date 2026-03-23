# Library Files AQL Operations

Mixin-based split of `LibraryFilesOperations` — the largest query class, covering CRUD, search, statistics, tagging status, reconciliation, calibration, chromaprint, and track metadata.

## Responsibilities

- Provide all AQL operations for the `library_files` collection
- Split into focused mixins to keep each module under 300 lines
- Compose into a single `LibraryFilesOperations` class via mixin inheritance

## Key Modules

| Module | Purpose |
|--------|--------|
| `crud.py` | `LibraryFilesCrudMixin` — upsert, delete, batch upsert, path update, bulk delete |
| `queries.py` | `LibraryFilesQueriesMixin` — get by ID/path, search with tags, folder queries, recently processed |
| `stats.py` | `LibraryFilesStatsMixin` — library statistics, artist/album frequencies, tag-based search |
| `status.py` | `LibraryFilesStatusMixin` — ML tagging state via edge-based `file_has_state` |
| `reconciliation.py` | `LibraryFilesReconciliationMixin` — claim-based tag reconciliation with lease locking |
| `calibration.py` | `LibraryFilesCalibrationMixin` — calibration hash management via `file_has_state` edges |
| `chromaprint.py` | `LibraryFilesChromaprintMixin` — audio fingerprint storage and lookup (move detection) |
| `tracks.py` | `LibraryFilesTracksMixin` — track metadata fetch for playlists and matching |

## Patterns

- **Mixin composition**: Each file defines one mixin class; the parent `LibraryFilesOperations` inherits all mixins
- **Edge-based state**: Tagging, calibration, and reconciliation state tracked via `file_has_state` edges (not flat fields)
- **Normalized paths**: File identity uses POSIX-style `normalized_path` relative to library root

## Access Rule

**Only components may import these modules.** Services, workflows, interfaces, and helpers must not access persistence directly.
