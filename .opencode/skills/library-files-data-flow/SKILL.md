---
name: library-files-data-flow
description: Data flow for songs (song/track) documents — persistence, hydration, field coverage, serialization, and the tag-derived metadata pattern. Use when working with song/track data structures, file queries, tag hydration, or persistence layer changes. See also the song-hydration-flow skill for the write/read hydration paths.
---

# Library Files Data Flow

## Mental Model

Songs/tracks in Nomarr are **rows in the `songs` table**, but their descriptive metadata (`artist`, `album`, `title`, `artists`, `labels`, `genres`, `year`) is NOT stored on the row — it is **derived from tags at query time via hydration** (`tag_hydration_comp.hydrate_songs_with_metadata`). The `songs` row stores filesystem properties plus processing flags (path, size, timestamps, chromaprint, `needs_tagging`, `is_valid`, `tagged`, `calibration_hash`, `write_claimed_by`). Tag edges live in the `song_tags` join table and are batch-loaded during queries.

The canonical song domain object is `Song` in `nomarr/helpers/dataclasses/song_dataclass.py` (ADR-041 domain dataclass; the `LibraryDb` persistence facade owns DB-row → `Song` mapping via `Song.from_row`). The legacy `song_class` module's `Song` (with `DBkey`/`DBid`/`tags`/`embeddings`) has been **deleted** — do not reference it.

## Coverage

**Documented:** canonical `Song` dataclass + `songs` columns, tag-derived metadata hydration (read path), the write/hydration path, library `FileTag`/DTO boundary, song state transitions, bulk operations, serialization (dict-shaped through the persistence/DTO boundary), processing pipeline, and the frontend field contract.

**Related skills:** `song-hydration-flow` (write + read hydration step order, tag_id gap, claims), `song-state-transitions` (state axes), `library-scan-lifecycle` (scan records/heartbeats).

**Last extended:** 2026-09-04

## Key Findings

### 1. Canonical Song dataclass — `nomarr/helpers/dataclasses/song_dataclass.py`

```python
@dataclass(frozen=True, slots=True)
class Song:
    song_id: int            # domain alias for the storage PK (row["id"])
    library_id: int
    folder_id: int | None
    path: str
    normalized_path: str
    file_size: int
    modified_time: int
    duration_seconds: float | None
    chromaprint: str | None
    needs_tagging: bool
    is_valid: bool
    tagged: bool
    calibration_hash: str | None
    write_claimed_by: str | None
    last_tagged_at: int | None
    scanned_at: int | None
    created_at: int
```

- Natural domain identity is `song_id` (a stable caller-facing handle, not a storage-internal name).
- `to_dict()` is a **transitional** projection back to the storage-shaped mapping, aliasing `id` = `song_id`, for downstream dict consumers that still hydrate/project via `row["id"]`.
- `Song.from_row(row)` is the facade-mapper entry (ADR-041): the facade mediates; the domain class stays storage-agnostic.
- `SongTagMatch` (same module) pairs a `Song` with a matched tag + distance (tag-search result).

### 2. `songs` table columns and the write allowlist

The `songs` table columns mirror the `Song` fields above (plus the `id` PK). Timestamps are wall-clock ms. NOT on the row: `artist`/`album`/`title`/metadata (tag-derived).

- `nomarr/persistence/database/song_repo.py` owns song writes: `upsert_song(s)`, `update_song`, and the metadata-cache-specific `update_song_metadata_fields(_batch)` (filters supplied fields down to real `songs` columns, touching only those).
- The `LibraryDb` facade (`nomarr/persistence/api/library.py`, sub-facade `library_songs.py`) exposes intent-level methods (`db.library.songs.update_song_metadata_fields`, etc.); the facade owns row↔domain mapping.

### 3. Tag-derived metadata — read path

Metadata is NOT stored on the `songs` row:

- Tag edges live in the `song_tags` join table (`nomarr/persistence/models/song_tag.py`; writes via `song_tag_repo.replace_song_tags`).
- `tag_hydration_comp.hydrate_songs_with_metadata` batch-reads tags for all songs via `db.library.list_song_tags_for_songs` and merges canonical `artist`/`artists`/`album`/`title`/`label`/`genre`/`year` onto song docs (8 call sites in `library_song_query_comp.py`).
- Queries read `row.get('title')` / `row.get('artist')` — populated by hydration, not DB columns.

See `song-hydration-flow` for the full write-path step order (mutagen extraction → `nom:` tags + entity tags + metadata-cache fields → one-shot `duration_seconds` → `not_hydrated → hydrated`).

