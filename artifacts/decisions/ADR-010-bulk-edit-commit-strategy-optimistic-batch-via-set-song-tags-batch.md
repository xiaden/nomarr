# ADR-010: Bulk Edit Commit Strategy — Optimistic Batch via set_song_tags_batch

**Status:** Accepted  
**Date:** 2026-04-04  
**Tags:** persistence, arangodb, tag-editor, performance  
**Source Log:** rnd-manager#L1  

## Context

The Tag Editor needs to support bulk tag edits across N selected songs. Three approaches were considered:\n\n1. **Transactional:** Wrap all changes in a single ArangoDB transaction. Not viable — community edition doesn't support multi-collection transactions, and tag writes span `tags` + `song_has_tags` collections.\n2. **Per-tag sequential:** One API call per (file, rel) pair. Simple but O(N) round-trips — unacceptable for 100+ songs.\n3. **Batch:** Use existing `set_song_tags_batch()` which handles N entries in 3 AQL round-trips (ensure tags exist, remove stale edges, upsert new edges). Not truly atomic but idempotent — safe to retry on partial failure.\n\nThe `set_song_tags_batch()` persistence method already exists and is tested.

## Decision

Use `set_song_tags_batch()` for bulk edits with optimistic UI. Client updates displayed rows immediately and rolls back on API error.\n\nFor very large selections (1000+ entries), chunk the batch into groups of 1000 and show progress per chunk. Each chunk is an independent batch call — partial success is possible but each chunk is idempotent and safe to retry.

## Consequences

**Positive:**\n- Reuses existing, tested persistence method — no new AQL\n- 3 AQL round-trips regardless of batch size (within a chunk)\n- Idempotent — safe to retry on failure\n- Optimistic UI provides responsive feel\n\n**Negative:**\n- Not atomic across chunks — partial failure leaves some songs updated and others not\n- Optimistic UI requires rollback logic on error\n\n**Acceptable for alpha:** Last-write-wins semantics and non-atomic chunking are fine for single-user alpha. Revisit if concurrent multi-user editing becomes a requirement.

## References

DD-tag-editor.md
