# ADR-014: Unified Re-link Persistence Primitive for Tag Curation

**Status:** Accepted  
**Date:** 2026-04-04  
**Tags:** persistence, arangodb, tag-curation  
**Source Log:** rnd-manager#L4  

## Context

The tag curation tool requires four operations: rename, merge, split, and single-song edit. At the graph level, these look different in the UI but are structurally identical:

- **Rename:** Move ALL edges from tag vertex A to tag vertex B (find-or-create B with new value, same rel)
- **Merge:** Move ALL edges from tag vertex A to tag vertex B (B already exists). Handle duplicates — songs already linked to B must not get duplicate edges.
- **Split:** Move SOME edges (selected songs) from tag vertex A to tag vertex B (find-or-create B)
- **Single-song edit:** Move ONE edge from tag vertex A to tag vertex B

All four reduce to: "re-link edges from source tag to target tag for a set of songs (or all songs)."

The existing `set_song_tags_batch()` from ADR-010 operates per-song: given a song, replace all its tags for a rel. This is correct for per-song multi-tag overwrites but is NOT the right primitive for graph-level curation where the operation is "given a tag, move its edges." The access pattern is inverted.

Directly mutating tag vertex values (e.g., renaming by updating the `value` field) is not viable because the `(rel, value)` unique index would conflict if the target value already exists as a separate vertex.

## Decision

All four curation operations use a single persistence primitive: `relink_tag_edges(source_tag_id, target_tag_id, song_ids=None)`.

**Semantics:**
- If `song_ids` is None → re-link ALL edges from source to target
- If `song_ids` is provided → re-link only edges for those songs
- Handles duplicates: songs already linked to target are skipped (no duplicate edges)
- Returns `RelinkResult(moved=int, skipped=int, source_orphaned=bool)`

**Operation mapping:**
- **Rename:** source = old tag vertex, target = find_or_create(same rel, new value), song_ids = None
- **Merge:** source = each tag to merge, target = canonical tag (already exists), song_ids = None
- **Split:** source = current tag, target = find_or_create(same rel, new value), song_ids = selected subset
- **Single-song:** source = current tag, target = find_or_create(same rel, new value), song_ids = [one_song]

**AQL implementation (2-3 round trips):**
1. Find or create target tag vertex (UPSERT on `(rel, value)`)
2. Re-link edges: UPDATE `song_has_tags` WHERE `_to == source_tag_id` (AND `_from IN song_ids` if scoped), SET `_to = target_tag_id`. Use UPSERT to skip duplicates.
3. Cleanup: run `cleanup_orphaned_tags()` to delete source vertex if zero edges remain

**Never mutates a tag vertex value directly** — always re-links edges. This avoids unique index conflicts entirely.

**Relationship to ADR-010:** ADR-010's `set_song_tags_batch` remains valid for per-song multi-tag replacement (the original bulk edit use case). `relink_tag_edges` is the primitive for graph-level curation. They coexist — different access patterns for different use cases.

## Consequences

**Positive:**
- Single primitive handles all four curation operations — minimal persistence surface area
- Avoids unique index conflicts by never mutating tag vertex values
- Duplicate-safe: UPSERT semantics prevent double-edges during merge
- Orphan cleanup is automatic — no dangling tag vertices after rename/merge
- Idempotent: safe to retry on partial failure

**Negative:**
- 2-3 AQL round trips per operation (not single-query). Acceptable for user-initiated curation.
- `cleanup_orphaned_tags()` after every operation adds overhead — could be batched/deferred for bulk merges. Acceptable for alpha.
- Re-linking edges (rather than updating vertex value) means ArangoDB edge `_key` changes for moved edges — no external consumers depend on edge keys today.

**Neutral:**
- Does not replace `set_song_tags_batch` — both primitives coexist for their respective use cases

## References

DD-tag-editor.md, ADR-010 (coexists — different access patterns)
