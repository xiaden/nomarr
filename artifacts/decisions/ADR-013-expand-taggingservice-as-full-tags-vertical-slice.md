# ADR-013: Expand TaggingService as Full Tags Vertical Slice

**Status:** Accepted (Revised)  
**Date:** 2026-04-04  
**Tags:** architecture, services, tag-curation  
**Source Log:** rnd-manager#L3  
**Supersedes:** ADR-007 — Tag Editor Service Home (LibraryService Extension via Mixin)  
**Revised:** 2026-04-04 — Changed from standalone TagCurationService to expanding existing TaggingService

## Context

The Tag Editor design (DD-tag-editor) is being reframed as a tag curation tool that operates at the graph level — renaming tag values across all songs, merging duplicate tags, splitting generic tags into sub-genres, etc. These are fundamentally different operations from per-song tag editing.

ADR-007 placed tag editing in LibraryService via a mixin (`LibraryTagEditMixin`). This was appropriate for simple per-song writes, but graph-level curation changes the scope:

1. **LibraryService is already large** — it owns library management, file queries, tag queries, and scan orchestration. Adding curation methods (rename, merge, split) plus migrated query methods further inflates it.
2. **Curation is a distinct domain** — renaming a tag value across 300 songs is not a "library file operation." It's a graph operation on the tag vertex + edges.
3. **LibraryService's tag query methods** (`get_unique_tag_keys`, `get_unique_tag_values`, `get_unique_mood_values`, `get_file_tags`, `cleanup_orphaned_tags`, `search_files_by_tag`) are actually tag-domain operations that were placed in LibraryService for convenience.

The original ADR-013 proposed a standalone `TagCurationService` separate from the existing `TaggingService`. However, this creates an unnecessary split in the tag domain — TaggingService already owns ML tagging, and adding a separate curation service means two services operating on the same `tags` and `song_has_tags` collections. The simpler approach is to expand TaggingService to own the full tags vertical slice.

## Decision

Expand the existing `TaggingService` to own the full tags vertical slice — file I/O, DB CRUD, curation, and tag queries migrated from LibraryService. This is NOT a new service. TaggingService becomes the single owner of "everything about tags."

**Ownership model:**

 | Question | Owner |
 | ---------- | ------- |
 | "What tags does this file have?" | LibraryService (file metadata perspective) |
 | "What files have this specific tag?" | TaggingService (tag domain perspective) |
 | "Set/update tags on a file" | Library workflow (orchestration) |
 | "Create/manage tag documents in DB" | Tagging component (persistence domain logic) |
 | "Tag curation (rename/merge/split)" | TaggingService (new curation operations) |

**Expanded TaggingService scope:**

- Retains existing ML tagging: `tag_files`, `retag_files`, calibration
- Adds user-facing tag curation: rename, merge, split, single-song edit
- Owns tag query methods migrated from LibraryService: `get_unique_tag_keys`, `get_unique_tag_values`, `get_unique_mood_values`, `cleanup_orphaned_tags`, `search_files_by_tag`
- Enforces `nom:` prefix rejection at the service layer (defense-in-depth per ADR-009)

**What stays where:**

- `LibraryService` retains library management + file queries only. The `LibraryTagEditMixin` from ADR-007 is NOT created.
- TaggingService gets tag query methods migrated from LibraryService
- TaggingService calls `TagOperations` persistence directly for curation operations

**New curation methods on TaggingService:**

- `rename_tag(tag_id, new_value) → RenameResult`
- `merge_tags(source_tag_ids, canonical_tag_id) → MergeResult`
- `split_tag(source_tag_id, song_ids, new_value) → SplitResult`
- `update_file_tags(file_id, name, values) → FileTagsResult`
- `list_tag_values(name, prefix, limit, offset) → TagListResult`
- `get_tag_songs(tag_id, limit, offset) → list[dict]`

**Supersedes ADR-007** which placed tag editing in LibraryService via mixin.

## Consequences

**Positive:**

- Single service owns the entire tag domain — no split between ML tagging and user curation
- Tag query methods move to the service that actually operates on tags
- LibraryService stops growing — sheds responsibilities it shouldn't own
- Clear API surface for the frontend: all tag operations go through one service
- Easier to test: curation logic can be tested without LibraryService's scan/import dependencies
- No new service to wire — reduces DI complexity vs. standalone TagCurationService

**Negative:**

- TaggingService grows larger (but cohesively — all tag-domain operations)
- LibraryService callers that use `get_unique_tag_keys` etc. must be updated to use TaggingService
- Migration effort to move methods from LibraryService to TaggingService

**Neutral:**

- TagOperations persistence is unchanged — TaggingService calls it for both ML and curation ops
- No impact on scan pipeline

## References

DD-tag-editor.md, ADR-007 (superseded)
