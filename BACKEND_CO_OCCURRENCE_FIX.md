# Backend Co-Occurrence Fix - Implementation Summary

## Problem

The co-occurrence matrix was showing lots of zeros, particularly for mood tag presets. Investigation revealed a fundamental mismatch between how mood tags are stored and how they were being queried.

### Root Cause

**Storage Format:**
Mood tags are stored as JSON arrays in the database:
```json
{
  "name": "nom:mood-strict",
  "value": ["aggressive", "happy", "energetic"]
}
```

**Query Method (Before Fix):**
The `get_file_ids_for_mood_tags()` function used exact matching:
```python
# This was the problematic code
file_ids = _file_ids_for_tag_docs(db, _exact_tags_for_name_value(db, name, mood_value))
```

Which generated AQL:
```aql
FILTER tag.name == @tag_key AND tag.value == @value
```

**The Mismatch:**
- Searching for: `nom:mood-strict = "aggressive"`
- Stored value: `["aggressive", "happy", "energetic"]`
- Result: **NO MATCH** (array != string)

This caused empty file sets, leading to zeros in the co-occurrence matrix.

## Solution

Implemented CONTAINS matching for mood tags using ArangoDB's `IN` operator.

### Changes Made

#### 1. Database Layer (`nomarr/persistence/database/tags_aql.py`)

Added new method `search_files_by_tag_contains()`:

```python
def search_files_by_tag_contains(self, tag_key: str, value: str, *, limit: int | None) -> list[Document]:
    """Search for files where tag.value array contains the given value.
    
    Used for array-valued tags like mood tags where multiple values are stored
    in a single tag document (e.g., nom:mood-strict = ["aggressive", "happy"]).
    """
    bind_vars: dict[str, Any] = {
        "@tag_collection": self.COLLECTION,
        "@edge_collection": self.EDGE_COLLECTION,
        "tag_key": tag_key,
        "value": value,
    }
    query_lines = [
        "FOR tag IN @@tag_collection",
        "    FILTER tag.name == @tag_key AND @value IN tag.value",  # ← CONTAINS matching
        "    FOR edge IN @@edge_collection",
        "        FILTER edge._to == tag._id",
        "        COLLECT file_id = edge._from",
        "        LET file = DOCUMENT(file_id)",
        "        FILTER file != null",
        "        SORT file._key",
    ]
    # ... limit handling ...
    return primitives.execute(self._db, "\n".join(query_lines), bind_vars)
```

#### 2. API Layer (`nomarr/persistence/api/library.py`)

Exposed the new method through the Library API:

```python
def search_files_by_tag_contains(
    self,
    tag_key: str,
    value: str,
    *,
    limit: int | None,
) -> list[dict]:
    """Search for files where tag.value array contains the given value."""
    return self._tags.search_files_by_tag_contains(tag_key, value, limit=limit)
```

#### 3. Component Layer (`nomarr/components/tagging/tag_query_comp.py`)

Updated `get_file_ids_for_mood_tags()` to use CONTAINS matching:

```python
def get_file_ids_for_mood_tags(
    db: Database,
    mood_values: list[str],
    mood_tier: str = "mood-strict",
    library_id: str | None = None,
) -> dict[str, set[str]]:
    """Get file-id sets for many mood values within one mood tier.
    
    Uses CONTAINS matching since mood tags are stored as arrays (e.g.,
    nom:mood-strict = ["aggressive", "happy"]). This allows finding files
    that have a specific mood value within their mood array.
    """
    result: dict[str, set[str]] = {}
    name = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier
    library_ids = _library_file_ids(db, library_id)

    for mood_value in mood_values:
        # Use CONTAINS matching for mood tags (stored as arrays)
        file_docs = cast(
            "list[dict[str, Any]]",
            db.library.search_files_by_tag_contains(name, mood_value, limit=None),
        )
        file_ids = {
            file_doc.get("_id")
            for file_doc in file_docs
            if isinstance(file_doc.get("_id"), str)
        }
        if library_ids is not None:
            file_ids &= library_ids
        result[mood_value] = file_ids

    return result
```

## Testing

### Unit Tests Added

#### 1. Tag Query Component Tests (`tests/unit/components/tagging/test_tag_query_comp.py`)

