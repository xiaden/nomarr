# Completion Manifest: Remove Metadata Cache

## Execution Summary

| Plan | Title | Review Rounds | Fix Cycles | Status |
|------|-------|---------------|------------|--------|
| A | Tag Hydration Layer | 2 | 1 | ✅ Complete |
| B | Migrate Readers | 1 | 0 | ✅ Complete |
| C | Remove Writers | 1 | 0 | ✅ Complete |
| D | Schema Cleanup | 0 | 0 | ✅ Complete |

**Total:** 4 plans, 23 phases, ~69 steps executed across 4 Exec-Manager dispatches.

## Design Deviations

### Plan A: Domain Language Refinement
- **Original:** Function names used persistence language (`tag_docs`, `file_docs`, `hydrate_file_docs_with_metadata`)
- **Implemented:** Refactored to use domain language (`song_tags`, `songs`, `hydrate_songs_with_metadata`)
- **Rationale:** Components should speak domain (songs, tags), not persistence (documents, edges). This is a language-only change with no behavioral impact.

### Plan C: Module Deletion Order
- **Original:** Plan assumed clean deletion of `metadata_cache_comp.py` in Phase 3
- **Implemented:** Phase 2 had to neutralize the module (make it no-op) before Phase 3 could delete it, because deleting `update_metadata_cache()` broke the import chain
- **Rationale:** Future plans should co-locate callee and caller deletions to avoid intermediate broken states

## Key Decisions

1. **Tag-first architecture:** Tags collection is the authoritative source of truth. Embedded fields on `library_files` were a read cache that caused consistency bugs.

2. **Hydration on read:** Rather than maintaining a cache, metadata is derived from tags at read time via `hydrate_songs_with_metadata()`. This eliminates cache drift entirely.

3. **Batch hydration:** The hydration layer uses `db.library.list_file_tags_for_files()` for efficient batch tag reading (single AQL query), matching the pattern already used by `_hydrate_files_with_tags()`.

4. **Artist/album filtering moved to Python:** Previously done via DB-level `filters={}` on embedded fields. Now done in Python post-hydration, since these fields no longer exist on `library_files`.

5. **Title search migrated to tag-based search:** `search_files_by_text('title')` replaced with `search_files_by_tag_pattern('title')` which queries the tags collection.

## Files Created

| File | Layer | Purpose |
|------|-------|---------|
| `nomarr/components/library/tag_hydration_comp.py` | Components | Tag hydration layer with domain-appropriate naming |
| `tests/unit/components/library/test_tag_hydration_comp.py` | Tests | 13 unit tests for hydration layer |

## Files Modified

### Components
- `nomarr/components/library/library_file_query_comp.py` — 7 call sites updated to use hydration
- `nomarr/components/navidrome/descriptor_match_comp.py` — `_descriptor_from_doc()` reads from tags
- `nomarr/components/tagging/tag_query_comp.py` — `get_tag_songs_with_metadata()` reads title from tags
- `nomarr/components/library/library_file_mutation_comp.py` — Removed embedded field parameters
- `nomarr/components/library/move_detection_comp.py` — Removed cache rebuild call

### Workflows
- `nomarr/workflows/library/sync_file_to_library_wf.py` — Removed cache rebuild and embedded field writes

### Persistence
- `nomarr/persistence/api/library.py` — Removed `update_library_file_metadata_cache()`, removed embedded fields from `update_library_file_scan_metadata()`
- `nomarr/persistence/database/library_files_aql.py` — Removed dead code (`search_files_by_text`, `search_library_files_by_field`, `TEXT_SEARCH_FIELDS`), removed embedded fields from `ALLOWED_FILE_FIELDS`

### Tests
- `tests/unit/components/library/test_library_file_query_comp.py` — Updated mocks for hydration
- `tests/unit/components/library/test_tag_hydration_comp.py` — New test file
- `tests/unit/components/navidrome/test_descriptor_match_comp.py` — Updated to use tags instead of embedded fields
- `tests/unit/components/library/test_library_file_mutation_comp.py` — Removed `TestUpdateMetadataCache`
- `tests/unit/persistence/database/test_library_files_crud_aql.py` — Removed `TestUpdateMetadataCache`
- `tests/integration/test_library_files_query_regressions.py` — Updated mocks
- `tests/integration/test_domain_path_compatibility.py` — Updated mock assertions
- `tests/unit/workflows/navidrome/test_find_similar_tracks_wf.py` — Updated to use tags format

## Files Deleted

| File | Layer | Reason |
|------|-------|--------|
| `nomarr/components/metadata/metadata_cache_comp.py` | Components | Entire module existed solely to rebuild the cache |
| `nomarr/workflows/metadata/rebuild_metadata_cache_wf.py` | Workflows | Workflow for cache rebuild no longer needed |

## Final Test Status

```
Unit tests:       1618 passed, 1 failed (pre-existing), 2 skipped
Integration tests:  30 passed, 0 failed
```

**Pre-existing failure:** `tests/unit/persistence/database/test_tags_aql.py::TestAggregateTagField::test_allows_underscore_id_field` — tests a method `aggregate_tag_field` that doesn't exist. Unrelated to this feature.

## Lint Status

```
nomarr/components/library/tag_hydration_comp.py: ✅ PASS
nomarr/components/library/library_file_query_comp.py: ✅ PASS
```

## Schema Changes

`ALLOWED_FILE_FIELDS` in `nomarr/persistence/database/library_files_aql.py` no longer includes:
- `album`
- `title`
- `artist`
- `artists`
- `labels`
- `genres`
- `year`

These fields are now derived from tags at read time via the hydration layer.

## Migration Notes

**No data migration required.** ArangoDB is schemaless — existing embedded fields in `library_files` documents become inert data. They can be cleaned up opportunistically but are not read by any code path.

## Future Considerations

1. **`update_library_file_scan_metadata()`** now has zero callers after removing artist/album/title. Candidate for future removal.

2. **Test file placement:** `tests/unit/services/test_worker_system_svc_restart.py` lives in `services/` but tests `services/infrastructure/worker_system_svc.py`. Should be moved to `tests/unit/services/infrastructure/` for consistency.

3. **Pre-existing test failure:** `test_allows_underscore_id_field` in `test_tags_aql.py` tests a non-existent method. Should be removed or the method should be implemented.
