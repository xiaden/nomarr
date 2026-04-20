# Tag Curation Tool — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-04-04  
**Revised:** 2026-04-04  

**Related Documents:**

- [ADR-003](artifacts/decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) — Boolean state graph. Provides `tags_written/tags_not_written` axis used by the two-phase commit workflow.
- [ADR-007](artifacts/decisions/ADR-007-tag-editor-service-home-libraryservice-extension-via-mixin.md) — **Superseded by ADR-013, which itself needs revision.** Originally placed tag editing in LibraryService via mixin. Now superseded by the expanded TaggingService direction.
- [ADR-008](artifacts/decisions/ADR-008-database-only-tag-writes-no-audio-file-writeback.md) — DB-only writes, no audio file writeback. **Needs revision:** Not "never write to files" but "writes are deferred and user-initiated via commit." **Proposed ADR Revision: ADR-008** — Revise to document two-phase curation→commit workflow where curation is DB-only and file writeback is deferred, user-initiated via commit button.
- [ADR-009](artifacts/decisions/ADR-009-nom-tag-prefix-exclusion-from-user-editing.md) — nom: prefix enforcement at three layers. **Unchanged.** Curation tool enforces nom: read-only at TaggingService.
- [ADR-010](artifacts/decisions/ADR-010-bulk-edit-commit-strategy-optimistic-batch-via-set-song-tags-batch.md) — Optimistic batch via `set_song_tags_batch`. **Scope narrowed:** remains valid for per-song multi-tag replacement, but graph-level curation ops use the new `relink_tag_edges` primitive from ADR-014.
- [ADR-011](artifacts/decisions/ADR-011-mui-datagrid-inline-cell-editing-for-single-tag-edits.md) — MUI DataGrid inline editing. **Scope expanded:** inline editing now applies to the tag-value list (for rename) in addition to per-song editing in the expansion panel. The DataGrid is tag-value-centric, not file-centric.
- [ADR-012](artifacts/decisions/ADR-012-server-side-pagination-for-tag-editor-results.md) — Server-side pagination. **Scope expanded:** applies to both the tag-value list AND the drill-down song list in the expansion panel.
- [ADR-013](artifacts/decisions/ADR-013-standalone-tagcurationservice.md) — **Needs revision:** Should expand TaggingService rather than creating standalone TagCurationService. **Proposed ADR Revision: ADR-013** — Expand TaggingService as single vertical slice for tags domain (ML calibration + user curation + tag queries).
- [ADR-014](artifacts/decisions/ADR-014-unified-re-link-persistence-primitive-for-tag-curation.md) — **New.** Unified re-link persistence primitive for all curation operations.

---

## Scope

Backend (service + interface + persistence) + Frontend (new page + components + hooks). Expands the existing `TaggingService` to own curation operations alongside ML calibration, adds new persistence primitives in `TagOperations`, new curation and commit API endpoints, and a new React page with MUI DataGrid integration. Migrates tag query methods from `LibraryService` to `TaggingService`. Introduces a two-phase curation→commit workflow: instant DB edits with deferred, user-initiated file writeback.

### Service Ownership

 | Question | Owner |
 | ---------- | ------- |
 | "What tags does this file have?" | LibraryService (file metadata perspective) |
 | "What files have this specific tag?" | TaggingService (tag domain perspective) |
 | "Set/update tags on a file" | Library workflow (orchestration) |
 | "Create/manage tag documents in DB" | Tagging component (persistence domain logic) |
 | "Tag curation (rename/merge/split)" | TaggingService (new curation operations) |
 | "ML calibration and tag writing" | TaggingService (existing operations) |

---

## Problem Statement

Nomarr's ML pipeline generates tags automatically, but tag values are imperfect. Real libraries accumulate:

1. **Weird genres** — `"Electronic / Dance"` vs `"Electronic"` vs `"electronic"`
2. **Overly generic tags** — `"Rock"` applied to 500 songs that should be `"Post-Punk"`, `"Alt-Rock"`, `"Shoegaze"`
3. **Duplicates** — `"Hip-Hop"` and `"Hip Hop"` as separate tag vertices
4. **Single-song misclassifications** — one song tagged `"Jazz"` that's clearly `"Blues"`

