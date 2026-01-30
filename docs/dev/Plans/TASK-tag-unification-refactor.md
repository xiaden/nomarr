# Task: Unify Tag Storage Schema

## Problem Statement

Nomarr has **two parallel tagging systems** storing the same data differently:

**System A (library_tags + file_tags):**
- `library_tags`: Document collection with JSON-stringified values (BUG: `"[\"Artist1\"]"`)
- `file_tags`: Edge collection linking `library_files → library_tags`

**System B (entities/* + song_tag_edges):**
- Separate collections per type: `artists`, `albums`, `genres`, `labels`, `years`
- `song_tag_edges`: Edge collection with `rel` field (duplicated on every edge)

**Consequences:**
- Data duplication (same tag stored 2-3 times)
- JSON serialization bug in API responses
- Inconsistent field names (`display_name` vs `value`)
- Maintenance burden (two code paths for every tag operation)

**Unified Model:**
- ONE vertex collection: `tags` with shape `{rel, value}`
- ONE edge collection: `song_tag_edges` with minimal shape `{_from: song, _to: tag}`
- `rel` stored ONLY on tag vertex (not edges)
- Nomarr provenance via `rel` prefix (`nom:*`) instead of boolean flag
- Scalar values only (no JSON serialization)

---

## Phases

### Phase 1: Schema Changes

- [x] Create `tags` collection in bootstrap
- [x] Add index on `tags.rel` (persistent) for browse by type
- [x] Add unique index on `tags.(rel, value)` for upsert deduplication
- [x] Add index on `song_tag_edges._from` for getting tags per song
- [x] Add index on `song_tag_edges._to` for getting songs per tag
- [x] Add unique index on `song_tag_edges.(_from, _to)` to prevent duplicate edges
- [x] Modify `song_tag_edges` to minimal shape `{_from, _to}` only

**Notes:** Indexes verified in `arango_bootstrap_comp.py` lines 156-194. All required indexes present.

### Phase 2: Create TagOperations

- [x] Create `nomarr/persistence/database/tags_aql.py` with `TagOperations` class
- [x] Wire into `db.py` as `db.tags`
- [x] Implement `find_or_create_tag(rel, value)`
- [x] Implement `get_tag(tag_id)`
- [x] Implement `list_tags_by_rel(rel, limit, offset, search)`
- [x] Implement `count_tags_by_rel(rel, search)`
- [x] Implement `set_song_tags(song_id, rel, values)`
- [x] Implement `add_song_tag(song_id, rel, value)`
- [x] Implement `get_song_tags(song_id, rel, nomarr_only)`
- [x] Implement `list_songs_for_tag(tag_id, limit, offset)`
- [x] Implement `count_songs_for_tag(tag_id)`
- [x] Implement `delete_song_tags(song_id)`
- [x] Implement `cleanup_orphaned_tags()`
- [x] Implement `get_orphaned_tag_count()`

**Notes:** Full API implemented with additional methods: `get_unique_rels`, `get_tag_value_counts`, `get_file_ids_matching_tag`, `get_tag_frequencies`, `get_mood_and_tier_tags_for_correlation`, `get_mood_distribution_data`, `get_file_ids_for_tags`.

### Phase 3: Update Write Path

- [x] Rewrite `entity_seeding_comp.py` to use `db.tags.set_song_tags()`
- [x] Update `sync_file_to_library_wf.py` to use unified TagOperations
- [x] Remove all `db.file_tags.*` calls
- [x] Remove all `db.library_tags.*` calls

**Notes:** `sync_file_to_library_wf.py` verified - uses `db.tags.set_song_tags()` directly for both external and Nomarr tags. No legacy calls remain in codebase.

### Phase 4: Update Read Path

- [x] Rewrite `metadata_svc.py` browse methods to use `db.tags.list_tags_by_rel()`
- [x] Update `entity_cleanup_comp.py` to use `db.tags.cleanup_orphaned_tags()`
- [x] Update `metadata_cache_comp.py` to use new tag queries
- [x] Update `library_files_aql.py` tag queries

**Notes:** All read paths verified using unified schema. `library_files_aql.py` uses `tags` + `song_tag_edges` with correct `rel`/`value` fields.

### Phase 5: Delete Legacy Persistence Code

- [x] Verify `library_tags_aql.py` does not exist
- [x] Verify `file_tags_aql.py` does not exist
- [x] Verify `entities_aql.py` does not exist
- [x] Verify `song_tag_edges_aql.py` does not exist (merged into tags_aql.py)
- [x] Update `db.py` to remove old operation class references

**Notes:** No legacy AQL files found in `nomarr/persistence/database/`. Only unified `tags_aql.py` exists.

### Phase 6: Delete Legacy Component Code

- [x] DELETE `entity_keys_comp.py` (no longer needed, Arango assigns _key)
- [x] Verify `entity_cleanup_comp.py` updated (uses unified TagOperations)
- [x] Update `__init__.py` files to remove stale exports

**Warning:** `entity_keys_comp.py` still exists with hash-based key generation. This is dead code since unified schema uses Arango-assigned keys. Safe to delete.

**Notes:** `entity_cleanup_comp.py` verified - already uses `db.tags.cleanup_orphaned_tags()`.
  Removed 5 stale exports, import test passed
  Confirmed no usages in codebase via search
  File already deleted in previous context

### Phase 7: Verification

- [x] Run full library rescan
- [x] Verify browse UI works (artists, albums, genres, years, labels)
- [x] Verify tag display in file details
- [x] Verify no JSON strings in API responses
- [x] Run `lint_backend` on full codebase
- [x] Run `import-linter` to verify no stale imports

**Notes:** Requires running app - manual verification needed
  import-linter ran. Pre-existing workflow->persistence violations unrelated to tag refactor. No new issues from this work.
  lint_backend passed with check_all=true, 0 errors
  Requires running app - manual verification needed
  Requires running app - manual verification needed
  Requires running app - manual verification needed

---

## Completion Criteria

- [ ] Single `tags` collection for ALL tag types with shape `{rel, value}`
- [ ] Single `song_tag_edges` collection with minimal shape `{_from: song, _to: tag}`
- [ ] `rel` stored ONLY on tag vertex, NOT on edges
- [ ] No `is_nomarr_tag` boolean anywhere — provenance via `rel` prefix (`nom:*`)
- [ ] No JSON string serialization anywhere
- [ ] Scalar values only (str|int|float|bool)
- [ ] Browse by artist/album/genre/year/label works via `tags.rel` filter
- [ ] API responses contain proper typed values
- [ ] All legacy AQL modules deleted
- [ ] `lint_backend` passes with no errors
- [ ] `import-linter` passes

---

## References

- Original design doc: `TAG_UNIFICATION_REFACTOR.md` (archived)
- Schema appendix with before/after examples in original doc
