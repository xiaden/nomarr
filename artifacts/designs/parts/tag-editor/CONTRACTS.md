# Tag Editor (Tag Curation Tool) — Contracts Ledger

**Design doc:** `artifacts/designs/pending/DD-tag-editor.md`
**Parts:** `artifacts/designs/parts/tag-editor/README.md`
**Last updated:** 2026-04-04 (initial)

---

## Architectural Rules

- Dependency direction: interfaces → services → workflows → components → persistence/helpers
- TaggingService is the single vertical slice for tags domain (ADR-013): ML calibration + curation + tag queries
- `nom:` prefix tags are read-only for users — enforce at service layer with ValueError (ADR-009)
- Curation operations are DB-only; file writeback is deferred via `tags_not_written` state (ADR-008)
- `relink_tag_edges` is the single persistence primitive for rename/merge/split (ADR-014)
- Server-side pagination for both tag value list and song drill-down (ADR-012)
- MUI DataGrid inline cell editing for rename (ADR-011)
- Cross-page selection via `Set<string>` client-side (ADR-015)
- All Python code must pass `lint_project_backend` with zero errors

---

## Collections & Methods

### `tags_aql/curation.py` — TagCurationMixin (Plan A)

| Method | Signature | Notes | Plan |
|--------|-----------|-------|------|
| `relink_tag_edges` | `(self, source_tag_id: str, target_tag_id: str, song_ids: list[str] \| None = None) -> RelinkResult` | 2-3 AQL round trips. UPSERT edges, REMOVE old, cleanup orphans. | A |

### `tags_aql/queries.py` — Enhanced TagQueriesMixin (Plan A)

| Method | Signature | Notes | Plan |
|--------|-----------|-------|------|
| `list_tags_by_rel` | `(self, rel: str \| None = None, limit=100, offset=0, search=None, sort_by_count=False) -> list[dict]` | Enhanced: `rel=None` returns cross-rel listing | A |
| `count_tags_by_rel` | `(self, rel: str \| None = None, search=None) -> int` | Enhanced: `rel=None` counts cross-rel | A |
| `get_tag_songs_with_metadata` | `(self, tag_id: str, limit=50, offset=0) -> list[dict]` | Returns `{file_id, title, artist, album, path}` | A |

### `file_states_aql.py` — FileStatesOperations (Plan A)

| Method | Signature | Notes | Plan |
|--------|-----------|-------|------|
| `count_pending_tag_writes` | `(self) -> int` | INBOUND traversal on `tags_not_written` vertex. O(1) discovery per ADR-003. | A |
| `get_pending_tag_write_file_ids` | `(self, limit: int = 100) -> list[str]` | For commit: discover files needing writeback | A |

---

## DTOs (Plan A)

### `helpers/dto/tag_curation_dto.py`

| DTO | Fields | Plan |
|-----|--------|------|
| `RelinkResult` | `moved: int, skipped: int, source_orphaned: bool` | A |
| `TagValueItem` | `id: str, rel: str, value: str, song_count: int` | A |
| `TagListResult` | `tags: list[TagValueItem], total: int` | A |
| `RenameResult` | `moved: int, merged_into_existing: bool` | A |
| `MergeResult` | `total_moved: int, sources_removed: int` | A |
| `SplitResult` | `moved: int, new_tag_created: bool` | A |
| `CommitResult` | `started: bool, pending_files: int` | A |
| `TagSongItem` | `file_id: str, title: str, artist: str, album: str` | A |

---

## API Contracts (Plan B)

### `tag_curation_if.py` — New Router

| Endpoint | Method | Body / Params | Response | Plan |
|----------|--------|--------------|----------|------|
| `/api/web/tag-curation/values` | GET | `?rel=genre&prefix=roc&limit=100&offset=0` | `TagListResult` | B |
| `/api/web/tag-curation/{tag_id}/songs` | GET | `?limit=50&offset=0` | `{songs: list[TagSongItem], total: int}` | B |
| `/api/web/tag-curation/rename` | POST | `{tag_id, new_value}` | `RenameResult` | B |
| `/api/web/tag-curation/merge` | POST | `{source_tag_ids, canonical_tag_id}` | `MergeResult` | B |
| `/api/web/tag-curation/split` | POST | `{source_tag_id, song_ids, new_value}` | `SplitResult` | B |
| `/api/web/tag-curation/commit` | POST | `{library_id?}` | `CommitResult` | B |
| `/api/web/tag-curation/pending-count` | GET | — | `{count: int}` | B |
| `/api/web/tag-curation/files/{file_id}/tags` | PATCH | `{rel, values}` | `{tags: list}` | B |

---

## Service Methods (Plan B)

### `TaggingService` — New Curation Methods

| Method | Signature | Notes | Plan |
|--------|-----------|-------|------|
| `rename_tag` | `(self, tag_id: str, new_value: str) -> RenameResult` | Rejects `nom:`. find_or_create target → relink_tag_edges → state updates | B |
| `merge_tags` | `(self, source_tag_ids: list[str], canonical_tag_id: str) -> MergeResult` | Rejects `nom:`. Iterates sources through relink. | B |
| `split_tag` | `(self, source_tag_id: str, song_ids: list[str], new_value: str) -> SplitResult` | Rejects `nom:`. Scoped relink. | B |
| `update_file_tags` | `(self, file_id: str, rel: str, values: list[str]) -> dict` | Rejects `nom:`. Wraps set_song_tags + state update. | B |

### `TaggingService` — New Query Methods

| Method | Signature | Notes | Plan |
|--------|-----------|-------|------|
| `list_tag_values` | `(self, rel: str \| None, prefix: str \| None, limit: int, offset: int) -> TagListResult` | Wraps enhanced list_tags_by_rel + count | B |
| `get_tag_songs` | `(self, tag_id: str, limit: int, offset: int) -> dict` | Wraps get_tag_songs_with_metadata + count | B |

### `TaggingService` — New Commit Methods

| Method | Signature | Notes | Plan |
|--------|-----------|-------|------|
| `get_pending_commit_count` | `(self) -> int` | Wraps count_pending_tag_writes | B |
| `commit_pending_tags` | `(self, library_id: str \| None = None) -> CommitResult` | Delegates to reconcile_library | B |

### `TaggingService` — Migrated from LibraryService (Plan B)

| Method | Original Location | Plan |
|--------|-------------------|------|
| `get_unique_tag_keys` | `LibraryQueryMixin` | B |
| `get_unique_tag_values` | `LibraryQueryMixin` | B |
| `get_unique_mood_values` | `LibraryQueryMixin` | B |
| `get_file_tags` | `LibraryFilesMixin` | B |
| `cleanup_orphaned_tags` | `LibraryFilesMixin` | B |
| `search_files_by_tag` | `LibraryQueryMixin` | B |

---

## Decisions

| Decision | Rationale | Plan |
|----------|-----------|------|
| Enhance existing `list_tags_by_rel` instead of new method | Already returns `{_id, rel, value, song_count}` — just needs optional `rel` param | A |
| New `tag_curation_if.py` router, not expanding `tags_if.py` | `tags_if.py` handles file I/O (show/remove tags); curation is a different concern | B |
| Migrate methods by adding to TaggingService + updating callers | Clean migration — TaggingService already has `self.db` for persistence access | B |
| Keep migrated methods on LibraryService as deprecated forwarders | Prevents breakage of any indirect callers not found during migration | B |
