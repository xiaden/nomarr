# ADR-045: Metadata is derived from source tags — no embedded metadata-cache columns on songs

**Status:** Accepted  
**Date:** 2026-08-18  
**Tags:** persistence, songs, tags, metadata, single-source-of-truth  
**Source Log:** exec-worker#L1  

## Context

The `songs` table schema (ORM model `song.py`, Alembic baseline migration 001, and the SQLite test schema) contains NO embedded metadata-cache columns — `artist`, `artists`, `album`, `labels`, `genres`, `year`, `_cache_updated_at` do not exist. Yet the legacy write path (`LibrarySongsDb.update_library_song_metadata_cache`, `metadata_cache_comp`) writes these fields via `SongRepository.update_song`, which raises `CompileError: Unconsumed column names` against the real schema. These cache fields duplicate data already stored authoritatively as tags (per ASR-0015 "Single Authoritative Type" and ADR-004's tags-as-authoritative-source note). A previous removal effort is recorded in completed plans TASK-remove-metadata-cache-{A,B,C,D}, which migrated readers to a tag-hydration layer and removed cache writers for the file domain. The hydration migration (TASK-persistence-hydration-migration-A) initially assumed the cache columns existed, but the schema does not support them.

## Decision

Nomarr does NOT store embedded metadata-cache columns on the `songs` table. The `tags` graph is the single authoritative source for browse/entity metadata (artist, artists, album, labels, genres, year). Persistence never writes `metadata_cache` fields as song-row columns; readers derive canonical metadata from source tags at read time via the tag-hydration layer (`tag_hydration_comp.extract_canonical_metadata` / `hydrate_songs_with_metadata`). The song hydration intent persists parsed tags and entity relationships (the source of truth) and does not write denormalized cache columns. The `metadata_cache` field in `HydrateSongInput` is accepted by the contract for forward-compatibility but must not be persisted as columns that do not exist; the tags written during hydration are what back any derived metadata.

## Consequences

Positive: eliminates the two-locations-of-truth drift bug where a cached column could diverge from its source tags; read path is already tag-derived so no reader regresses; no schema/migration work is required and portability across SQLite/PG is preserved (no phantom columns). Negative: the legacy `update_library_song_metadata_cache` write path and `metadata_cache_comp` are dead against the current schema and should eventually be removed; any caller expecting metadata to appear on the raw song row must instead hydrate from tags. The hydration contract's `metadata_cache` input is effectively ignored at the persistence layer until a reader requires it, and this must stay true to avoid reintroducing a second source of truth.

## References

ASR-0015 (Single Authoritative Type); ADR-043 (songs as sole library entity/source of truth); ADR-004 (tags authoritative — superseded by ADR-040 but note retained); completed plans TASK-remove-metadata-cache-{A,B,C,D}; artifacts/designs/parts/persistence-hydration-migration/CONTRACTS.md
