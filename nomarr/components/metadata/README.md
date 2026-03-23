# Metadata

Entity lifecycle management — seeding tag relationships from raw metadata, rebuilding caches, and cleaning orphans.

## Responsibilities

- Seed song–entity edges (artist, album, genre, label, year) from raw file metadata
- Compute and write denormalized metadata cache fields on song documents
- Detect and remove orphaned tags no longer referenced by any song
- Batch-optimized seeding for scan workflows (4 AQL per folder instead of ~20×N per file)

## Key Modules

| Module | Purpose |
|--------|----------|
| `entity_seeding_comp` | Seed tag vertices/edges from raw mutagen metadata — single-file (`seed_song_entities_from_tags`) and batch (`seed_entities_for_scan_batch`) paths |
| `metadata_cache_comp` | Compute and write denormalized cache fields (artist, album, genres, etc.) on song documents — single rebuild, batch update, and full-library rebuild |
| `entity_cleanup_comp` | Count and remove orphaned tags (tags with no referencing songs) |

## Patterns

- **Hybrid storage model:** Tags live in a graph (vertices + edges) for querying, but songs also carry denormalized cache fields for fast reads. Both must stay in sync.
- **Batch optimization:** `seed_entities_for_scan_batch` collects per-file entries in memory, then issues 3 AQL for tags + 1 AQL for cache = 4 total, regardless of file count.
- **Pure + DB dual paths:** `compute_metadata_cache_fields` is pure (no DB), used during scan to skip read-back. `rebuild_song_metadata_cache` reads tags from DB for repair.

## Dependencies

- **Upstream:** Called by scan workflows and metadata repair services
- **Downstream:** Calls persistence directly (ArangoDB tag operations via `db.tags`, song document updates)
- **External:** Standard library only