Users need a **tag curation tool** that operates at the graph level — not just per-song editing, but the ability to:

- **Rename** a tag value across all songs that have it (normalize weird genres)
- **Merge** duplicate tag values into a canonical form
- **Split** a generic tag by selecting a subset of songs and re-tagging them
- **Edit** a single song's tags (fix misclassifications)

Additionally, curated tags must eventually be written back to audio files on disk so that external players see the changes. This requires a **two-phase workflow**: instant DB edits during curation, followed by user-initiated batch file writeback ("commit").

The existing backend has tag CRUD primitives in `TagOperations` persistence and query capabilities in `LibraryService`, but no service-layer wiring for user-facing tag curation, no frontend UI for tag browsing or graph-level editing, and no deferred file-writeback mechanism.

---

## UX Options

### Option A: Tag Value List with Inline Expansion (RECOMMENDED)

- **Primary view:** Single DataGrid of `(rel, value, song_count)` rows, grouped by rel
- **Rename:** Double-click value cell → inline edit → if target exists, prompt "Merge into existing?"
- **Merge:** Multi-select 2+ rows (same rel) → contextual toolbar "Merge" → pick canonical → confirm with preview count
- **Split:** Click expand chevron on a row → detail panel shows song list with checkboxes → select subset → "Re-tag as…" → autocomplete
- **Single-song edit:** Expand row → find song → click tag chip → edit inline
- **Graph vs song-level disambiguation:** Outer grid = graph-level (all songs). Expansion panel = song-level.
- **Commit bar:** Persistent banner at top showing pending write count + "Commit Changes" button
- **Complexity:** Medium

 | Pros | Cons |
 | ------ | ------ |
 | Tag values are first-class objects, song count visible | Nested pagination needed for popular tags (1000+ songs) |
 | Contextual toolbar shows only relevant actions | Split is 3+ interactions |
 | MUI DataGrid detail panel supported natively | |
 | Natural mapping: outer grid = graph ops, inner panel = song ops | |
 | Two-phase commit avoids slow I/O during curation | |

### Option B: Scope Toggle (Two Modes on Same DataGrid)

- **Primary view:** Same file grid as original DD-tag-editor
- **Toggle:** Tab bar switches between "Song View" (file-centric, per-song editing) and "Tag Value View" (tag-value-centric, graph ops)
- **Complexity:** Medium (extends existing DD design)

 | Pros | Cons |
 | ------ | ------ |
 | Lower risk, reuses existing design | Mode-switch is a known UX antipattern |
 | Explicit mode eliminates ambiguity | Users may forget which mode they're in |

### Option C: Dual-Panel Curator

- **Primary view:** Left panel = tag value tree grouped by rel, Right panel = affected songs
- **Complexity:** High

 | Pros | Cons |
 | ------ | ------ |
 | Most powerful spatial model | Highest frontend effort |
 | Drag-and-drop merge possible | Drag-drop in virtualized lists is complex with MUI |

### Option D: Action-First Command Palette

- **Primary view:** Action cards (Rename, Merge, Split, Edit Song) → each opens wizard flow with preview
- **Complexity:** Medium

 | Pros | Cons |
 | ------ | ------ |
 | Zero ambiguity (user picks action first) | Wizard fatigue |
 | Preview/staging step prevents mistakes | No casual browsing |
 | | Not power-user friendly |

### Recommendation

**Option A** is recommended. It makes tag values first-class objects (matching the graph-level mental model), uses MUI DataGrid's native detail panel for drill-down, and cleanly separates graph-level operations (outer grid) from song-level operations (expansion panel). The contextual toolbar pattern avoids mode confusion (Option B) and wizard fatigue (Option D) while staying within MUI community edition capabilities (unlike Option C's drag-drop).

---

## Architecture

