# ADR-014: Unified Re-link Persistence Primitive for Tag Curation

**Status:** Accepted  
**Date:** 2026-04-04  
**Tags:** persistence, arangodb, tag-curation  
**Source Log:** rnd-manager#L4  

## Context

The tag curation tool requires four operations: rename, merge, split, and single-song edit. At the data level, these look different in the UI but are structurally identical:

- **Rename:** Re-point ALL song_has_tags rows from tag A to tag B (find-or-create B with new value, same rel)
- **Merge:** Re-point ALL song_has_tags rows from tag A to tag B (B already exists). Handle duplicates — songs already linked to B must not get duplicate rows.
- **Split:** Re-point SOME song_has_tags rows (selected songs) from tag A to tag B (find-or-create B)
- **Single-song edit:** Re-point ONE song_has_tags row from tag A to tag B

All four reduce to: "re-point song_has_tags rows from source tag to target tag for a set of songs (or all songs)."

The existing `set_song_tags_batch()` from ADR-010 operates per-song: given a song, replace all its tags for a rel. This is correct for per-song multi-tag overwrites but is NOT the right primitive for tag-graph curation where the operation is "given a tag, re-point its rows." The access pattern is inverted.

Directly mutating tag rows (e.g., renaming by updating the `value` field) is not viable because the `(name, value)` unique index would conflict if the target value already exists as a separate row.

## Decision

All four curation operations use a single persistence primitive: `relink_tag_edges(source_tag_id, target_tag_id, song_ids=None)`.

**Semantics:**

- If `song_ids` is None → re-point ALL song_has_tags rows from source to target
- If `song_ids` is provided → re-point only rows for those songs
- Handles duplicates: songs already linked to target have their source edge
  removed (no duplicate rows are created)
- Returns `RelinkResult(moved=int, skipped=int, source_orphaned=bool)`

**Operation mapping:**

- **Rename:** source = old tag, target = find_or_create(same name, new value), song_ids = None
- **Merge:** source = each tag to merge, target = canonical tag (already exists), song_ids = None
- **Split:** source = current tag, target = find_or_create(same name, new value), song_ids = selected subset
- **Single-song:** source = current tag, target = find_or_create(same name, new value), song_ids = [one_song]

**Implementation (2-3 SQL statements):**

1. Find or create the target tag (upsert — `INSERT ... ON CONFLICT` on `(name, value)`)
2. Re-point rows: first DELETE source rows whose target edge already exists (correlated `EXISTS` on `(song_id, target_tag_id)`), then UPDATE the remaining source rows to `target_tag_id` (AND `song_id IN song_ids` if scoped). This preserves one edge per song without leaving the source assignment behind.
3. Cleanup: run `cleanup_orphaned_tags()` to delete the source tag if zero referencing rows remain

**Never mutates a tag value directly** — always re-points rows. This avoids unique index conflicts entirely.

**Relationship to ADR-010:** ADR-010's `set_song_tags_batch` remains valid for per-song multi-tag replacement (the original bulk edit use case). `relink_tag_edges` is the primitive for tag-graph curation. They coexist — different access patterns for different use cases.

## Consequences

**Positive:**

- Single primitive handles all four curation operations — minimal persistence surface area
- Avoids unique index conflicts by never mutating tag values directly
- Duplicate-safe: collision source rows are deleted before re-pointing, so no duplicate `(song_id, tag_id)` rows are created
- Orphan cleanup is automatic — no dangling tags after rename/merge
- Idempotent: safe to retry on partial failure

**Negative:**

- 2-3 SQL statements per operation (not single-query). Acceptable for user-initiated curation.
- `cleanup_orphaned_tags()` after every operation adds overhead — could be batched/deferred for bulk merges. Acceptable for alpha.
- Re-pointing rows (rather than updating tag value) means the `song_has_tags` rows change for moved songs — no external consumers depend on the old row identity today.

**Neutral:**

- Does not replace `set_song_tags_batch` — both primitives coexist for their respective use cases

## References

DD-tag-editor.md, ADR-010 (coexists — different access patterns)
