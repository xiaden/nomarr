# Library Components

File and library management — scanning, syncing, metadata extraction, move detection, and search.

## Responsibilities

- Library CRUD (create, update, delete) with root path validation and overlap prevention
- Folder discovery and incremental scan planning (mtime + file count change detection)
- Batch file scanning with metadata extraction and chromaprint fingerprinting
- Missing file detection and move detection (chromaprint-based)
- File tag storage and search with filtering
- Scan lifecycle management (start, progress, complete, interrupt recovery)
- Path reconciliation after library root changes

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `library_admin_comp` | Library create/update/delete with name generation and validation |
 | `library_root_comp` | Root path normalization, security boundary checks, overlap prevention |
 | `list_libraries_comp` | List libraries with optional enabled-only filtering |
 | `update_library_metadata_comp` | Update library metadata fields (name, enabled, watch mode, write mode) |
 | `folder_analysis_comp` | Discover folders with audio files, plan incremental vs full scans |
 | `file_batch_scanner_comp` | Scan a single folder: enumerate files, extract metadata, build upsert entries |
 | `scan_lifecycle_comp` | Scan start/complete marks, progress updates, file upserts, folder cache, interrupt detection |
 | `validate_scan_state_comp` | Heal edge state for unchanged files (e.g., short files without ml_tagged edge) |
 | `file_sync_comp` | Single-file operations: upsert, get, mark tagged, save tags, set chromaprint |
 | `file_library_comp` | Look up which library owns a given file |
 | `file_tags_comp` | Retrieve all tags for a file with optional Nomarr-only filtering |
 | `metadata_extraction_comp` | Extract metadata from audio files (mutagen-based: MP3/MP4/FLAC), resolve artists, compute chromaprints |
 | `missing_file_detection_comp` | Folder-aware detection of files removed from disk (respects skipped folders) |
 | `move_detection_comp` | Chromaprint-based move detection with duration pre-filter and early termination |
 | `reconcile_paths_comp` | Re-validate all library paths after config changes (dry-run, mark-invalid, or delete) |
 | `search_files_comp` | Search library files with filtering; list unique tag keys/values |
 | `tag_cleanup_comp` | Remove orphaned tags not referenced by any song |
 | `work_status_comp` | Compute unified work status (scanning progress, tagging velocity) |

## Patterns

- **Incremental scanning:** `folder_analysis_comp` compares folder mtime and file count against a DB cache to skip unchanged folders, making re-scans fast.
- **Move detection:** When files disappear and new files appear, chromaprints are compared. Duration pre-filtering and early termination optimize the matching.
- **Batch upserts:** `scan_lifecycle_comp.upsert_scanned_files` writes files in bulk AQL operations, with optional edge bootstrapping for files that should skip ML processing.
- **Security boundary:** All library roots must be nested under a configured `base_library_root`. Path traversal is prevented by `library_root_comp`.

## Dependencies

- **Upstream:** Called by `workflows/` (scan workflow, file write workflow) and `services/`
- **Downstream:** Calls `persistence/` directly for all DB operations
- **External:** `mutagen` (metadata extraction), `pathlib`