Added `TestGetFileIdsForMoodTags` class with 3 tests:
- `test_uses_contains_matching_for_mood_tags` - Verifies CONTAINS method is called
- `test_scopes_to_library_when_provided` - Verifies library filtering works
- `test_handles_empty_results` - Verifies empty result handling

#### 2. Database AQL Tests (`tests/unit/persistence/database/test_tags_aql.py`)

Added 2 tests:
- `test_search_files_by_tag_contains_uses_in_operator` - Verifies AQL query structure
- `test_search_files_by_tag_contains_respects_limit` - Verifies limit handling

### Test Results

All tests pass:
- ✅ 47/47 tag_query_comp tests pass
- ✅ 6/6 tags_aql tests pass
- ✅ 37/37 analytics tests pass

## Impact

### Before Fix
- Mood tag presets showed lots of zeros in co-occurrence matrix
- No files matched because exact match failed on array values
- Poor user experience with mood-based analytics

### After Fix
- Mood tags correctly match files containing the mood value
- Co-occurrence matrix shows meaningful data for mood presets
- Consistent behavior across all tag types (regular tags use exact match, mood tags use CONTAINS)

## Architecture Notes

### Why Not Change All Tags to Use CONTAINS?

Regular tags (genre, year, artist) are stored as scalar values:
```json
{
  "name": "genre",
  "value": "Rock"
}
```

These should continue using exact matching because:
1. They're not arrays
2. Exact matching is more efficient
3. It prevents false positives (e.g., "Rock" shouldn't match "Rockabilly")

### Why Mood Tags Use Arrays

Mood tags represent multiple moods per file:
```json
{
  "name": "nom:mood-strict",
  "value": ["aggressive", "happy", "energetic"]
}
```

This design allows:
- Multiple moods per file in a single tag document
- Efficient storage (one edge per file instead of one per mood)
- Natural representation of mood complexity

### Query Strategy

| Tag Type | Storage | Query Method | Example |
|----------|---------|--------------|---------|
| Regular (genre, year) | Scalar | Exact match (`==`) | `tag.value == "Rock"` |
| Mood (nom:mood-*) | Array | CONTAINS (`IN`) | `"aggressive" IN tag.value` |

## Files Modified

1. `nomarr/persistence/database/tags_aql.py` - Added `search_files_by_tag_contains()`
2. `nomarr/persistence/api/library.py` - Exposed new method through Library API
3. `nomarr/components/tagging/tag_query_comp.py` - Updated `get_file_ids_for_mood_tags()`
4. `tests/unit/components/tagging/test_tag_query_comp.py` - Added 3 tests
5. `tests/unit/persistence/database/test_tags_aql.py` - Added 2 tests

## Verification

To verify the fix works in production:

1. **Check mood tag storage:**
```aql
FOR tag IN tags
  FILTER tag.name == "nom:mood-strict"
  LIMIT 5
  RETURN { name: tag.name, value: tag.value, type: TYPEOF(tag.value) }
```

Expected: `value` should be an array like `["aggressive", "happy"]`

2. **Test CONTAINS query:**
```aql
FOR tag IN tags
  FILTER tag.name == "nom:mood-strict" AND "aggressive" IN tag.value
  LIMIT 10
  RETURN { _id: tag._id, value: tag.value }
```

Expected: Should return tags containing "aggressive"

3. **Test co-occurrence endpoint:**
```bash
curl -X POST http://127.0.0.1:8356/api/web/analytics/tag-co-occurrences \
  -H "Content-Type: application/json" \
  -d '{
    "x": [{"key": "nom:mood-strict", "value": "aggressive"}],
    "y": [{"key": "nom:mood-strict", "value": "happy"}]
  }'
```

Expected: Should return non-zero matrix values if files have both moods

## Related Documentation

- [Nomarr Tags Skill](/.opencode/skills/nomarr-tags/SKILL.md) - Tag system architecture
- [Docker Skill](/.opencode/skills/docker/SKILL.md) - Database access and AQL queries
- [Frontend Caching Fix](/frontend/src/features/analytics/components/TagCoOccurrenceGrid/useMatrixCache.ts) - Related frontend improvements
