# Task: Errored File Listing and Recovery

**Prerequisite:** TASK-file-state-graph-F-wire-vectors-errored-axes

## Problem Statement

The `errored` axis blocks discovery — files that fail ML processing are quarantined via `set_errored()` and excluded by `discover_next_untagged_file()`. But there is no way to see which files are errored, no way to clear the errored state for retry, and no way to scope this per-library or per-file. Without a recovery path, errored files are permanently stuck.

This plan adds:
1. Persistence methods to list and count errored files per library
2. Service methods to query errored files and retry (clear errored + re-queue for tagging)
3. DTOs for the API response shapes
4. Two REST endpoints: GET errored files list, POST retry errored
5. Frontend API wrappers (UI deferred — API-first)

## Phases

### Phase 1: Persistence — errored file queries
- [x] Add `get_errored_file_ids(library_id: str, limit: int = 500) -> list[str]` to `FileStatesOperations` in `file_states_aql.py`, following the `get_untagged_file_ids` pattern (OUTBOUND library_contains_file for scoping, INBOUND STATE_ERRORED traversal, set intersection)
    **executor:** Added get_errored_file_ids(library_id, limit=500) after count_uncalibrated_files. Uses OUTBOUND library_contains_file + INBOUND STATE_ERRORED edge filter pattern. library_id param is a key, CONCATs to full _id in bind vars.
- [x] Add `count_errored_files(library_id: str) -> int` to `FileStatesOperations` in `file_states_aql.py`, following the `count_untagged_files` pattern (INBOUND STATE_ERRORED, LET/LENGTH wrapper)
    **executor:** Added count_errored_files(library_id) using LET/LENGTH wrapper pattern from count_untagged_files. Same library scoping and bind var approach as get_errored_file_ids.
- [x] Run `lint_project_backend` on `nomarr/persistence/database/file_states_aql.py` to verify no type or import errors
    **executor:** lint_project_backend passed with 0 errors on file_states_aql.py.

### Phase 2: DTOs and service layer
- [x] Add `ErroredFileItem` TypedDict to `nomarr/helpers/dto/library_dto.py` with fields: `_id: str`, `path: str`, `duration_seconds: float | None`, `artist: str | None`, `title: str | None`
    **executor:** Added ErroredFileItem TypedDict with _id, path, duration_seconds, artist, title fields.
- [x] Add `ErroredFilesResult` TypedDict to `nomarr/helpers/dto/library_dto.py` with fields: `files: list[ErroredFileItem]`, `total: int`
    **executor:** Added ErroredFilesResult TypedDict with files and total fields.
- [x] Add `RetryErroredResult` TypedDict to `nomarr/helpers/dto/library_dto.py` with fields: `retried: int`
    **executor:** Added RetryErroredResult TypedDict with retried field.
- [x] Add `get_errored_files(library_id: str) -> ErroredFilesResult` to `LibraryQueryMixin` in `nomarr/services/domain/library_svc/query.py` — calls `_get_library_or_error`, then `db.file_states.get_errored_file_ids(library_id)`, then `db.library_files.get_files_by_ids(file_ids)` to hydrate metadata, returns `ErroredFilesResult`
    **executor:** Added get_errored_files to LibraryQueryMixin. Uses get_files_by_ids_with_tags (not get_files_by_ids which doesnt exist on persistence). Maps raw dicts to ErroredFileItem TypedDicts. Uses count_errored_files for real total.
- [x] Add `retry_errored_files(library_id: str, file_ids: list[str] | None = None) -> RetryErroredResult` to `LibraryFilesMixin` in `nomarr/services/domain/library_svc/files.py` — calls `_get_library_or_error`, gets errored IDs (all or filtered to provided `file_ids`), calls `db.file_states.bulk_set_not_errored(ids)` then `db.file_states.clear_tagged_batch(ids)` to re-queue, returns `RetryErroredResult`
    **executor:** Added retry_errored_files to LibraryFilesMixin. Clears errored state via bulk_set_not_errored then clears tagged state via clear_tagged_batch to re-queue for discovery. Supports optional file_ids filter.
