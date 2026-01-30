# Tag Storage Unification Refactor

**Status:** Planning  
**Priority:** High (blocks other refactors)  
**Created:** 2026-01-25

---

## Problem Statement

Nomarr has **two parallel tagging systems** that store the same data differently:

### System A: library_tags + file_tags
- **library_tags**: Document collection storing tag definitions
  - Shape: `{ _key, key, value (JSON string), is_nomarr_tag }`
  - Values stored as JSON strings: `"[\"Artist1\", \"Artist2\"]"`
- **file_tags**: Edge collection linking `library_files → library_tags`
  - Shape: `{ _from, _to }`

### System B: entities/* + song_tag_edges
- **Entity collections** (artists, albums, genres, labels, years):
  - Shape: `{ _key, display_name }`
  - One collection per browseable tag type
- **song_tag_edges**: Edge collection linking `entity → library_files`
  - Shape: `{ _from, _to, rel }`
  - `rel` field identifies the tag type ("artist", "album", etc.)

### Consequences

1. **Data Duplication**: Same data (artist, album, genre, year, label) stored in BOTH systems
2. **Serialization Bug**: `library_tags.value` is JSON string; AQL returns raw strings to frontend
3. **Inconsistent Shapes**: `display_name` vs `value` field names
4. **Wasted Storage**: Same tag stored 2-3 times (library_tags, entity collection, library_files cache)
5. **Maintenance Burden**: Two code paths to update for every tag operation
6. **Unnecessary Complexity**: Multiple collections for conceptually identical data

---

## Root Cause

A refactor created `library_tags` + `file_tags` as a parallel system instead of extending the existing entity pattern. The `sync_file_to_library_wf.py` workflow now calls BOTH:

```python
# Line 120: Writes to library_tags + file_tags
db.file_tags.upsert_file_tags_mixed(file_id, external_tags, nomarr_tags)

# Line 136: Writes to entity collections + song_tag_edges (same data!)
seed_song_entities_from_tags(db, file_id, entity_tags)
```

---

## Unified Model

### Design Principles

1. **ONE vertex collection**: All tags live in `tags` (no separate artists/albums/etc.)
2. **ONE edge collection**: All file↔tag relationships via `song_tag_edges`
3. **`rel` on vertex, not edge**: Tag type stored on the tag, not duplicated on edges
4. **Namespace-based provenance**: Nomarr-generated tags have `rel` starting with `"nom:"`. No boolean fields.
5. **Scalar values only**: No JSON serialization. No lists. Multi-value = multiple edges.
6. **No normalization**: `"Rock"` ≠ `"rock"` — exact string match always

### Schema

#### Vertex Collection: `tags`

```json
{
  "_key": "auto-assigned-by-arango",
  "_id": "tags/12345",
  "rel": "artist",           // Tag key (artist, album, genre, nom:mood-strict, etc.)
  "value": "The Beatles"     // Scalar: str | int | float | bool. NEVER list. NEVER JSON.
}
```

**Uniqueness**: A tag is uniquely identified by `(rel, value)` pair. No two documents should have the same `(rel, value)`.

#### Edge Collection: `song_tag_edges`

```json
{
  "_key": "auto-assigned",
  "_id": "song_tag_edges/67890",
  "_from": "library_files/abc123",  // Song _id
  "_to": "tags/12345"               // Tag _id
}
```

**Direction**: `_from` = song, `_to` = tag. This matches the semantic "song HAS tag".

**Minimal edge**: Edges contain ONLY `_from` and `_to`. No `rel`, no `is_nomarr_tag`. Provenance is inferred from the tag's `rel` prefix.

### Provenance Convention

| `rel` Prefix | Source | Examples |
|--------------|--------|----------|
| `nom:*` | Nomarr-generated | `nom:mood-strict`, `nom:danceability_...` |
| All others | External/user/library metadata | `artist`, `album`, `genre`, `year` |

**Filtering Nomarr tags**: Use `STARTS_WITH(tag.rel, "nom:")` or `tag.rel LIKE "nom:%"`.

