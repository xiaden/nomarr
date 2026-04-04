# Task: Frontend Tag Curation Page

## Problem Statement

With the backend API in place (Plans A+B), the tag curation tool needs a frontend page. This plan creates the `/tag-curation` route with a MUI DataGrid-based tag value browser, inline editing for rename (ADR-011), server-side pagination (ADR-012), expansion panels for song-level drill-down, cross-page selection (ADR-015), merge dialog, split action, commit bar for deferred file writeback (ADR-008), and all supporting hooks and API client code.

**Prerequisite:** TASK-tag-editor-B-backend-service-api

## Phases

### Phase 1: API Client & Hooks
- [x] Create `frontend/src/shared/api/tagCuration.ts` with TypeScript types mirroring backend DTOs (`TagValueItem`, `TagListResult`, `RenameResult`, `MergeResult`, `SplitResult`, `CommitResult`, `TagSongItem`) and API client functions for all tag-curation endpoints (fetchTagValues, fetchTagSongs, renameTag, mergeTags, splitTag, commitPendingTags, fetchPendingCount, updateFileTags). Place in `shared/api/` per codebase convention (no feature-local `api.ts` files).
- [x] Add re-export entry `export * from "./tagCuration";` to `frontend/src/shared/api/index.ts`
- [x] Update `frontend/src/shared/api/library.ts`: migrate `cleanupOrphanedTags()` and `getFileTags()` endpoint URLs to point at new tag-curation API paths, or remove them from `library.ts` and re-implement in `tagCuration.ts`. Update the explicit exports in `frontend/src/shared/api/index.ts` accordingly (move `cleanupOrphanedTags`, `getFileTags`, `CleanupTagsResult`, `FileTagsResult` from the library export block to the tagCuration re-export).
- [x] Create `frontend/src/features/tag-curation/hooks/useTagValues.ts` — fetches tag values with server-side pagination, accepts `rel` and `prefix` filters. Returns `{rows, total, loading, page, setPage, pageSize, setPageSize, refetch}`.
- [x] Create `frontend/src/features/tag-curation/hooks/useTagSongs.ts` — fetches songs for a tag with server-side pagination. Returns `{songs, total, loading, page, setPage, refetch}`.
- [x] Create `frontend/src/features/tag-curation/hooks/useCurationActions.ts` — wraps rename/merge/split/updateFileTags API calls with loading state and error handling. On success, triggers `refetch` on tag values. Returns `{rename, merge, split, updateFileTags, loading}`.
- [x] Create `frontend/src/features/tag-curation/hooks/useSelection.ts` — manages `Set<string>` of selected IDs that persists across pagination. Returns `{selectedIds, toggle, selectAll, deselectAll, count, isSelected}`. Per ADR-015.
- [x] Create `frontend/src/features/tag-curation/hooks/usePendingCommit.ts` — polls `GET /pending-count` on interval (e.g., 10s), exposes `commit()` action and `isCommitting` state. Returns `{pendingCount, commit, isCommitting, isPolling}`.

### Phase 2: Page Components & Routing
- [x] Create `frontend/src/features/tag-curation/TagCurationPage.tsx` — page layout with: `CommitBar` at top, library dropdown (reuse existing `LibrarySelector` or create simple select), search bar with `rel` filter dropdown, `TagValueGrid` as main content. Lazy-load in router.
    **NOTE:** TagCurationPage.tsx created; uses getUniqueTagKeys from shared/api/files.ts to populate rel dropdown; prefix filter is a letter A-Z dropdown; passes rel/prefix to TagValueGrid as optional props.