- [x] Update `__all__` in `nomarr/helpers/dto/library_dto.py` to export the 3 new DTOs
    **executor:** Exported ErroredFileItem, ErroredFilesResult, RetryErroredResult in __all__.
- [x] Run `lint_project_backend` on changed files
    **executor:** lint_project_backend passed with 0 errors on all 3 changed files. Added _get_library_or_error to both query.py and files.py mixins (matching scan.py pattern) to fix mypy attr-defined errors.

### Phase 3: API endpoints
- [x] Add `GET /{library_id}/errored-files` endpoint to `nomarr/interfaces/api/web/library_if.py` — depends on `verify_session`, calls `library_service.get_errored_files(library_id)`, returns Pydantic response model `ErroredFilesResponse` (mirrors `ErroredFilesResult`), follows `validate_library_tags` error handling pattern
    **executor:** Added GET /{library_id}/errored-files endpoint. Uses validate_library_tags pattern: decode_path_id, Depends(verify_session), ValueError->404, Exception->500. Pydantic models (ErroredFileItemResponse, ErroredFilesResponse) added to library_types.py.
- [x] Add `POST /{library_id}/retry-errored` endpoint to `nomarr/interfaces/api/web/library_if.py` — depends on `verify_session`, accepts optional JSON body `{"file_ids": ["..."]}`  via Pydantic model `RetryErroredRequest(file_ids: list[str] | None = None)`, calls `library_service.retry_errored_files(library_id, file_ids)`, returns `RetryErroredResponse(retried: int)`
    **executor:** Added POST /{library_id}/retry-errored endpoint. Accepts optional RetryErroredRequest body with file_ids. Returns RetryErroredResponse(retried=int). Same error handling pattern as validate_library_tags.
- [x] Run `lint_project_backend` on `nomarr/interfaces/api/web/library_if.py`
    **executor:** lint_project_backend passed with 0 errors on both library_if.py and library_types.py.

### Phase 4: Frontend API wrappers
- [x] Add `ErroredFileItem` and `ErroredFilesResult` interfaces to `frontend/src/shared/api/library.ts`
    **executor:** Added ErroredFileItem and ErroredFilesResult interfaces with snake_case fields matching backend response shape.
- [x] Add `getErroredFiles(libraryId: string): Promise<ErroredFilesResult>` function — calls `GET /api/web/libraries/${libraryId}/errored-files`
    **executor:** Added getErroredFiles(libraryId) calling GET /api/web/libraries/${libraryId}/errored-files, returns ErroredFilesResult.
- [x] Add `RetryErroredResult` interface and `retryErroredFiles(libraryId: string, fileIds?: string[]): Promise<RetryErroredResult>` function — calls `POST /api/web/libraries/${libraryId}/retry-errored` with optional body
    **executor:** Added RetryErroredResult interface and retryErroredFiles(libraryId, fileIds?) calling POST /api/web/libraries/${libraryId}/retry-errored with optional {file_ids} body.
- [x] Run frontend lint (`cd frontend && npx eslint src/shared/api/library.ts`)
    **executor:** lint_project_frontend: ESLint passed with 0 errors. 1 pre-existing TS5103 error in tsconfig.app.json (ignoreDeprecations config) unrelated to changes.

## Completion Criteria
- `get_errored_file_ids` and `count_errored_files` exist on `FileStatesOperations` with library scoping
- `get_errored_files` and `retry_errored_files` exist on `LibraryService`
- `GET /{library_id}/errored-files` returns errored file list with metadata
- `POST /{library_id}/retry-errored` clears errored state and re-queues files (sets not_errored + not_tagged)
- Selective retry via `file_ids` body parameter works
- `lint_project_backend` passes on all changed backend files
- Frontend lint passes on `library.ts`
- All new DTOs exported from `library_dto.py`

## References
- Prior plans: TASK-file-state-graph-A through F
- Design doc: `artifacts/designs/pending/DD-file-state-graph-completion.md`
- Contracts: `artifacts/designs/parts/file-state-graph/CONTRACTS.md`
- Pattern reference: `validate_library_tags` endpoint + `get_untagged_file_ids` persistence method
