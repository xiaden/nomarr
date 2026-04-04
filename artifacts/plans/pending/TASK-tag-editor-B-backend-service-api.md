# Task: Backend Service Expansion & API Endpoints for Tag Curation

## Problem Statement

With persistence primitives and DTOs in place (Plan A), the tag curation tool needs service-layer orchestration and HTTP endpoints. This plan expands `TaggingService` to be the single vertical slice for the tags domain (ADR-013): adding curation operations (rename, merge, split, single-song edit), query methods for the UI, commit operations for deferred file writeback, and `nom:` prefix enforcement (ADR-009). It migrates tag query methods from `LibraryService` to `TaggingService` and updates all callers. Finally, it creates new API endpoints for curation, queries, and commit.

**Prerequisite:** TASK-tag-editor-A-backend-persistence

## Phases

### Phase 1: Expand TaggingService
- [x] Add curation methods to `TaggingService` in `nomarr/services/domain/tagging_svc.py`: `rename_tag(tag_id, new_value) -> RenameResult`, `merge_tags(source_tag_ids, canonical_tag_id) -> MergeResult`, `split_tag(source_tag_id, song_ids, new_value) -> SplitResult`, `update_file_tags(file_id, rel, values) -> dict`. Each method: (1) validates `nom:` prefix rejection with `ValueError`, (2) calls persistence primitives (`relink_tag_edges`, `find_or_create_tag`, `set_song_tags`), (3) sets affected files to `tags_not_written` via `self.db.file_states.set_tags_not_written(file_id)`.
    **executor:** Added rename_tag, merge_tags, split_tag, update_file_tags with nom: prefix rejection via _reject_nom_prefix static helper. Each calls persistence primitives and sets tags_not_written state.
- [x] Add query methods to `TaggingService`: `list_tag_values(rel, prefix, limit, offset) -> TagListResult` wrapping `self.db.tags.list_tags_by_rel` + `count_tags_by_rel`; `get_tag_songs(tag_id, limit, offset) -> dict` wrapping `self.db.tags.get_tag_songs_with_metadata` + `count_songs_for_tag`.
    **executor:** Added list_tag_values wrapping list_tags_by_rel+count_tags_by_rel, and get_tag_songs wrapping get_tag_songs_with_metadata+count_songs_for_tag.
- [x] Add commit methods to `TaggingService`: `get_pending_commit_count() -> int` wrapping `self.db.file_states.count_pending_tag_writes()`; `commit_pending_tags(library_id=None) -> CommitResult` delegating to existing `self.reconcile_library()` for files in `tags_not_written` state.
    **executor:** Added get_pending_commit_count wrapping count_pending_tag_writes, and commit_pending_tags iterating libraries via reconcile_library.
- [x] Add migrated tag query methods to `TaggingService`: `get_unique_tag_keys(nomarr_only=False)`, `get_unique_tag_values(tag_key, nomarr_only=False)`, `get_unique_mood_values(mood_tier, limit)`, `get_file_tags(file_id, nomarr_only=False)`, `cleanup_orphaned_tags(dry_run=False)`, `search_files_by_tag(tag_key, target_value, limit, offset)`. Each wraps the same component/persistence calls that `LibraryService` currently uses. Keep return types compatible with existing DTOs (`UniqueTagKeysResult`, `TagCleanupResult`, `FileTagsResult`, `SearchFilesResult`). Note actual call chains: `cleanup_orphaned_tags` delegates to `cleanup_orphaned_tags_workflow` at `nomarr/workflows/library/cleanup_orphaned_tags_wf.py` (not a component directly); `get_file_tags` calls `get_file_tags_with_path` component at `nomarr/components/library/file_tags_comp.py`. Mirror these exact delegation patterns in the new `TaggingService` methods.
    **executor:** Added 6 migrated methods mirroring LibraryService patterns: get_unique_tag_keys/values via component, cleanup_orphaned_tags via workflow, get_file_tags via component, search_files_by_tag via db.library_files.
- [x] Update `library_if.py` callers: change 6 endpoints (`search_files_by_tag`, `get_unique_tag_keys`, `get_unique_tag_values`, `get_unique_mood_values`, `cleanup_orphaned_tags`, `get_file_tags`) to inject `tagging_service` via `Depends(get_tagging_service)` instead of using `library_service`. Update method calls accordingly.
    **executor:** Changed 6 endpoints in library_if.py to inject tagging_service via Depends(get_tagging_service). get_tagging_service was already imported. TaggingService TYPE_CHECKING import already present.
