# ADR-007: Tag Editor Service Home — LibraryService Extension via Mixin

**Status:** Accepted  
**Date:** 2026-04-04  
**Tags:** architecture, services, tag-editor  
**Source Log:** rnd-manager#L1  

## Context

The Tag Editor feature needs service-layer wiring for user-facing tag write operations (single-file and bulk). Two candidate services exist:\n\n1. **TaggingService** — owns ML tagging pipeline (`tag_files`, `retag_files`). ML-focused, operates on entire libraries via workers.\n2. **LibraryService** — owns file queries (`search_files`), tag queries (`get_unique_tag_keys`, `get_unique_tag_values`, `get_file_tags`), and library management.\n\nLibraryService already uses a mixin pattern (`LibraryQueryMixin`, `LibraryScanMixin`) for organizing responsibilities. TagOperations persistence has all CRUD primitives (`set_song_tags`, `set_song_tags_batch`) ready for use.

## Decision

Extend LibraryService with a new `LibraryTagEditMixin` containing `update_file_tags()` and `bulk_update_tags()` methods. These methods enforce the `nom:` prefix rejection invariant and delegate to `TagOperations` persistence primitives.\n\nTaggingService remains ML-only. User-facing tag writes live in LibraryService because it already owns the query side of the same data.

## Consequences

**Positive:**\n- Keeps TaggingService focused on ML pipeline\n- Groups read and write operations for tags under one service owner\n- Follows established mixin pattern in LibraryService\n- TagOperations persistence remains the single source of truth for tag CRUD\n\n**Negative:**\n- LibraryService grows larger (mitigated by mixin separation)\n- If tag writes gain complex workflows in the future, may need extraction to a dedicated service\n\n**Neutral:**\n- No impact on existing API contracts or callers

## References

DD-tag-editor.md