### Layer Mapping

 | Component | Layer | Responsibility |
 | ----------- | ------- | ---------------- |
 | `TaggingService` | services (existing, expanded) | Owns ML calibration (existing) + tag curation (new) + tag queries (migrated from LibraryService). Enforces `nom:` rejection. Single vertical slice for tags domain. |
 | `TagOperations` | persistence (existing) | Add `relink_tag_edges()`, `list_tags_with_counts()`, `get_tag_songs()`, `count_pending_tag_writes()`. Keep existing methods. (ADR-014) |
 | `POST /api/web/tag-curation/rename` | interfaces | Rename a tag value (re-links all edges) |
 | `POST /api/web/tag-curation/merge` | interfaces | Merge 2+ tag values into canonical |
 | `POST /api/web/tag-curation/split` | interfaces | Re-tag subset of songs from one value to another |
 | `POST /api/web/tag-curation/commit` | interfaces | Trigger writing pending tag changes to audio files on disk |
 | `GET /api/web/tag-curation/pending-count` | interfaces | Return count of files with `tags_not_written` state |
 | `PATCH /api/web/tag-curation/file/{id}/tag` | interfaces | Single-song tag edit (kept from original DD) |
 | `GET /api/web/tag-curation/value` | interfaces | List tag values with song counts, filterable by rel |
 | `GET /api/web/tag-curation/{tag_id}/song` | interfaces | Get songs linked to a specific tag value |
 | `TagCurationPage` | frontend | New page at `/tag-curation` |
 | `TagValueGrid` | frontend | MUI DataGrid: `(rel, value, song_count)` with expandable detail panels |
 | `CommitBar` | frontend | Persistent banner: pending write count + "Commit Changes" button |
 | `MergeDialog` | frontend | Confirmation dialog for merge operations |
 | `useTagValues(rel)` | frontend | Hook: fetch tag values with counts |
 | `useTagSongs(tagId)` | frontend | Hook: fetch songs linked to tag value |
 | `useCurationActions()` | frontend | Hook: rename/merge/split/single-song API calls |
 | `useSelection()` | frontend | Hook: cross-page selection management |
 | `usePendingCommit()` | frontend | Hook: pending count polling + commit trigger |

### Data Model

**Existing (no changes):**

- `tags` collection: docs with `rel` + `value`, unique index on `(rel, value)`
- `song_has_tags` edges to `library_files`: unique on `(_from, _to)`
- `file_states` collection: boolean state vertices including `tags_written` and `tags_not_written` (ADR-003)
- `file_has_state` edges: one edge per file per axis linking to state vertices

**No new collections or indexes required.** The `tags_written/tags_not_written` axis from ADR-003 is reused for commit tracking.

### Two-Phase Curation → Commit Workflow

All curation operations follow a two-phase pattern:

```
Curate:  User renames/merges/splits → DB updated immediately → file state set to tags_not_written
Pending: UI shows "N files have pending tag changes" via CommitBar
Commit:  User clicks "Commit Changes" → POST /tag-curation/commit → TaggingService.reconcile_library()
         processes tags_not_written files → state set to tags_written
```

**Phase 1 — Curation (instant, DB-only):**

- All curation operations (rename/merge/split/single-song edit) write to DB only
- After each curation op, affected files' state edges are updated: `tags_written → tags_not_written` on the ADR-003 boolean state graph
- This marks "DB tags do not match file on disk" — pending writes accumulate

**Phase 2 — Commit (batch, user-initiated file I/O):**

- `CommitBar` component polls `GET /tag-curation/pending-count` to show pending file count
- User clicks "Commit Changes" → `POST /tag-curation/commit` → `TaggingService.reconcile_library()` processes all files in `tags_not_written` state
- `reconcile_library()` already exists on `TaggingService` — it reads DB tags and writes them to audio files, then sets state to `tags_written`
- Progress indicator shown during commit (reuses existing `get_reconcile_status` polling)

**State edge transitions:**

- Curation op → `set_tags_not_written(file_id)` for each affected file
- Commit → `reconcile_library()` → for each processed file: write tags to disk → `set_tags_written(file_id)`

