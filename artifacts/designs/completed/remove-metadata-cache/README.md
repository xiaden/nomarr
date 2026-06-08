# Remove Metadata Cache

## Overview

Remove embedded metadata cache fields (artist, album, title, artists, labels, genres, year) from the library_files collection. The tags collection is the authoritative source of truth; embedded fields are a read cache that causes consistency bugs.

## Execution Rounds

### Round 1: Foundation
- **Plan A**: Tag Hydration Layer
  - Create `tag_hydration_comp.py` with metadata extraction from tags
  - Batch + single-file hydration functions
  - Unit tests

### Round 2: Migration
- **Plan B**: Migrate Readers
  - Update all read sites to use hydration layer
  - Migrate title search to tag-based search
  - Remove dead code

### Round 3: Cleanup
- **Plan C**: Remove Writers
  - Remove embedded field writes from 5 locations
  - Delete `metadata_cache_comp.py` and `rebuild_metadata_cache_wf.py`

### Round 4: Schema
- **Plan D**: Schema Cleanup & Test Repair
  - Remove 7 fields from `ALLOWED_FILE_FIELDS`
  - Update/remove tests for deleted functions
  - Verify full test suite

## Dependencies

```
A → B → C → D
```

Each plan depends on the previous plan being complete.

## Key Files

- `nomarr/components/library/tag_hydration_comp.py` (new, Plan A)
- `nomarr/components/library/library_file_query_comp.py` (Plan B)
- `nomarr/components/navidrome/descriptor_match_comp.py` (Plan B)
- `nomarr/workflows/library/sync_file_to_library_wf.py` (Plan C)
- `nomarr/components/metadata/metadata_cache_comp.py` (delete, Plan C)
- `nomarr/persistence/database/library_files_aql.py` (Plan D)