### 4. Library `FileTag` / DTO boundary (library-owned tag contract)

- Library song-tag query/read paths pass the library-owned **`FileTag`** DTO (`nomarr/helpers/dto/library_dto.py`), fields `key`/`value`/`tag_type`/`is_nomarr` — NOT domain `Tag`/`Tags` and NOT dict rows.
- Row→`FileTag` projection is centralized in `nomarr/components/library/tag_mapping_comp.py` (`file_tag_from_tag_row`).
- `LibrarySongWithTags` (in `nomarr/helpers/dto/library_dto.py`) is the service/API-facing DTO; `map_song_with_tags_to_dto(row)` converts a raw song dict (whose `tags` are already projected `FileTag` objects) into it.

### 5. Serialization pattern

- Persistence returns raw `dict[str, Any]` rows (no typed row types for songs). Typed structure starts at the DTO/domain layer.
- Layers: persistence/component = raw dicts with `.get()`; DTO/domain = typed dataclasses (`Song`, `LibrarySongWithTags`, `FileTag`); API = Pydantic models mapped from DTOs; frontend = TypeScript interfaces (`frontend/src/shared/api/files.ts`).

### 6. Processing pipeline (ML → tags → DB)

1. A worker claims a song (canonical `db.app.add_claim`), e.g. tag-extraction `Pass 2` (`tag_extraction_worker.py`) for hydration or the discovery worker for ML tagging.
2. `process_file_wf` / `tag_extraction_worker._process_file` produce tags; `_execute_deferred_writes` persists tags → `song_tags` via `save_file_tags`/`set_song_tags_batch` → `song_tag_repo.replace_song_tags`, plus output streams and chromaprint.
3. State transitions run per-axis via `transition_song_state` (`library_song_state_comp.py`, additive remove+add semantics), e.g. `not_hydrated → hydrated`, `not_processed → processed`, `not_calibrated → calibrated`.
4. Reconciliation (`write_tags_to_files`) later writes DB tags to audio files.
5. Calibration apply updates mood tags from stored stats.

### 7. Frontend field contract

`frontend/src/shared/api/files.ts` `LibraryFile`: `tagged`/`skip_auto_tag` serialized to boolean, optional `calibration`, optional `artist`/`album`/`title` populated by hydration. Wire ids are ints (`file_id`). See the `frontend-api-contract` skill for confirmed wire mismatches.

## Critical Invariants

1. **artist/album/title are NOT `songs` columns** — tag-derived during hydration. NEVER assume they exist on raw DB rows.
2. **`song_tags` is the join table** (`songs.id → tags.id`, with `confidence`/`source`/`created_at`). There is no `song_has_tags` table.
3. **Metadata is always batch-loaded** — `hydrate_songs_with_metadata` makes one batch call; never fetch per-file.
4. **Song state lives in state-assignment rows**, not on the `songs` row; per-axis transitions via `transition_song_state` (see `song-state-transitions`).
5. **No typed rows in persistence** — raw SQL results are plain dicts; typing starts at DTO/domain.
6. **`song_class` module is deleted** — canonical song dataclass is `nomarr/helpers/dataclasses/song_dataclass.py`.

## Sources

- `nomarr/helpers/dataclasses/song_dataclass.py` (canonical `Song`/`SongTagMatch`)
- `nomarr/helpers/dto/library_dto.py` (`FileTag`, `LibrarySongWithTags`, `map_song_with_tags_to_dto`)
- `nomarr/persistence/database/song_repo.py`, `song_tag_repo.py`, `song_state_repo.py`
- `nomarr/persistence/api/library.py`, `library_songs.py`, `library_tags.py`, `application.py`
- `nomarr/components/library/tag_hydration_comp.py`, `library_song_query_comp.py`, `library_song_state_comp.py`, `tag_mapping_comp.py`, `song_sync_comp.py`
- `nomarr/components/tagging/tag_write_comp.py`
- `nomarr/workflows/processing/process_file_wf.py`, `write_file_tags_wf.py`
- workers `nomarr/services/infrastructure/workers/discovery_worker.py` and `nomarr/services/infrastructure/workers/tag_extraction_worker.py`
- `nomarr/interfaces/api/web/` (library/songs/tags API surface)
- `frontend/src/shared/api/files.ts`
- Related skills: `song-hydration-flow`, `song-state-transitions`, `library-scan-lifecycle`, `frontend-api-contract`
