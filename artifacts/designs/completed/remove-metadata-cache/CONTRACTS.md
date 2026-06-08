# Contracts Ledger: Remove Metadata Cache

This ledger tracks implemented contracts (function signatures, module APIs) as plans are executed.

## Plan A: Tag Hydration Layer

**Status:** Complete

### Planned Contracts

| Module | Function | Signature | Status |
|--------|----------|-----------|--------|
| `nomarr/components/library/tag_hydration_comp.py` | `extract_canonical_metadata` | `(song_tags: list[dict[str, Any]]) -> dict[str, Any]` | ✅ Implemented |
| `nomarr/components/library/tag_hydration_comp.py` | `hydrate_songs_with_metadata` | `(db: Database, songs: list[dict[str, Any]]) -> list[dict[str, Any]]` | ✅ Implemented |
| `nomarr/components/library/tag_hydration_comp.py` | `hydrate_song_with_metadata` | `(db: Database, song: dict[str, Any]) -> dict[str, Any]` | ✅ Implemented |

### Implemented Contracts

- `extract_canonical_metadata(song_tags)` — extracts artist/album/title/artists/labels/genres/year from a song's tags. Uses domain language (songs, tags) rather than persistence language (documents, edges).
- `hydrate_songs_with_metadata(db, songs)` — batch hydration using `db.library.list_file_tags_for_files()`. Returns new dicts without mutation.
- `hydrate_song_with_metadata(db, song)` — single-song convenience wrapper delegating to batch function.

### Decisions

- **Domain language:** Component uses domain terms (songs, tags) not persistence terms (documents, edges). Tag entries use `"name"` as primary field (matching DB schema), with `"key"` fallback for defensive handling.

---

## Plan B: Migrate Readers

**Status:** Phase 8 complete (all phases done)

### Planned Contracts

_No new contracts. Existing readers will be updated to use Plan A's hydration layer._

### Implemented Contracts

_Plan A refactored function names to use domain language: `hydrate_file_docs_with_metadata` → `hydrate_songs_with_metadata`, `hydrate_file_doc_with_metadata` → `hydrate_song_with_metadata`, `tag_docs` → `song_tags`, `file_docs` → `songs`._

_Phase 1: Updated 4 reader functions in `library_file_query_comp.py` to call `hydrate_songs_with_metadata()` before sort/project/filter:_
- `get_recently_processed()` — hydrates after library_id filtering, before sort and projection
- `list_library_files()` — hydrates after fetch, then applies artist/album filtering in Python on hydrated values (removed DB-level `filters={}` for artist/album)
- `search_library_files_with_tags()` — hydrates for metadata before sort; keeps `_hydrate_files_with_tags()` after pagination for tags+library_id
- `get_tracks_by_file_ids()` — hydrates after fetch, before sort and projection

_Phase 2: Updated `get_tracks_for_matching()` to hydrate before building result rows._

_Phase 3: Updated `search_files_by_tag()` both paths to hydrate before sort._

_Phase 4: Updated `_descriptor_from_doc()` in `descriptor_match_comp.py` to read title, artist, album, year from hydrated tags list using `_tag_value()` and `_tag_int()` helpers instead of embedded file_doc fields. Callers confirmed to pass docs hydrated via `get_files_by_ids_with_tags()` which uses `_hydrate_files_with_tags()` (adds "tags" list)._

_Phase 5: Replaced `search_files_by_text('title')` with `search_files_by_tag_pattern('title')` in both `library_file_query_comp` and `descriptor_match_comp`._

_Phase 6: Updated `get_tag_songs_with_metadata()` in `tag_query_comp.py` to read title from tags list via `_first_name_value(tag_docs, "title")` instead of embedded `file_doc.get("title", "")`. Artist and album already used the same pattern._

_Phase 7: Removed dead code — `_matches_text_query()` from `library_file_query_comp.py`, `search_files_by_text()` from both `persistence/api/library.py` and `persistence/database/library_files_aql.py`, `search_library_files_by_field()` from `library_files_aql.py`, and `TEXT_SEARCH_FIELDS` constant. Also simplified `_search_candidate_docs()` in `descriptor_match_comp.py` to remove dead else branch. Fixed stale test mocks in `test_library_files_query_regressions.py` (updated `side_effect` for 3 `search_files_by_tag_pattern` calls, changed `assert_called_once_with` to `assert_any_call` for double hydration). Updated `test_find_similar_tracks_wf.py` to provide metadata in tags list format consistent with Phase 4 `_descriptor_from_doc` changes._

