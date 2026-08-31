---
name: library-files-data-flow
description: Data flow for songs (song/track) documents — persistence, hydration, field coverage, serialization, and the tag-derived metadata pattern. Use when working with song/track data structures, file queries, tag hydration, or persistence layer changes.
---

# Library Files Data Flow

## Mental Model

Songs/tracks in Nomarr are stored as **rows in the `songs` table**, but their metadata fields (`artist`, `album`, `title`) are NOT stored on the row — they are **derived from tags** at query time via a hydration step. The `songs` row only stores filesystem properties: path, size, timestamps, chromaprint. Tags are stored in the `song_has_tags` join table and are batch-loaded during search.

## Coverage

**Documented:** Song/track data structures, persistence layer operations, ALLOWED_FILE_FIELDS vs DTO/API field coverage, tag-derived metadata hydration, bulk operations (scan/batch upsert/reconciliation), serialization (dict-based), calibration_hash field tracking, file state transitions, v2 dataclass comparison, and sub-repo → facade mock migration patterns.

**Not yet documented:** Embedding stream persistence, Navidrome config generation, playlist import flow.

**Last extended:** 2026-07-17

## Key Findings

### 1. Current Song Dataclass (`nomarr/components/library/songs/song_class.py`)

```python
@dataclass(frozen=True)
class Song:
    name: str
    DBkey: str       # Database row key
    DBid: str        # Database row ID
    path: str
    tags: list[Tag]  # Tag has name + value
    embeddings: list[Vector]  # Vector has name + value
```

This is only used in a few places (playlist import, embedding research). It uses `name` not `title`.

### 2. LibraryTrack (`nomarr/components/playlist_import/track_matcher_comp.py`)

```python
@dataclass(frozen=True)
class LibraryTrack:
    file_id: str
    file_path: str
    title: str | None
    artist: str | None
    album: str | None
    isrc: str | None
    normalized_title: str
    normalized_artist: str

    @classmethod
    def from_db_row(cls, row: dict) -> LibraryTrack:
        # reads _id, path, title, artist, album, isrc from row
```

Note: `title`/`artist`/`album` read from DB row dict — these are populated by hydration, NOT direct DB fields.

### 3. LibraryFileWithTags DTO (`nomarr/helpers/dto/library_dto.py`)

```python
@dataclass
class LibraryFileWithTags:
    _id: str
    path: str
    library_id: str | None
    file_size: int | None
    modified_time: int | None
    duration_seconds: float | None
    artist: str | None      # Tag-derived
    album: str | None       # Tag-derived
    title: str | None       # Tag-derived
    calibration: str | None # DTO-only field (no DB equivalent exists)
    scanned_at: int | None
    last_tagged_at: int | None
    tagged: int             # DTO default: False
    tagged_version: str | None
    skip_auto_tag: int
    created_at: str | None
    updated_at: str | None
    tags: list[FileTag]
```

**Critical finding:** `tagged`, `skip_auto_tag`, `created_at`, `updated_at`, `calibration`, `tagged_version` are read from `file_dict.get()` with defaults. These fields may not actually exist on DB documents — they are conventions carried forward from earlier schema versions or from the `map_file_with_tags_to_dto` function which reads them defensively.

### 4. ALLOWED_FILE_FIELDS (Actual DB schema — `nomarr/persistence/database/songs_repo/main.py`)

```python
ALLOWED_FILE_FIELDS = frozenset({
    "path", "normalized_path", "library_key", "status",
    "modified_time", "duration_seconds", "file_size",
    "scanned_at", "chromaprint", "is_valid", "last_tagged_at",
})
```

These 11 fields are the **only fields** that the persistence layer allows to be written via `_update_file()` / `_upsert_file()`. Any field not in this set cannot be written through the SQL persistence layer.

DDL indexes on `songs` (from `nomarr/persistence/schema/ddl.py`) include additional fields:
- `library_id + path` (unique)
- `library_id + normalized_path` (unique)
- `normalized_path`
- `chromaprint` (sparse)
- `needs_tagging + is_valid`
- `library_id + tagged`
- `path`
- `calibration_hash`
- `write_claimed_by` (sparse)

**Notable:** `calibration_hash`, `needs_tagging`, `tagged`, `write_claimed_by` have indexes but are NOT in `ALLOWED_FILE_FIELDS`. These fields may exist on rows but are set through raw SQL or schema migrations, not through the standard file mutation paths.

### 5. Tag-Derived Metadata Pattern

Metadata (`artist`, `album`, `title`, `artists`, `labels`, `genres`, `year`) is **NOT stored on the `songs` document**. Instead:

- Tags are stored as rows in the `song_has_tags` join table
- `extract_canonical_metadata()` in `tag_hydration_comp.py` groups tags by name: `artist`, `artists`, `album`, `title`, `label`, `genre`, `year`
- `hydrate_songs_with_tags()` batch-reads all tags for all songs and **merges** the metadata onto song dicts at query time
- Queries use `file_row.get('title')` / `file_row.get('artist')` / `file_row.get('album')` — these are populated by hydration, not DB columns

**Fields like `bpm`, `musical_key`, `track_number`, `disc_number` are not regular tags.** `bpm` is computed by Essentia algorithms during ML inference. These are stored as `nom:*` tags if configured.

### 6. Upsert/Scan Write Pattern

When scanning a file (`library_file_mutation_comp.py`), only these fields are written:

```python
{
    "path": absolute_path,
    "library_key": library_key,
    "normalized_path": relative_path,
    "file_size": file_size,
    "modified_time": modified_time,
    "duration_seconds": duration_seconds,
    "scanned_at": now_ms,
    "chromaprint": None,
    "last_tagged_at": last_tagged_at,
}
```

`last_tagged_at` is only set on initial upsert if the file was previously ML-tagged (detected during scan).

### 7. Calibration ("hash") Is Tracked by State, Not by Field

`update_file_calibration_hash()` in `ml_calibration_state_comp.py` **only transitions state edges** from `not_calibrated` → `calibrated`. It does NOT write a `calibration_hash` field to the `songs` document despite its name.

The `calibration_hash` parameter used in `write_file_tags_wf.py` comes from the calibration bookkeeping value `calibration_version` (read via `db.app.get_calibration_version()`), not from the file doc.

### 8. File State Machine

File state is tracked through join table rows in the `file_has_state` table. State axis pairs:
- **Processing:** `not_processed` ↔ `processed`
- **Hydration:** `not_hydrated` ↔ `hydrated`  
- **Vectors:** `not_vectors_extracted` ↔ `vectors_extracted`
- **Calibration:** `not_calibrated` ↔ `calibrated`
- **Writeback:** `not_written` ↔ `written`
- **Tag freshness:** `tags_not_fresh` ↔ `tags_current`
- **Error:** `errored` (standalone)

Transitions happen via `transition_file_state()` in `library_file_state_comp.py`.

### 9. Bulk Operations

| Operation | Location | Batch Size |
|-----------|----------|------------|
| Bulk file upsert | `_upsert_files_batch()` in `songs_repo/main.py` | Via `upsert_files_for_library()` |
| Scan (discovery) | `scan_folder_files()` → `FileBatchResult` | Configurable |
| Batch tag writeback | `write_tags_to_files()` in `tagging_svc/write.py` | Default 100 |
| Reconcile stale files | `claim_files_for_reconciliation()` in `reconciliation_comp.py` | Default 100 |
| File path reconciliation | `reconcile_songs()` | All library files |
| State bulk transitions | `transition_file_state()` with list of file_ids | Arbitrary |
| Get files by IDs | `get_files_by_ids_with_tags()` | All, no limit |

### 10. v2 Dataclass Landscape

The `v2/nomarr/helpers/dataclasses/` directory contains:
- `song_dataclass.py` — **excluded from scope by user**
- `tags_dataclass.py` — **excluded from scope by user**
- `library_dataclass.py` — `Library` frozen dataclass (state/config, not file-level)
- `classifier_dataclass.py` — `HeadSpec`, `LabelPrediction`, `HeadDecision`, `ClassificationResult`, `Cascade`
- `embedding_dataclass.py` — `EmbeddingStream`, `VectorEntry`, `VectorSearchResult`, `OutputStream`

The v2 domain component directory `v2/nomarr/components/domain/songs/` is **empty** — no Song domain logic has been migrated yet.

### 11. Serialization Pattern

**There are NO typed row/record types for songs in persistence.** All files are returned as `dict[str, Any]` from SQL. Typed data is only introduced at the DTO level (`helpers/dto/library_dto.py`) via `map_file_with_tags_to_dto()`, which converts raw dicts to `LibraryFileWithTags` dataclass.

This means:
- Persistence layer: raw dicts with `.get()` for field access
- Component layer: raw dicts with `.get()` for field access  
- DTO layer: typed dataclasses (used by services and API)
- API layer: Pydantic models that map from DTOs
- Frontend: TypeScript `LibraryFile` interface with optional `?` fields

### 12. Processing Pipeline (ML → Tags → DB)

1. **DiscoveryWorker** claims a file via worker claim mechanism
2. **process_file_workflow()** loads audio, runs backbones + heads, produces `DeferredFileWrites`
3. **_execute_deferred_writes()** persists:
   - Tags → `song_has_tags` rows via `save_file_tags()`
   - Chromaprint → `songs` doc
   - Output streams → `ml_output_streams` collection