### New Persistence Methods (ADR-014)

```python
# New in TagOperations:

def relink_tag_edges(
    source_tag_id: str,
    target_tag_id: str,
    song_ids: list[str] | None = None,
) -> RelinkResult:
    """Re-link edges from source tag to target tag.

    If song_ids is None, re-links ALL edges from source to target.
    If song_ids is provided, only re-links edges for those songs.
    Handles duplicates (songs already linked to target are skipped).

    Returns: RelinkResult(moved=int, skipped=int, source_orphaned=bool)
    """

def list_tags_with_counts(
    rel: str | None = None,
    prefix: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> TagListResult:
    """List tag values with edge counts, optionally filtered by rel and value prefix.

    Returns: TagListResult(tags=[{id, rel, value, song_count}], total=int)
    """

def get_tag_songs(
    tag_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Get songs linked to a specific tag vertex with basic file metadata."""

def count_pending_tag_writes() -> int:
    """Count files in tags_not_written state via INBOUND traversal on the
    tags_not_written state vertex. O(1) discovery per ADR-003."""
```

**AQL implementation for `relink_tag_edges` (2-3 round trips):**

1. Find or create target tag vertex (UPSERT on `(rel, value)`)
2. Re-link edges: for each edge WHERE `_to == source_tag_id` (AND `_from IN song_ids` if scoped), UPSERT a new edge `(_from, target_tag_id)` and REMOVE the old edge. UPSERT handles duplicates.
3. Cleanup: run `cleanup_orphaned_tags()` to delete source vertex if zero edges remain.

### API Surface

#### Curation Endpoints (New)

```
POST /api/web/tag-curation/rename
  Body: { "tag_id": "tags/123", "new_value": "post-punk" }
  → Service finds or creates target tag with same rel + new value
  → Calls relink_tag_edges(source=tag_id, target=new_or_existing_tag_id)
  → Sets affected files to tags_not_written state
  → Returns: { "moved": 312, "merged_into_existing": true/false }

POST /api/web/tag-curation/merge
  Body: { "source_tag_ids": ["tags/123", "tags/456"], "canonical_tag_id": "tags/789" }
  → For each source tag: relink_tag_edges(source, canonical)
  → Sets affected files to tags_not_written state
  → Returns: { "total_moved": 500, "sources_removed": 2 }

POST /api/web/tag-curation/split
  Body: { "source_tag_id": "tags/123", "song_ids": ["library_files/a", ...], "new_value": "alt-rock" }
  → Service finds or creates target tag with same rel + new_value
  → Calls relink_tag_edges(source, target, song_ids=song_ids)
  → Sets affected files to tags_not_written state
  → Returns: { "moved": 15, "new_tag_created": true }
```

#### Commit Endpoints (New)

```
POST /api/web/tag-curation/commit
  Body: { "library_id": "libraries/abc" }  (optional — if omitted, commits all libraries)
  → Triggers TaggingService.reconcile_library() for files in tags_not_written state
  → Returns: { "started": true, "pending_files": 47 }
  → Progress polled via GET /api/web/library/{library_id}/pipeline

GET /api/web/tag-curation/pending-count
  → Returns: { "count": 47 }
  → Uses count_pending_tag_writes() persistence method (O(1) via ADR-003 state vertex)
```

#### Song-Level Endpoints (Kept from Original DD)

```
PATCH /api/web/files/{file_id}/tags
  Body: { "rel": "genre", "values": ["rock", "alternative"] }
  → Single-song multi-value replace. Uses existing set_song_tags.
  → Sets file to tags_not_written state
  → Returns: updated tag list for the file+rel
```

#### Query Endpoints (New)

```
GET /api/web/tag-curation/value?rel=genre&prefix=roc&limit=100&offset=0
  → Returns tag values with song counts

GET /api/web/tag-curation/{tag_id}/song?limit=50&offset=0
  → Returns songs linked to this tag with file metadata
```