_Phase 8: Verification complete. Component tests: 393 passed, 0 failed. Persistence tests: 252 passed, 1 failed (pre-existing `aggregate_tag_field` method missing — unrelated to this plan). All `file_doc.get("artist"/"album"/"title"/"year")` hits in `library_file_query_comp.py` confirmed to read from hydrated docs (callers hydrate before projection/sort). Other hits (`metadata_extraction_comp.py`, `entity_seeding_comp.py`, `descriptor_match_comp.py` seed dict, `deezer_fetcher_comp.py` API response, `track_matcher_comp.py` row dict) are in write/extraction/unrelated contexts — not embedded-field read paths. Zero remaining `search_files_by_text` references in codebase._

### Decisions

- Artist/album filtering in `list_library_files()` moved from DB-level `filters={}` to Python post-hydration, because these fields will be removed from `ALLOWED_FILE_FIELDS` in Plan D.
- Tests patch `hydrate_songs_with_metadata` as pass-through (`lambda _db, songs: songs`) since hydration logic is tested separately in `test_tag_hydration_comp.py`.
- Phase 4: `descriptor_match_comp.py` reads from "tags" list (via `_tag_value`/`_tag_int`) because its callers use `get_files_by_ids_with_tags()` which calls `_hydrate_files_with_tags()`, not `hydrate_songs_with_metadata()`. Test updated to provide metadata in tags list format.

---

## Plan C: Remove Writers

**Status:** Complete (all 7 phases done)

### Planned Contracts

_Deletions only. No new contracts._

### Implemented Contracts

_Phase 1: Removed `rebuild_song_metadata_cache` import and call from `sync_file_to_library_wf.py`. Removed `artist`/`album`/`title` kwargs from `upsert_library_file()` call. Updated docstring._

_Phase 2: Removed `artist`/`album`/`title` parameters from `upsert_library_file()` and `update_file_path()` signatures and payload dicts in `library_file_mutation_comp.py`. Deleted `update_metadata_cache()` function._

_Phase 3: Deleted `nomarr/components/metadata/metadata_cache_comp.py` and `nomarr/workflows/metadata/rebuild_metadata_cache_wf.py` entirely. Cleaned up both `__init__.py` files._

_Phase 4: Removed `rebuild_song_metadata_cache` import and call from `move_detection_comp.py` (absorbed into Phase 3 for clean module deletion)._

_Phase 5: Deleted `update_library_file_metadata_cache()` from `persistence/api/library.py`. Removed `artist`/`album`/`title` parameters from `update_library_file_scan_metadata()`._

_Phase 6: Verified all callers — zero dangling references to deleted functions._

_Phase 7: 496 tests pass, 0 unexpected failures. Two test files have expected import failures (Plan D scope). One pre-existing failure (`aggregate_tag_field`) documented in Plan B._

### Decisions

- Phase 2 required neutralizing `metadata_cache_comp.py` before Phase 3 could delete it, because deleting `update_metadata_cache()` broke the import chain. Future plans should co-locate callee and caller deletions.
- Phase 4 absorbed into Phase 3: `move_detection_comp.py` references removed early to allow clean deletion of `metadata_cache_comp.py`.
- `update_library_file_scan_metadata()` now has zero callers after removing artist/album/title — candidate for Plan D removal.

---

## Plan D: Schema Cleanup

**Status:** Complete

### Planned Contracts

_Schema changes only. No new contracts._

### Implemented Contracts

_All schema cleanup was completed by Plans B and C. Plan D verified the final state:_
- `ALLOWED_FILE_FIELDS` no longer includes `artist`, `album`, `title`, `artists`, `labels`, `genres`, `year`
- All tests for deleted functions removed
- All tests for modified signatures updated
- Full test suite: 1618 passed, 1 pre-existing failure unrelated to this plan

### Decisions

- **Post-plan refinement:** Function names refactored to use domain language (songs, tags) instead of persistence language (documents, edges). This was a language-only change, no behavioral change.