### Required Indexes

| Collection | Index Type | Fields | Purpose |
|------------|------------|--------|---------|
| `tags` | persistent | `["rel"]` | Filter tags by type for browse, Nomarr prefix filtering |
| `tags` | persistent, unique | `["rel", "value"]` | Upsert by exact match, prevent duplicates |
| `song_tag_edges` | persistent | `["_from"]` | Find all tags for a song |
| `song_tag_edges` | persistent | `["_to"]` | Find all songs for a tag |

### Tag Key Examples

| `rel` Value | Example `value` | Notes |
|-------------|-----------------|-------|
| `artist` | `"The Beatles"` | Primary artist (singular) |
| `artists` | `"John Lennon"` | Contributing artists (one edge per artist) |
| `album` | `"Abbey Road"` | Album name |
| `genre` | `"Rock"` | One edge per genre |
| `label` | `"Apple Records"` | One edge per label |
| `year` | `1969` | Integer, not string |
| `track_number` | `5` | Integer |
| `bpm` | `120.5` | Float |
| `nom:danceability_...` | `0.7234` | Float (Nomarr-generated) |
| `nom:mood-strict` | `"peppy"` | String (one edge per mood value) |

---

## Current State Analysis

### Collections to DROP

| Collection | Reason |
|------------|--------|
| `library_tags` | Replaced by unified `tags` |
| `file_tags` | Replaced by unified `song_tag_edges` |
| `artists` | Replaced by `tags` with `rel="artist"` or `rel="artists"` |
| `albums` | Replaced by `tags` with `rel="album"` |
| `genres` | Replaced by `tags` with `rel="genre"` |
| `labels` | Replaced by `tags` with `rel="label"` |
| `years` | Replaced by `tags` with `rel="year"` |

### Collections to MODIFY

| Collection | Change |
|------------|--------|
| `song_tag_edges` | Remove `rel` field, change direction (song→tag), minimal edge shape |

### Collections to CREATE

| Collection | Purpose |
|------------|---------|
| `tags` | Single unified tag vertex collection |

---

## Code Impact Analysis

### Files to DELETE

| File | Reason |
|------|--------|
| `nomarr/persistence/database/library_tags_aql.py` | Replaced by unified TagOperations |
| `nomarr/persistence/database/file_tags_aql.py` | Replaced by unified TagOperations |
| `nomarr/persistence/database/entities_aql.py` | Replaced by unified TagOperations |
| `nomarr/persistence/database/song_tag_edges_aql.py` | Merged into TagOperations |
| `nomarr/components/metadata/entity_keys_comp.py` | No longer needed (Arango assigns _key) |
| `nomarr/components/metadata/entity_cleanup_comp.py` | Replaced by tag cleanup in TagOperations |

### Files to CREATE

| File | Purpose |
|------|---------|
| `nomarr/persistence/database/tags_aql.py` | Unified TagOperations class |

### Files to MODIFY

#### Persistence Layer

| File | Changes |
|------|---------|
| `arango_bootstrap_comp.py` | Drop 7 collections, create `tags`, update indexes |
| `db.py` | Remove old operations, add unified `TagOperations` |
| `library_files_aql.py` | Update all tag queries to use `tags` + `song_tag_edges` |

#### Component Layer

| File | Changes |
|------|---------|
| `entity_seeding_comp.py` | Rewrite as sole tag writer using TagOperations |
| `metadata_cache_comp.py` | Update to read via TagOperations |

#### Workflow Layer

| File | Changes |
|------|---------|
| `sync_file_to_library_wf.py` | Remove file_tags calls, only call entity seeding |
| `scan_library_direct_wf.py` | Same |

#### Service Layer

| File | Changes |
|------|---------|
| `metadata_svc.py` | Rewrite browse queries to filter by `tags.rel` |

---

## New TagOperations API

