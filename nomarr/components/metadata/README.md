# Metadata

Entity lifecycle management — deriving entity tag assignments from raw metadata, computing metadata cache fields, and cleaning orphans.

## Responsibilities

- Derive song–entity tag assignments (artist, album, genre, label, year) from raw file metadata — compute-only
- Compute the denormalized metadata cache fields (`artist`, `album`, `genres`, etc.) accepted by the hydration contract — compute-only
- Detect and remove orphaned tags no longer referenced by any song
- Provide the hydration entity mapping consumed by the tag-extraction worker

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `entity_seeding_comp` | Compute entity tag assignments from raw metadata — the typed assignment list (`build_song_tag_assignments`) and the hydration entity mapping (`extract_entity_tag_mapping`), both pure functions |
 | `metadata_cache_comp` | Compute denormalized cache fields (`compute_metadata_cache_fields`) from a raw metadata dict — pure, single entry point |

## Patterns

- **Compute-only:** `metadata_cache_comp` computes and returns cache-field mappings; it does **not** read or write the database. Per ADR-045 the embedded song cache writer was removed, and no cache writer remains. The result is accepted by the hydration contract as a forward-compatible `metadata_cache` member but is deliberately never persisted by this module.
- **Batch optimization:** the scan callers collect per-file entity assignments via the compute-only `build_song_tag_assignments`/`extract_entity_tag_mapping` helpers before the library facade persists them.
- **One way in:** `build_song_tag_assignments(tags: dict[str, Any]) -> list[SongTagAssignment]` and `extract_entity_tag_mapping(metadata: dict[str, Any]) -> dict[str, list[str | int | float]]` are pure functions over already-parsed metadata; the caller owns the song's `SongIdentity` locator and persists through the sealed facade.

## Dependencies

- **Upstream:** Called by scan workflows, the tag-extraction worker, and metadata services
- **Downstream:** No database access; these are pure helpers
- **External:** Standard library only
