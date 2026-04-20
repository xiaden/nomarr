# Tag Editor (Tag Curation Tool) — Implementation Parts

**Design doc:** `artifacts/designs/pending/DD-tag-editor.md`

## Parts

 | Part | Title | Depends On | Layers |
 | ------ | ------- | ------------ | -------- |
 | A | Backend Persistence & DTOs | None | persistence, helpers |
 | B | Backend Service & API | A | services, interfaces |
 | C | Frontend Tag Editor | B | frontend |

## Dependency Graph

```
A ──→ B ──→ C
```

## Execution Rounds

- Round 1: A (no deps)
- Round 2: B (depends on A)
- Round 3: C (depends on B)

## Per-Part Scope

### Part A: Backend Persistence & DTOs

Adds the `relink_tag_edges` persistence primitive to `TagOperations` (ADR-014) — the single building block for rename, merge, and split operations. Adds `count_pending_tag_writes()` to `FileStatesOperations` for commit tracking (ADR-003). Enhances existing `list_tags_by_rel` to support optional cross-rel listing. Adds `get_tag_songs_with_metadata` for drill-down with file metadata. Creates all result DTOs needed by service and API layers.

**Files touched:** `nomarr/persistence/database/tags_aql/curation.py` (new), `nomarr/persistence/database/tags_aql/__init__.py`, `nomarr/persistence/database/file_states_aql.py`, `nomarr/helpers/dto/tag_curation_dto.py` (new)
**Contracts exposed:** `relink_tag_edges`, `count_pending_tag_writes`, enhanced tag listing, curation DTOs

### Part B: Backend Service & API

Expands `TaggingService` with curation methods (rename, merge, split, update_file_tags), query methods (list_tag_values, get_tag_songs), and commit methods (get_pending_commit_count, commit_pending_tags). Enforces `nom:` prefix rejection at service layer (ADR-009). Migrates tag query methods from `LibraryService` to `TaggingService` (ADR-013) and updates all 6 callers in `library_if.py`. Creates new `tag_curation_if.py` with curation/query/commit API endpoints. Registers new router.

**Files touched:** `nomarr/services/domain/tagging_svc.py`, `nomarr/services/domain/library_svc/query.py`, `nomarr/services/domain/library_svc/files.py`, `nomarr/interfaces/api/web/tag_curation_if.py` (new), `nomarr/interfaces/api/web/router.py`, `nomarr/interfaces/api/web/library_if.py`
**Contracts exposed:** All TaggingService curation/query/commit methods, all new API endpoints

### Part C: Frontend Tag Editor

Creates the `/tag-curation` page with MUI DataGrid for tag value browsing (server-side pagination, ADR-012), inline editing for rename (ADR-011), expansion panels for song drill-down, cross-page selection (ADR-015), merge dialog, split action, commit bar with pending count, and all supporting hooks. Adds route and navigation.

**Files touched:** `frontend/src/features/tag-curation/` (new directory with components), `frontend/src/router/AppRouter.tsx`, `frontend/src/components/layout/AppShell.tsx` (nav link)
**Contracts exposed:** None (leaf consumer)
