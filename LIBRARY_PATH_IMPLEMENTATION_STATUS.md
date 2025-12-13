# LibraryPath Refactor - Implementation Status

## Completed ✅

### Phase 1: Core Infrastructure
- [x] Created `LibraryPath` DTO in `helpers/dto/path_dto.py`
  - Immutable frozen dataclass
  - Fields: relative, absolute, library_id, status, reason
  - Status enum: valid, invalid_config, not_found, unknown
  
- [x] Created factory functions:
  - `build_library_path_from_input(raw_path, db)` - For API/CLI inputs
  - `build_library_path_from_db(stored_path, db, library_id, check_disk)` - For database reads
  
- [x] Exported from `helpers/dto/__init__.py`

## In Progress 🚧

### Phase 2: Critical Path Fixes (Immediate Error Resolution)

#### Workers (Entry Points for Queue Processing)
- [ ] `services/infrastructure/workers/base.py`
  - `_process_job()` - Validate dequeued `job.file_path` using `build_library_path_from_db()`
  - Pass LibraryPath to processing backend
  - Handle non-valid status (mark job as error with reason)

- [ ] `services/infrastructure/workers/scanner.py`
  - `ScannerBackend.__call__(db, path: str, force)` → change to accept LibraryPath
  - Or validate internally before calling workflow

- [ ] `services/infrastructure/workers/tagger.py`
  - `TaggerBackend.__call__(db, path: str, force)` → change to accept LibraryPath
  - Or validate internally before calling workflow

#### Workflows (Core Business Logic)
- [ ] `workflows/library/scan_single_file_wf.py`
  - Replace ValidatedPath validation with LibraryPath
  - Accept LibraryPath in params DTO
  - Check `path.is_valid()` before proceeding
  - Pass LibraryPath to components

- [ ] `workflows/processing/tag_file_wf.py`
  - Update to receive and use LibraryPath
  - Check status before file operations

- [ ] `workflows/calibration/calibrate_file_wf.py`
  - Update to receive and use LibraryPath

#### Components (Filesystem Operations)
- [ ] `components/library/metadata_extraction_comp.py`
  - `extract_metadata(file_path: str)` → `extract_metadata(path: LibraryPath)`
  - Enforce `path.is_valid()` at entry
  - Use `str(path.absolute)` for file I/O

- [ ] `components/tagging/tagging_writer_comp.py`
  - `TagWriter.write(path: str, tags)` → `write(path: LibraryPath, tags)`
  - All implementations: MP3TagWriter, MP4TagWriter, VorbisTagWriter, OpusTagWriter
  - Enforce status check

- [ ] `components/tagging/tagging_reader_comp.py`
  - `read_tags_from_file(path: str)` → `read_tags_from_file(path: LibraryPath)`

- [ ] `components/tagging/tagging_remove_comp.py`
  - `remove_tags_from_file(path: str)` → `remove_tags_from_file(path: LibraryPath)`

- [ ] `components/ml/ml_audio_comp.py`
  - `load_audio_mono(path: str)` → `load_audio_mono(path: LibraryPath)`

- [ ] `components/queue/queue_enqueue_comp.py`
  - `check_file_needs_processing(db, path: str)` → `check_file_needs_processing(db, path: LibraryPath)`
  - `enqueue_file(db, path: ValidatedPath)` → `enqueue_file(db, path: LibraryPath)`
  - `enqueue_file_checked(db, path: ValidatedPath)` → `enqueue_file_checked(db, path: LibraryPath)`

## Planned 📋

### Phase 3: Persistence Layer
- [ ] `persistence/database/library_files_sql.py`
  - `upsert_library_file(path: str, ...)` → Accept LibraryPath, store relative path
  - `delete_library_file(path: str)` → Accept LibraryPath
  - `get_library_file(path: str)` → Keep as string (lookup only)

- [ ] `persistence/database/tag_queue_sql.py`
  - `enqueue(path: ValidatedPath)` → `enqueue(path: LibraryPath)`
  - Store relative path, include library_id

- [ ] `persistence/database/library_queue_sql.py`
  - `enqueue_scan(path: ValidatedPath)` → `enqueue_scan(path: LibraryPath)`
  - Store relative path, include library_id