- [x] Create `frontend/src/features/tag-curation/components/TagValueGrid.tsx` — MUI DataGrid with columns `(rel, value, song_count)`, `paginationMode="server"`, `processRowUpdate` handler for inline rename (double-click value cell), row selection with checkboxes for merge, detail panel via `getDetailPanelContent` for song drill-down (`SongListPanel`). Disable editing and selection for `nom:` prefix rows (grey styling).
    **NOTE:** TagValueGrid.tsx created; uses custom expand column (community DataGrid workaround for Pro-only detail panel); SongListPanel rendered below grid when expanded; processRowUpdate calls rename action; nom: rows styled grey, non-selectable, non-editable; MergeDialog shown when 2+ same-rel rows selected. GridRowSelectionModel in MUI X DataGrid v8 changed to object format with type and ids fields.
- [x] Create `frontend/src/features/tag-curation/components/SongListPanel.tsx` — expansion panel content: DataGrid of songs (title, artist, album) with checkboxes, server-side pagination, cross-page selection via `useSelection`, "Re-tag selected as…" button with autocomplete input that calls `splitTag`, single-song tag chip editing.
    **NOTE:** SongListPanel.tsx created; uses useTagSongs for server-side pagination; useSelection for cross-page selection (ADR-015); useCurationActions for split action; Re-tag selected input calls splitTag then clears selection.
- [x] Create `frontend/src/features/tag-curation/components/MergeDialog.tsx` — MUI Dialog shown when 2+ same-rel tags selected and "Merge" clicked. Lists source tags with song counts, radio selector for canonical tag, preview count ("N songs will be re-tagged"), Merge/Cancel buttons.
    **NOTE:** MergeDialog.tsx created; RadioGroup for canonical tag selection; shows preview of songs to be re-tagged; Merge button disabled if less than 2 source tags.
- [x] Create `frontend/src/features/tag-curation/components/CommitBar.tsx` — persistent banner at top of page: "N files have pending tag changes" + "Commit Changes" button. Uses `usePendingCommit`. Shows progress indicator during commit (reuses existing reconcile status polling pattern).
    **NOTE:** CommitBar.tsx created; uses usePendingCommit hook; renders MUI Alert with Commit Changes button and CircularProgress spinner; returns empty fragment when pendingCount is 0.
- [x] Add `/tag-curation` route to `frontend/src/router/AppRouter.tsx` as lazy-loaded protected route. Add navigation entry in `frontend/src/components/layout/Sidebar.tsx` — specifically append to the `navItems` array (line ~20) with appropriate icon, label, and path. Verify frontend builds with `npm run build` in `frontend/`.
    **NOTE:** AppRouter.tsx: added TagCurationPage lazy import and /tag-curation route. Sidebar.tsx: added Tag Curation entry before Config. ESLint + TypeScript clean (0 errors). Key discovery: MUI X DataGrid v8 GridRowSelectionModel changed from array to { type: include/exclude, ids: Set } — requires new Set(...) for rowSelectionModel prop and model.ids for reading selection.
- [x] Create `frontend/src/features/tag-curation/index.ts` barrel export (all feature folders require an `index.ts`)
    **NOTE:** index.ts barrel export created; exports TagCurationPage, CommitBar, MergeDialog, SongListPanel, TagValueGrid.

## Completion Criteria
- `/tag-curation` route loads and shows tag value grid with data from backend
- Server-side pagination works on both tag value list and song drill-down
- Inline editing triggers rename API (with merge prompt if target exists)
- Multi-select + Merge dialog triggers merge API
- Song drill-down expansion with cross-page selection and split action works
- CommitBar shows pending count and triggers commit
- `nom:` prefix rows are non-interactive (disabled editing, selection, expansion)
- Frontend builds successfully with zero TypeScript errors

## References
- Design doc: `artifacts/designs/pending/DD-tag-editor.md` (Frontend Architecture section)
- ADR-011: MUI DataGrid inline cell editing
- ADR-012: Server-side pagination
- ADR-015: Cross-page selection pattern
- ADR-008: Two-phase curation→commit
- ADR-009: `nom:` prefix exclusion (frontend layer)
- Contracts: `artifacts/designs/parts/tag-editor/CONTRACTS.md`
- Prerequisite: `artifacts/plans/pending/TASK-tag-editor-B-backend-service-api.md`