- Transition states: `not_processed` → `processed`, `not_vectors_extracted` → `vectors_extracted`
- Update `last_tagged_at` timestamp on `songs` row
4. **Reconciliation** (later): `write_tags_to_files()` writes tags from DB to audio files via TagWriter
5. **Calibration apply**: `apply_calibration_wf()` updates mood tags based on calibration state

### 13. Frontend Field Contract

The frontend `LibraryFile` interface (in `frontend/src/shared/api/files.ts`) expects:
- `tagged: boolean` (serialized from int, truthy/falsy)
- `skip_auto_tag: boolean` (serialized from int)
- `tagged_version?: string`
- `calibration?: string`
- `artist?, album?, title?` — all optional, populated by hydration

### 14. Sub-Repo → Library Facade Mock Migration (2026-07-17)

The `LibraryDb` class in `nomarr/persistence/api/library.py` is a thin namespaced forwarder exposing exactly four sub-facade properties — `songs`, `tags`, `scans`, `regions` (`db.library.songs`, `db.library.tags`, `db.library.scans`, `db.library.regions`). Production code calls intent-level methods directly on `db.library` (or a sub-facade namespace); the facade exposes no repo properties.

**Vocabulary rename patterns (file → song):**

| Old (pre-evolution) name | Current name |
|---|---|
| `list_file_tag_edges` | `db.library.list_song_tag_edges` |
| `search_files_by_tag_pattern` | `db.library.search_songs_by_tag_pattern` |
| `update_file_fields` | `db.library.update_song_fields` |
| `count_files_for_library` | `db.library.count_songs_for_library` |

**Files affected:** `test_tag_stats_comp.py`, `test_tag_write_comp.py`, `test_library_file_mutation_comp.py`, `test_library_file_query_comp.py`, `test_descriptor_match_comp.py`.

**Also:** Some tests set `MagicMock` on these paths but the production code `await`s them — must use `AsyncMock`.

## Critical Invariants

1. **artist/album/title are NOT file table columns** — they are tag-derived and set during hydration. NEVER assume these exist on raw DB rows.
2. **ALLOWED_FILE_FIELDS is the sole write-allowlist** — fields outside this set (`tagged`, `skip_auto_tag`, `calibration_hash`, `created_at`, `updated_at`, `needs_tagging`, `write_claimed_by`) cannot be written through standard file mutation functions.
3. **calibration_hash on file docs is unused** — calibration is tracked via state edges (`not_calibrated` ↔ `calibrated`). The field has an index but is never set by code.
4. **Tag metadata is always batch-loaded** — `hydrate_songs_with_tags` makes one batch call. Never fetch per-file.
5. **File state is separate from file row** — state lives in join table rows (`file_has_state` table), not on the `songs` row.
6. **No typed rows in persistence** — all raw SQL results are plain dicts. Type safety starts at DTO level.

## Sources

- `nomarr/components/library/songs/song_class.py`
- `nomarr/components/playlist_import/track_matcher_comp.py`
- `nomarr/components/library/file_sync_comp.py`
- `nomarr/components/library/reconciliation_comp.py`
- `nomarr/components/library/library_file_mutation_comp.py`
- `nomarr/components/library/library_file_query_comp.py`
- `nomarr/components/library/library_file_state_comp.py`
- `nomarr/components/library/tag_hydration_comp.py`
- `nomarr/components/ml/calibration/ml_calibration_state_comp.py`
- `nomarr/components/tagging/tag_write_comp.py`
- `nomarr/helpers/dto/library_dto.py`
- `nomarr/helpers/dto/processing_dto.py`
- `nomarr/helpers/dto/metadata_dto.py`
- `nomarr/persistence/database/song_repo.py`
- `nomarr/persistence/database/app_repo.py`
- `nomarr/persistence/api/library.py`
- `nomarr/persistence/api/application.py`
- `nomarr/persistence/schema/names.py`
- `nomarr/persistence/schema/ddl.py`
- `nomarr/interfaces/api/types/library_types.py`
- `nomarr/services/infrastructure/workers/discovery_worker.py`
- `nomarr/services/domain/tagging_svc/write.py`
- `nomarr/services/domain/tagging_svc/apply.py`
- `nomarr/services/infrastructure/pipeline_svc.py`
- `frontend/src/shared/api/files.ts`
- `v2/nomarr/helpers/dataclasses/library_dataclass.py`
- `v2/nomarr/helpers/dataclasses/classifier_dataclass.py`
- `v2/nomarr/helpers/dataclasses/embedding_dataclass.py`