```python
class TagOperations:
    """Unified tag operations for the tags collection."""
    
    def find_or_create_tag(self, rel: str, value: str | int | float | bool) -> str:
        """Find or create a tag vertex. Returns tag _id."""
        # UPSERT on (rel, value) unique index
        
    def get_tag(self, tag_id: str) -> dict | None:
        """Get tag by _id. Returns {_id, _key, rel, value}."""
        
    def list_tags_by_rel(
        self, 
        rel: str, 
        limit: int = 100, 
        offset: int = 0,
        search: str | None = None
    ) -> list[dict]:
        """List all unique tag values for a rel. For browse UI."""
        
    def count_tags_by_rel(self, rel: str, search: str | None = None) -> int:
        """Count unique tags for a rel."""
        
    # --- Edge operations ---
    
    def set_song_tags(
        self, 
        song_id: str, 
        rel: str, 
        values: list[str | int | float | bool]
    ) -> None:
        """Replace all tags for a song+rel. Creates tag vertices as needed."""
        # 1. Delete existing edges for song+rel (via subquery on tag.rel)
        # 2. For each value: find_or_create_tag, create edge
        # Note: Nomarr provenance is implicit in rel prefix ("nom:*")
        
    def get_song_tags(
        self, 
        song_id: str, 
        rel: str | None = None,
        nomarr_only: bool = False
    ) -> list[dict]:
        """Get all tags for a song, optionally filtered by rel or Nomarr prefix."""
        # If nomarr_only=True, filter by STARTS_WITH(tag.rel, "nom:")
        
    def list_songs_for_tag(
        self, 
        tag_id: str, 
        limit: int = 100, 
        offset: int = 0
    ) -> list[str]:
        """List song _ids with this tag. For browse drill-down."""
        
    def count_songs_for_tag(self, tag_id: str) -> int:
        """Count songs with this tag."""
        
    def delete_song_tags(self, song_id: str) -> None:
        """Delete all tag edges for a song (on file delete)."""
        
    def cleanup_orphaned_tags(self) -> int:
        """Delete tags with no edges. Returns count deleted."""
```

---

## Browse Query Patterns

### List all artists (paginated)

```aql
FOR tag IN tags
    FILTER tag.rel == "artist"
    SORT tag.value
    LIMIT @offset, @limit
    LET song_count = LENGTH(
        FOR edge IN song_tag_edges
            FILTER edge._to == tag._id
            RETURN 1
    )
    RETURN { _id: tag._id, value: tag.value, song_count: song_count }
```

### Get songs for an artist

```aql
FOR edge IN song_tag_edges
    FILTER edge._to == @tag_id
    SORT edge._from
    LIMIT @offset, @limit
    RETURN edge._from
```

### Get all tags for a song

```aql
FOR edge IN song_tag_edges
    FILTER edge._from == @song_id
    LET tag = DOCUMENT(edge._to)
    RETURN { 
        rel: tag.rel, 
        value: tag.value
    }
```

### Get Nomarr-only tags for a song

```aql
FOR edge IN song_tag_edges
    FILTER edge._from == @song_id
    LET tag = DOCUMENT(edge._to)
    FILTER STARTS_WITH(tag.rel, "nom:")
    RETURN { 
        rel: tag.rel, 
        value: tag.value
    }
```

### Get specific tag type for a song

```aql
FOR edge IN song_tag_edges
    FILTER edge._from == @song_id
    LET tag = DOCUMENT(edge._to)
    FILTER tag.rel == @rel
    RETURN tag.value
```

---

## Migration Phases

### Phase 0: Pre-Migration Cleanup

1. Document current state for reference
2. Ensure tests exist for browse functionality
3. No data preservation needed (pre-alpha: users rescan)

### Phase 1: Schema Changes

1. **Create `tags` collection** in bootstrap
2. **Add indexes**:
   - `tags`: `["rel"]` (persistent) — browse by type, Nomarr prefix filtering
   - `tags`: `["rel", "value"]` (persistent, unique) — upsert deduplication
   - `song_tag_edges`: `["_from"]` (persistent) — get tags for song
   - `song_tag_edges`: `["_to"]` (persistent) — get songs for tag
3. **Modify `song_tag_edges`**: Minimal edge shape `{_from, _to}` only

