# Tags AQL Operations

Mixin-based split of `TagOperations` — covers tag CRUD, queries, analytics, mood analysis, cleanup, and statistics.

## Responsibilities

- Provide all AQL operations for the `tags` and `song_has_tags` collections
- Split into focused mixins by domain concern
- Compose into a single `TagOperations` class via mixin inheritance

## Key Modules

| Module | Purpose |
|--------|--------|
| `crud.py` | `TagCrudMixin` — find/create tags, set/add/delete song tags, batch tag writes |
| `queries.py` | `TagQueriesMixin` — tag lookup, listing, song-tag queries, mood values, co-occurrence filtering |
| `stats.py` | `TagStatsMixin` — unique rels, value counts, tag frequencies, library-wide aggregates |
| `mood.py` | `TagMoodMixin` — mood distribution, coverage, balance, top pairs, correlation data |
| `analytics.py` | `TagAnalyticsMixin` — year and genre distributions for Collection Overview |
| `cleanup.py` | `TagCleanupMixin` — orphaned tag detection and atomic cascade deletion |

## Patterns

- **Mixin composition**: Each file defines one mixin; the parent `TagOperations` inherits all mixins
- **Graph traversal**: Queries traverse `song_has_tags` edges from `library_files` to `tags` vertices
- **Provenance edges**: Tags may also have `tag_model_output` edges linking to ML model activations
- **Atomic cleanup**: Orphaned tag removal cascades `tag_model_output` edges in a single AQL query

## Access Rule

**Only components may import these modules.** Services, workflows, interfaces, and helpers must not access persistence directly.