- [x] Update `MetadataService` caller: `nomarr/services/domain/metadata_svc.py` line ~265 calls `self.db.tags.cleanup_orphaned_tags()` at the persistence level. Review whether this should delegate to `TaggingService.cleanup_orphaned_tags()` or remain as a direct persistence call. Also update the CLI path at `nomarr/interfaces/cli/commands/cleanup_cli.py` line ~31 which flows through `MetadataService`. Ensure both callers are consistent with the new canonical owner (`TaggingService`).
    **executor:** Reviewed MetadataService and CLI callers. MetadataService.cleanup_orphaned_entities uses direct persistence call (self.db.tags.cleanup_orphaned_tags) for tag cleanup as side effect of entity cleanup. CLI only calls entity cleanup. Decision: keep as-is to avoid lateral service dependency. Logged as observation L12.
- [x] Verify `lint_project_backend` passes on `nomarr/services/domain/tagging_svc.py` and `nomarr/interfaces/api/web/library_if.py`
    **executor:** Both files pass lint with zero errors (ruff + mypy clean).

### Phase 2: New API Endpoints
- [x] Create `nomarr/interfaces/api/web/tag_curation_if.py` with `APIRouter(prefix="/tag-curation", tags=["Tag Curation"])`. Add curation endpoints: `POST /rename` (body: `{tag_id, new_value}`), `POST /merge` (body: `{source_tag_ids, canonical_tag_id}`), `POST /split` (body: `{source_tag_id, song_ids, new_value}`). Each calls corresponding `TaggingService` method via `Depends(get_tagging_service)`. All require `Depends(verify_session)`.
    **executor:** Created tag_curation_if.py with APIRouter(prefix="/tag-curation", tags=["Tag Curation"]) and 3 POST curation endpoints: /rename, /merge, /split. Each uses asyncio.to_thread, Depends(verify_session), Pydantic request models, and ValueError->400 error handling for nom: prefix rejection.
- [x] Add query endpoints to `tag_curation_if.py`: `GET /values` (query params: `rel`, `prefix`, `limit`, `offset`) and `GET /{tag_id}/songs` (query params: `limit`, `offset`). Both call `TaggingService` query methods.
    **executor:** Added GET /values (rel, prefix, limit, offset query params) and GET /{tag_id}/songs (limit, offset query params). Both use asyncio.to_thread and return dict responses matching TagListResult and {songs, total} contracts.
- [x] Add commit endpoints to `tag_curation_if.py`: `POST /commit` (body: `{library_id?}`) and `GET /pending-count`. Add single-song edit endpoint: `PATCH /files/{file_id}/tags` (body: `{rel, values}`) — this can go on the existing library router or the new tag-curation router.
    **executor:** Added POST /commit (body: {library_id?}), GET /pending-count (returns {count}), and PATCH /files/{file_id}/tags (body: {rel, values}) on tag-curation router for cohesion. Uses decode_path_id for file_id URL parameter.
- [x] Register `tag_curation_if.router` in `nomarr/interfaces/api/web/router.py` alongside existing routers
    **executor:** Registered tag_curation_if.router in router.py alongside existing routers (alphabetical order between processing and tags).
- [x] Verify `lint_project_backend` passes on all new and modified interface files
    **executor:** Both tag_curation_if.py and router.py pass lint_project_backend with zero errors (ruff + mypy clean).

## Completion Criteria
- `TaggingService` has all curation methods (rename, merge, split, update_file_tags) with `nom:` enforcement
- `TaggingService` has query/commit methods (list_tag_values, get_tag_songs, get_pending_commit_count, commit_pending_tags)
- 6 migrated methods exist on `TaggingService` and `library_if.py` endpoints call them via `tagging_service`
- All 8 new API endpoints respond correctly (curation: 3, query: 2, commit: 2, single-song: 1)
- New router registered and all endpoints reachable under `/api/web/tag-curation/`
- `lint_project_backend` passes with zero errors

## References
- Design doc: `artifacts/designs/pending/DD-tag-editor.md`
- ADR-009: `nom:` prefix exclusion (three-layer guard)
- ADR-013: TaggingService as vertical slice
- ADR-008: Two-phase curation→commit
- Contracts: `artifacts/designs/parts/tag-editor/CONTRACTS.md`
- Prerequisite: `artifacts/plans/pending/TASK-tag-editor-A-backend-persistence.md`