### Phase 2: Create TagOperations

1. Create `nomarr/persistence/database/tags_aql.py` with `TagOperations` class
2. Wire into `db.py` as `db.tags`
3. Implement all methods from API spec above

### Phase 3: Update Write Path

1. Rewrite `entity_seeding_comp.py` to use `db.tags.set_song_tags()`
2. Update `sync_file_to_library_wf.py` to only call entity seeding
3. Remove all `db.file_tags.*` and `db.library_tags.*` calls

### Phase 4: Update Read Path

1. Rewrite `metadata_svc.py` browse methods to use `db.tags.list_tags_by_rel()`
2. Update `metadata_cache_comp.py` to use new tag queries
3. Update `library_files_aql.py` tag queries

### Phase 5: Delete Legacy Code

1. **DELETE** `library_tags_aql.py`
2. **DELETE** `file_tags_aql.py`
3. **DELETE** `entities_aql.py`
4. **DELETE** `song_tag_edges_aql.py` (merged into tags_aql.py)
5. **DELETE** `entity_keys_comp.py`
6. **DELETE** `entity_cleanup_comp.py`
7. **Update** `db.py` to remove old operation classes
8. **Update** `__init__.py` files

### Phase 6: Drop Collections

1. **DROP** `library_tags` collection
2. **DROP** `file_tags` collection
3. **DROP** `artists` collection
4. **DROP** `albums` collection
5. **DROP** `genres` collection
6. **DROP** `labels` collection
7. **DROP** `years` collection
8. Update bootstrap to not create these collections

### Phase 7: Verification

1. Run full library rescan
2. Verify browse UI works (artists, albums, genres, years, labels)
3. Verify tag display in file details
4. Verify no JSON strings in API responses
5. Run QC scripts to detect orphaned references
6. Run import-linter to verify no stale imports

---

## Pre-Alpha Policy

Because Nomarr is pre-alpha:
- **No data migrations** - users rescan libraries after update
- **No backwards compatibility** - breaking schema changes OK
- **No deprecation periods** - delete old code immediately

---

## Call Site Inventory

### library_tags reads (DELETE all)

| Location | Operation |
|----------|-----------|
| `file_tags_aql.py` (multiple) | `LibraryTagOperations(self.db)` |

### file_tags reads (DELETE all)

| Location | Operation |
|----------|-----------|
| `library_files_aql.py:204` | Tag join in `get_files_by_ids_with_tags` |
| `library_files_aql.py:262,272` | Search by tag |
| `library_files_aql.py:312,322` | Search by tag |
| `library_files_aql.py:567-574` | Truncate all |
| `library_files_aql.py:1029,1045,1116` | Tag queries |

### entities reads (MIGRATE to tags.rel filter)

| Location | Operation | New Pattern |
|----------|-----------|-------------|
| `metadata_svc.py:57-58` | `db.entities.list_entities` | `db.tags.list_tags_by_rel(rel)` |
| `metadata_svc.py:86` | `db.entities.get_entity` | `db.tags.get_tag(tag_id)` |
| `metadata_svc.py:217-221` | `db.entities.count_entities` | `db.tags.count_tags_by_rel(rel)` |
| `entity_cleanup_comp.py:31,50` | Orphan cleanup | `db.tags.cleanup_orphaned_tags()` |

### song_tag_edges reads (MIGRATE to TagOperations)

| Location | Operation | New Pattern |
|----------|-----------|-------------|
| `metadata_svc.py:115-116` | `list_songs_for_entity` | `db.tags.list_songs_for_tag(tag_id)` |
| `metadata_svc.py:139,146,177,184,194` | Traversals | Rewrite with new edge direction |
| `metadata_cache_comp.py:26-32` | `list_entities_for_song` | `db.tags.get_song_tags(song_id, rel)` |
| `entity_seeding_comp.py:40-41` | Write path | `db.tags.set_song_tags()` |

---

## Acceptance Criteria