### Service Layer — Expanded TaggingService

The existing `TaggingService` at `nomarr/services/domain/tagging_svc.py` is expanded to own the entire tags domain. It already has: `tag_file`, `tag_library`, `reconcile_library`, `read_file_tags`, `remove_file_tags`, calibration status, and background apply. The following methods are added:

```python
# Added to TaggingService:

# Migrated from LibraryService query mixins:
def get_unique_tag_keys(self, nomarr_only: bool = False) -> UniqueTagKeysResult
def get_unique_tag_values(self, tag_key: str, nomarr_only: bool = False) -> UniqueTagKeysResult
def get_unique_mood_values(self, mood_tier: str, limit: int) -> UniqueTagKeysResult
def get_file_tags(self, file_id: str, nomarr_only: bool = False) -> FileTagsResult
def cleanup_orphaned_tags(self, dry_run: bool = False) -> TagCleanupResult
def search_files_by_tag(self, tag_key: str, target_value: float | str, limit: int, offset: int) -> SearchFilesResult

# New curation operations:
def list_tag_values(self, rel: str | None, prefix: str | None, limit: int, offset: int) -> TagListResult
def get_tag_songs(self, tag_id: str, limit: int, offset: int) -> list[dict]
def rename_tag(self, tag_id: str, new_value: str) -> RenameResult
def merge_tags(self, source_tag_ids: list[str], canonical_tag_id: str) -> MergeResult
def split_tag(self, source_tag_id: str, song_ids: list[str], new_value: str) -> SplitResult
def update_file_tags(self, file_id: str, rel: str, values: list[str]) -> FileTagsResult

# New commit operations:
def get_pending_commit_count(self) -> int
def commit_pending_tags(self, library_id: str | None = None) -> CommitResult
```

**Dependency injection:** `TaggingService` already gets `Database` injected. New curation methods call `TagOperations` persistence directly. `commit_pending_tags` delegates to the existing `reconcile_library()` which processes files in `tags_not_written` state.

### Frontend Architecture (Option A)

#### Component Hierarchy

```
TagCurationPage (lazy-loaded route: /tag-curation)
├── CommitBar                    # Persistent banner: "47 files have pending tag changes" + "Commit Changes" button
│   └── ProgressIndicator        # Shown during commit, polls reconcile status
├── LibrarySelector              # Dropdown: "All Libraries" + each library
├── SearchBar                    # Text filter + rel filter dropdown
│   └── FilterChips              # Active filters display
├── Toolbar
│   ├── SelectionInfo            # "3 tag values selected" / "47 songs selected across 3 pages"
│   ├── MergeButton              # Opens MergeDialog (enabled when 2+ same-rel rows selected)
│   └── RefreshButton
├── TagValueGrid                 # @mui/x-data-grid, paginationMode="server"
│   ├── Columns: rel, value (editable), song_count
│   ├── Row grouping: by rel
│   ├── Inline edit: double-click value → rename
│   │   └── If target exists: prompt "Merge into existing 'post-punk' (45 songs)?"
│   └── Detail panel (expand chevron):
│       └── SongListPanel
│           ├── Song rows with checkboxes: title, artist, album
│           ├── Pagination: paginationMode="server" (ADR-012)
│           ├── Cross-page selection: checkboxes persisted across page navigation
│           ├── "Select All Matching" button → selects all songs for current filter
│           ├── "Re-tag selected as…" button → autocomplete input
│           └── Single-song tag chip editing
└── MergeDialog                  # MUI Dialog
    ├── Source tags list with song counts
    ├── Canonical tag selector (radio)
    ├── Preview: "312 songs will be re-tagged"
    └── Action buttons: Merge / Cancel
```

#### State Management (hooks)

 | Hook | Purpose |
 | ------ | --------- |
 | `useTagValues(rel)` | Fetch tag values with counts, handle pagination |
 | `useTagSongs(tagId)` | Fetch songs linked to a tag value, handle pagination |
 | `useCurationActions()` | Submit rename/merge/split/single-song APIs with optimistic UI |
 | `useSelection()` | Cross-page selection management: `Set<string>` of IDs, select/deselect, select-all-matching mode, count display |
 | `usePendingCommit()` | Poll pending count via `GET /tag-curation/pending-count`, trigger commit via `POST /tag-curation/commit`, track commit progress |