- [ ] `persistence/database/calibration_queue_sql.py`
  - Similar updates for calibration queue

### Phase 4: DTOs (Cross-Layer Contracts)
- [ ] `helpers/dto/queue_dto.py`
  - Keep `DequeueResult.file_path: str` (read from DB)
  - Keep `Job.path: str` (for external visibility)
  - Add note that consumers must validate with factory

- [ ] `helpers/dto/library_dto.py`
  - `ScanSingleFileWorkflowParams.file_path: str` → Keep for now, validate in workflow
  - Consider adding `LibraryPathWorkflowParams` variant

- [ ] `helpers/dto/calibration_dto.py`
  - Similar considerations

- [ ] `helpers/dto/ml_dto.py`
  - `ProcessFileParams.path: str` → Consider LibraryPath

### Phase 5: Services (API Boundary)
- [ ] `services/domain/library_svc.py`
  - Methods accepting file paths from API
  - Validate using `build_library_path_from_input()`
  - Pass LibraryPath to workflows

- [ ] `services/domain/processing_svc.py`
  - Enqueue methods validate paths before enqueueing

- [ ] `services/domain/queue_svc.py`
  - Validate paths from API before database operations

### Phase 6: Interfaces (External Boundary)
- [ ] `interfaces/api/routes/library_routes.py`
  - Validate file paths from requests early

- [ ] `interfaces/api/routes/queue_routes.py`
  - Validate enqueue requests

- [ ] `interfaces/cli/main.py`
  - Validate CLI path arguments

### Phase 7: Reconciliation Workflow
- [ ] Create `workflows/library/reconcile_library_paths_wf.py`
  - Scan library_files table in batches
  - Re-validate each path against current config
  - Mark/delete invalid paths based on policy
  - Log detailed diagnostics
  
- [ ] Add service method to trigger reconciliation
- [ ] Add API endpoint for admin to trigger
- [ ] Consider automatic reconciliation on config change

### Phase 8: Database Schema Considerations
- [ ] Review library_files table
  - Currently stores absolute paths
  - Consider storing relative + library_id for portability
  - Migration strategy for pre-alpha

- [ ] Review queue tables
  - Add library_id column for faster lookups
  - Store relative paths

## Testing Strategy 🧪

- [ ] Unit tests for LibraryPath factory functions
  - Valid paths
  - Invalid paths (outside library)
  - Non-existent paths
  - Config changes

- [ ] Integration tests for workflows
  - End-to-end with LibraryPath
  - Status handling

- [ ] Worker tests
  - Dequeue and validate
  - Handle invalid paths from DB

- [ ] Reconciliation workflow tests
  - Detect invalid paths after config change
  - Clean up orphaned entries

## Risk Mitigation 🛡️

### High Risk Areas
1. **Worker system**: Multiprocessing pickle concerns with LibraryPath
   - Mitigation: LibraryPath is frozen dataclass (pickle-safe)
   
2. **Database layer**: Many callers, breaking changes
   - Mitigation: Update systematically, use mypy to catch issues

3. **Existing queue data**: Paths in queue tables are strings
   - Mitigation: Workers validate on dequeue, handle gracefully

### Rollback Plan
- Pre-alpha: Can break schemas and APIs
- If issues arise: Fix forward rather than rollback
- Document breaking changes for users

## Success Criteria ✨

- [ ] No raw strings passed to filesystem operations without LibraryPath
- [ ] Workers validate paths from queue before processing
- [ ] Filesystem components enforce `path.is_valid()` check
- [ ] Persistence layer only accepts LibraryPath for writes
- [ ] Mypy passes without str → LibraryPath errors
- [ ] All tests pass
- [ ] Clear error messages when paths become invalid
- [ ] Reconciliation workflow cleanly handles config changes

## Implementation Order

1. ✅ Core DTO and factories
2. 🚧 Workers (immediate error fix)
3. 🚧 Critical workflows (scan_single_file, tag_file)
4. 🚧 Filesystem components
5. 📋 Queue components
6. 📋 Persistence writes
7. 📋 Services and interfaces
8. 📋 Reconciliation workflow
9. 📋 Testing and validation

## Notes

- Keep external DTOs (API responses, events) as strings for now
- Focus on internal type safety first
- Pre-alpha: No backward compatibility needed
- Can break and fix forward