- [ ] Single `tags` collection for ALL tag types with shape `{rel, value}`
- [ ] Single `song_tag_edges` collection with minimal shape `{_from: song, _to: tag}`
- [ ] `rel` stored ONLY on tag vertex, NOT on edges
- [ ] No `is_nomarr_tag` boolean anywhere — provenance via `rel` prefix (`nom:*`)
- [ ] No JSON string serialization anywhere
- [ ] Scalar values only (str|int|float|bool)
- [ ] `"Rock"` ≠ `"rock"` (case-sensitive, no normalization)
- [ ] Browse by artist/album/genre/year/label works via `tags.rel` filter
- [ ] Nomarr-only filtering works via `STARTS_WITH(rel, "nom:")` queries
- [ ] API responses contain proper typed values
- [ ] 7 legacy collections deleted (library_tags, file_tags, artists, albums, genres, labels, years)
- [ ] 4+ legacy AQL modules deleted
- [ ] QC scripts pass with no orphan references
- [ ] import-linter passes

---

## Risks

| Risk | Mitigation |
|------|------------|
| Data loss | Pre-alpha: users rescan; no migration needed |
| Incomplete call site update | Use grep + import-linter to find all references |
| Performance regression | Proper indexes on (rel), (rel,value), (_from), (_to) |
| Browse pagination issues | Test with large tag counts before merging |

---

## Dependencies

This refactor should be completed BEFORE:
- SafeDatabase refactor (TAG_UNIFICATION removes the JSON string issue)
- Write-Ahead Journal (simpler schema = fewer operations to journal)

---

## Appendix: Schema Comparison

### BEFORE: library_tags (TO BE DROPPED)
```json
{
  "_key": "12345",
  "_id": "library_tags/12345",
  "key": "artist",
  "value": "[\"The Beatles\"]",  // JSON string! BUG!
  "is_nomarr_tag": false
}
```

### BEFORE: file_tags (TO BE DROPPED)
```json
{
  "_key": "67890",
  "_id": "file_tags/67890",
  "_from": "library_files/abc123",
  "_to": "library_tags/12345"
}
```

### BEFORE: artists (TO BE DROPPED)
```json
{
  "_key": "v1_abc123...",
  "_id": "artists/v1_abc123...",
  "display_name": "The Beatles"
}
```

### BEFORE: song_tag_edges (TO BE MODIFIED)
```json
{
  "_key": "99999",
  "_id": "song_tag_edges/99999",
  "_from": "artists/v1_abc123...",  // entity → song (WRONG direction)
  "_to": "library_files/abc123",
  "rel": "artist"  // DUPLICATED on edge
}
```

### AFTER: tags (NEW - unified)
```json
{
  "_key": "12345",
  "_id": "tags/12345",
  "rel": "artist",
  "value": "The Beatles"  // Scalar string, NOT JSON
}
```

```json
{
  "_key": "67890",
  "_id": "tags/67890",
  "rel": "year",
  "value": 1969  // Integer, NOT string
}
```

```json
{
  "_key": "11111",
  "_id": "tags/11111",
  "rel": "nom:danceability_essentia21-beta6-dev_effnet20220217_danceability20220825",
  "value": 0.7234  // Float
}
```

### AFTER: song_tag_edges (MODIFIED)
```json
{
  "_key": "99999",
  "_id": "song_tag_edges/99999",
  "_from": "library_files/abc123",  // song → tag (CORRECT direction)
  "_to": "tags/12345"
}
```

Multiple edges for multi-value tags:
```json
// Song has two genres (external metadata)
{ "_from": "library_files/abc123", "_to": "tags/11111" }  // tag: {rel: "genre", value: "Rock"}
{ "_from": "library_files/abc123", "_to": "tags/22222" }  // tag: {rel: "genre", value: "Pop"}

// Song has Nomarr-generated tags (rel starts with "nom:")
{ "_from": "library_files/abc123", "_to": "tags/33333" }  // tag: {rel: "nom:mood-strict", value: "peppy"}
{ "_from": "library_files/abc123", "_to": "tags/44444" }  // tag: {rel: "nom:danceability_...", value: 0.7234}
```