#### Cross-Page Selection

**Selection state:**

- Frontend maintains a `Set<string>` of selected song IDs independent of the currently-loaded page
- Selections persist across page navigation — selecting songs on pages 1, 2, 5, and 7 applies bulk operations to ALL selected songs
- `SelectionInfo` component shows: "47 songs selected across 3 pages"

**"Select All" behavior:**

- "Select All" on current page: adds current page's song IDs to the selection set
- "Select All Matching" (global): backend endpoint returns all matching IDs for the current filter, or a special "select all N results" action
- When "Select All Matching" is active, bulk operations send the **filter criteria** to the backend instead of individual IDs (to avoid sending 10,000 IDs in a request body)

#### Data Flow

```
Browse:     LibrarySelector + SearchBar → useTagValues → GET /tag-curation/value → TaggingService → AQL
Expand:     Detail panel → useTagSongs → GET /tag-curation/{id}/song → TaggingService → AQL
Rename:     DataGrid processRowUpdate → useCurationActions → POST /tag-curation/rename → TaggingService → relink_tag_edges → set tags_not_written
Merge:      MergeDialog confirm → useCurationActions → POST /tag-curation/merge → TaggingService → relink_tag_edges (per source) → set tags_not_written
Split:      Detail panel "Re-tag as…" → useCurationActions → POST /tag-curation/split → TaggingService → relink_tag_edges → set tags_not_written
Single:     Detail panel tag chip edit → useCurationActions → PATCH /tag-curation/file/{id}/tag → TaggingService → set_song_tags → set tags_not_written
Pending:    usePendingCommit → GET /tag-curation/pending-count → TaggingService → count_pending_tag_writes() → AQL on tags_not_written vertex
Commit:     CommitBar "Commit Changes" → usePendingCommit → POST /tag-curation/commit → TaggingService.reconcile_library() → write files → set tags_written
```

---

## nom: Tag Enforcement (Three-Layer Guard)

Same defense-in-depth as ADR-009, now on expanded `TaggingService`:

1. **Frontend:** `nom:` tags displayed but not editable — grey rows, no expand, no actions. Contextual toolbar buttons disabled for `nom:` selections.
2. **Service:** `TaggingService` curation methods reject any operation targeting a `nom:` rel with `ValueError("Cannot modify ML-generated tags (nom: prefix)")`.
3. **Persistence:** Debug assertion `assert not rel.startswith("nom:")` as safety net.

---

## Edge Cases

- **Concurrent edits:** Last-write-wins (ArangoDB UPSERT). Acceptable for alpha.
- **Rename to existing value:** Treated as merge — prompt user with "Merge into existing '{value}' ({count} songs)?".
- **Merge with overlapping songs:** Songs linked to both source and canonical get one edge (to canonical). Duplicates skipped by UPSERT. `skipped` count reported.
- **Split with empty selection:** Frontend disables "Re-tag as…" button when no songs are checked.
- **Orphan cleanup:** After rename/merge, source tag vertex is deleted if zero edges remain. `source_orphaned` flag in response.
- **Large tag values (1000+ songs):** Nested pagination in detail panel (ADR-012 scope expansion).
- **Special characters in tag values:** ArangoDB bind variables handle escaping.
- **Empty results:** MUI DataGrid `noRowsOverlay` slot.
- **Pending commit state:** Files in `tags_not_written` state are displayed normally in curation UI. CommitBar shows count. Multiple curation ops can accumulate before a single commit.
- **Commit during curation:** Commit processes current `tags_not_written` files. If user curates during commit, newly-affected files enter `tags_not_written` and will be picked up by the next commit.
- **Re-scan while pending commits exist:** A library re-scan may overwrite DB tags for files in `tags_not_written` state. Open question: should re-scan skip files with pending commits, or should commit be forced first?

