# Task: Schema Refactor v1 — Part F Tag Queries & Constraints

## Problem Statement
Add missing indexes to `tag_model_output` edge collection, update library-filtered tag queries to use `library_contains_file` edge traversal (depends on Plan B), and create Pydantic models for type-safe tag operations.

## Phases

### Phase 1: Add Missing Indexes to tag_model_output
- [x] Add indexes `["_from"]` and `["_from", "_to"]` unique to `V021_schema_refactor_v1.py` (existing `["_to"]` remains)
- [x] Add same indexes to `arango_bootstrap_comp.py` for idempotent startup
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 2: Create Tag-Related Pydantic Models
- [x] Create `nomarr/persistence/models/tag.py` with `Tag(ArangoDocument)`: `rel: str`, `value: str|int|float|bool`
- [x] Add `SongHasTagsEdge(ArangoEdge)` — bare edge, no properties
- [x] Add `TagModelOutputEdge(ArangoEdge)` with `score: float`, `created_at`, `updated_at`
- [x] Export from `nomarr/persistence/models/__init__.py`
- [x] Run `lint_project_backend(path="nomarr/persistence/models")`

### Phase 3: Update Library-Filtered Tag Queries — Analytics
- [x] Update `get_year_distribution()` in `tags_aql/analytics.py` — replace `file.library_id == @library_id` with `FOR file IN OUTBOUND @library_id library_contains_file`
- [x] Update `get_genre_distribution()` — same pattern
- [x] Run `lint_project_backend(path="nomarr/persistence/database/tags_aql")`
  **Notes:** Depends on Plan B — `library_contains_file` edge must be populated

### Phase 4: Update Library-Filtered Tag Queries — Mood
- [x] Update `get_mood_distribution_data()` in `tags_aql/mood.py`
- [x] Update `get_mood_coverage()`, `get_mood_balance()`, `get_top_mood_pairs()` in mood.py
- [x] Run `lint_project_backend(path="nomarr/persistence/database/tags_aql")`

### Phase 5: Update Library-Filtered Tag Queries — Stats
- [x] Update `get_library_stats()` in `tags_aql/stats.py`
- [x] Run `lint_project_backend(path="nomarr/persistence/database/tags_aql")`

### Phase 6: Update Library-Filtered Tag Queries — Queries
- [x] Update `get_file_ids_for_tags()`, `get_file_ids_for_mood_tags()` in `tags_aql/queries.py`
- [x] Run `lint_project_backend(path="nomarr/persistence/database/tags_aql")`

### Phase 7: Review tag_model_output_aql.py
- [x] Review for potential traversal optimizations
    **Notes:** No changes needed. Module operates on tag/output _id values directly, no library_id filters. Index usage is optimal: _from index for tag lookups, _to index for output lookups.
- [x] Run `lint_project_backend(path="nomarr/persistence/database")`
    **Notes:** Fixed one mypy error in V021 migration (line 398): Added explicit list[str] type annotation for vector_collections

### Phase 8: Final Verification
- [x] Run full `lint_project_backend()`
    **Notes:** lint_project_backend(check_all=True) passes with 0 errors
- [x] Verify migration imports cleanly
    **Notes:** V021_schema_refactor_v1 imports cleanly

## Completion Criteria
1. `lint_project_backend()` passes with zero errors
2. `tag_model_output` has 3 indexes: `["_from"]`, `["_to"]`, `["_from", "_to"]` unique
3. All library-filtered queries use `library_contains_file` edge traversal
4. Pydantic models exist in `persistence/models/` and are exported

## Decisions Made
| Decision | Rationale |
|----------|----------|
| `song_has_tags` indexes unchanged | Already has all 3 standard edge indexes |
| Use `OUTBOUND @library_id library_contains_file` | Edge direction: `libraries → library_files` |
| TagModelOutputEdge keeps timestamps | Existing data has them; removal is Plan G cleanup |
| Index in both migration and bootstrap | Migration for upgrades; bootstrap for new installs |

## Dependencies
- **Plan A:** Created `tag_model_output` edge collection with only `["_to"]` index
- **Plan B (blocking for Phases 3-6):** Migrates `library_files.library_id` to `library_contains_file` edges
