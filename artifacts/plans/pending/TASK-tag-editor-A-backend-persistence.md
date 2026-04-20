# Task: Backend Persistence & DTOs for Tag Curation

## Problem Statement

Nomarr needs a tag curation tool that lets users rename, merge, split, and edit tags at the graph level. All curation operations share a common persistence pattern: re-linking edges from one tag vertex to another. This plan creates the foundational persistence primitive (`relink_tag_edges` per ADR-014), commit tracking via the boolean state graph (`tags_not_written` per ADR-003), enhanced tag listing for the UI, song metadata queries for drill-down, and all result DTOs needed by service and API layers.

**Prerequisite:** None (first plan in tag-editor sequence)

## Phases

### Phase 1: Persistence Primitives

- [x] Create `nomarr/persistence/database/tags_aql/curation.py` with `TagCurationMixin` containing `relink_tag_edges(self, source_tag_id: str, target_tag_id: str, song_ids: list[str] | None = None) -> RelinkResult`. Implementation: (1) find/create target tag vertex via existing `find_or_create_tag`, (2) AQL UPSERT new edges from songs to target + REMOVE old edges from songs to source (scoped by `song_ids` if provided, otherwise all), (3) call existing `cleanup_orphaned_tags()` for source if zero edges remain. Return `RelinkResult(moved, skipped, source_orphaned)`.
    **executor:** Created curation.py with TagCurationMixin.relink_tag_edges. Uses 2-3 AQL round trips: find edges, UPSERT+REMOVE in single query, orphan check+cleanup. Returns dict matching RelinkResult shape. DTO import deferred to Phase 2.
- [x] Add `TagCurationMixin` to the `TagOperations` class bases in `nomarr/persistence/database/tags_aql/__init__.py`
    **executor:** Added TagCurationMixin to TagOperations bases and import in **init**.py.
- [x] Enhance `list_tags_by_rel` in `nomarr/persistence/database/tags_aql/queries.py` to accept `rel: str | None = None` — when `None`, list across all rels. Also accept `search: str | None = None` for value prefix filtering (STARTS_WITH) and `sort_by_count: bool = False` for count-based ordering — matching CONTRACTS.md signature: `(self, rel=None, limit=100, offset=0, search=None, sort_by_count=False)`. Update `count_tags_by_rel` to match (`rel: str | None = None, search: str | None = None`).
    **executor:** Enhanced list_tags_by_rel and count_tags_by_rel to accept rel as optional. When None, omits the rel filter for cross-rel listing. Refactored from branched query strings to dynamic filter building. Existing callers pass rel positionally so remain compatible.
- [x] Add `get_tag_songs_with_metadata(self, tag_id: str, limit: int = 50, offset: int = 0) -> list[dict]` to `TagQueriesMixin` in `nomarr/persistence/database/tags_aql/queries.py`. AQL: traverse `song_has_tags` INBOUND from tag_id, join `library_files` for `{file_id, title, artist, album, path}`. Add `count_tag_songs_with_metadata(self, tag_id: str) -> int` for pagination total (or reuse existing `count_songs_for_tag`).
    **executor:** Added get_tag_songs_with_metadata to TagQueriesMixin. Uses INBOUND traversal on song_has_tags from tag vertex, with OUTBOUND subqueries for artist/album tag values. count_tag_songs_with_metadata not added separately because existing count_songs_for_tag (in TagMoodMixin) already returns the same count.
- [x] Add `count_pending_tag_writes(self) -> int` and `get_pending_tag_write_file_ids(self, limit: int = 100) -> list[str]` to `FileStatesOperations` in `nomarr/persistence/database/file_states_aql.py`. AQL: INBOUND traversal on `file_states/tags_not_written` vertex — count and list file IDs respectively.
    **executor:** Added count_pending_tag_writes and get_pending_tag_write_file_ids to FileStatesOperations. Both use INBOUND traversal on STATE_TAGS_NOT_WRITTEN constant, following the same pattern as count_untagged_files/get_untagged_file_ids.
- [x] Verify `tags_not_written` state vertex exists in `file_states` collection. Check `nomarr/migrations/V022_file_state_graph_completion.py` — if `tags_not_written` is present (it is in V022 lines 44/146), no new migration needed. If missing (schema changed since planning), create `V023` migration to add it.
    **executor:** Verified: tags_not_written state vertex exists in V022_file_state_graph_completion.py at lines 44 and 146. Also confirmed STATE_TAGS_NOT_WRITTEN constant exists in file_states_aql.py. No new migration needed.
- [x] Verify `lint_project_backend` passes on all modified persistence files
    **executor:** All 4 modified files pass lint with zero errors: curation.py, queries.py, **init**.py, file_states_aql.py.

### Phase 2: Result DTOs

- [x] Create `nomarr/helpers/dto/tag_curation_dto.py` with TypedDict DTOs: `RelinkResult` (moved: int, skipped: int, source_orphaned: bool), `TagValueItem` (id: str, rel: str, value: str, song_count: int), `TagListResult` (tags: list[TagValueItem], total: int), `RenameResult` (moved: int, merged_into_existing: bool), `MergeResult` (total_moved: int, sources_removed: int), `SplitResult` (moved: int, new_tag_created: bool), `CommitResult` (started: bool, pending_files: int), `TagSongItem` (file_id: str, title: str, artist: str, album: str)
    **executor:** Created tag_curation_dto.py with all 8 TypedDicts: RelinkResult, TagValueItem, TagListResult, RenameResult, MergeResult, SplitResult, CommitResult, TagSongItem. Only stdlib imports (typing.TypedDict).
- [x] Export new DTOs from `nomarr/helpers/dto/__init__.py` and verify `lint_project_backend` passes
    **executor:** Exported all 8 DTOs from helpers/dto/**init**.py, added to **all** in alphabetical order. lint_project_backend passes with zero errors on both files.

## Completion Criteria

- `relink_tag_edges` handles full relinking (all songs) and scoped relinking (subset of songs) with duplicate edge handling via UPSERT
- `count_pending_tag_writes` returns count via INBOUND traversal on `tags_not_written` state vertex
- `list_tags_by_rel(rel=None)` returns cross-rel tag listing with song counts
- `get_tag_songs_with_metadata` returns song metadata (not just IDs) for UI drill-down
- All 8 DTOs exist and are importable from `nomarr.helpers.dto`
- `lint_project_backend` passes with zero errors on all changed files

## References

- Design doc: `artifacts/designs/pending/DD-tag-editor.md`
- ADR-003: Boolean state graph (`tags_not_written` axis)
- ADR-014: Unified `relink_tag_edges` persistence primitive
- Contracts: `artifacts/designs/parts/tag-editor/CONTRACTS.md`