---

## Design Goals

1. Enable users to curate tag values at the graph level: rename, merge, split
2. Support single-song tag editing for misclassification fixes
3. Protect ML-generated (`nom:`) tags from user modification at every layer
4. Provide tag-value-centric browsing with song counts and drill-down
5. Server-side pagination for both tag value list and song drill-down
6. Single persistence primitive (`relink_tag_edges`) for all curation operations
7. Two-phase curation→commit workflow: instant DB edits, user-initiated file writeback
8. Cross-page selection persistence for bulk operations

---

## Constraints

1. MUI DataGrid community edition only (no Pro/Premium features)
2. ArangoDB community edition — no multi-collection transactions
3. `nom:` prefix tags are immutable by users (ML pipeline owns them)
4. File writeback is deferred and user-initiated (commit), not immediate — curation ops are DB-only
5. File state tracking uses ADR-003 boolean state graph (`tags_written/tags_not_written` axis)
6. Frontend uses React 19 + MUI 7 + TypeScript 5.9
7. Must follow existing layer architecture: interfaces → services → workflows → components → persistence
8. TaggingService is expanded as single vertical slice — not a new standalone service, not a LibraryService mixin

---

## Proposed ADR Revisions

1. **Proposed ADR Revision: ADR-013** — Change from "standalone TagCurationService" to "expand TaggingService as single vertical slice for tags domain." TaggingService owns ML calibration AND user curation AND tag queries migrated from LibraryService.
2. **Proposed ADR Revision: ADR-008** — Change from "no audio file writeback" to "two-phase curation→commit: DB-only edits are instant, file writeback is deferred and user-initiated via commit button." Curation operations set file state to `tags_not_written`; commit triggers `reconcile_library()` which writes to disk and sets `tags_written`.
3. **Proposed ADR: Cross-Page Selection Pattern** — Frontend selection state persists across server-side pagination pages. `Set<string>` of selected IDs maintained client-side, independent of loaded page. "Select All Matching" sends filter criteria to backend instead of individual IDs. This is a reusable pattern for any paginated bulk-operation UI.

---

## Open Questions

1. **Detail panel pagination UX:** MUI DataGrid community edition supports detail panels but nested DataGrids in detail panels may have scroll/layout quirks. Needs prototyping.
2. **Tag value types:** `rel` has no type metadata — values are polymorphic (`str | int | float | bool`). Should the UI validate types or accept all as strings?
3. **Undo support:** Should curation operations support undo? Rename/merge are lossy if the source tag is orphan-cleaned. Consider a confirmation step with preview counts instead.
4. **Export/import:** Future extensibility — should the API design accommodate CSV tag export/import?
5. **Autocomplete cardinality for split:** The "Re-tag as…" autocomplete needs existing tag values. Server-side prefix filtering via `GET /tag-curation/value?prefix=...` handles large cardinalities.
6. **Commit UX — progress and errors:** Should commit show per-file progress or just a spinner? What happens if some files fail to write (e.g., file locked, permissions)? Partial commit with error report?
7. **Commit scope:** Should commit be per-library or global? Current design supports both (optional `library_id` param). Per-library may be more predictable for users.
8. **Re-scan vs pending commits:** If a user triggers a library re-scan while files have pending tag commits, the scan may overwrite curated DB tags. Options: (a) force commit before re-scan, (b) skip `tags_not_written` files during re-scan, (c) warn and let user choose.
9. **State edge semantics for single-song edits:** When a user edits one tag on a song via `PATCH /tag-curation/file/{id}/tag`, should only that file be marked `tags_not_written`, or all files affected by the tag value? (Answer: only the directly edited file.)
10. **Select All Matching implementation:** Should the backend return all matching IDs (simple but large payload), or should bulk operations accept filter criteria directly (more complex but scalable)?
11. **Bulk merge:** Should the UI support selecting 10+ tags for merge, or cap at a reasonable limit to prevent accidental mass merges?
