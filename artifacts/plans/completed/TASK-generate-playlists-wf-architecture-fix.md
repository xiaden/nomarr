# Task: Fix generate_playlists_wf Architecture Violations

## Problem Statement

`nomarr/workflows/navidrome/generate_playlists_wf.py` violates nearly every workflow-layer rule:

1. **Raw AQL in the workflow.** Three private functions (`_get_known_artist_tags`, `_get_artist_tags_for_files`, `_get_genre_tags_for_user`) contain direct `db.db.aql.execute()` calls with inline AQL strings. AQL belongs exclusively in `persistence/database/*_aql.py`.

2. **Private helper functions.** The file has 8 private functions (`_generate_familiar`, `_generate_discovery`, `_generate_hidden_gems`, `_generate_genre`, `_generate_universal`, plus the 3 AQL helpers). Workflow instructions mandate: "No private helper functions. The recipe is the workflow function body. If part of a workflow is complex enough to extract, it belongs in a component."

3. **Component-level domain logic in the workflow.** Each `_generate_*` function contains heavy domain logic: ANN vector search with nlists/nprobe computation, candidate filtering/exclusion, artist-set-intersection filtering, stride-based diversified sampling, genre iteration with collection suffix construction. This is component work.

4. **Private cross-module import.** Imports `_sanitize_genre_name` (private) from `ml_vector_maintenance_comp`. Private symbols shouldn't be imported across modules.

**Reference patterns:**
- `promote_and_rebuild_vectors_wf.py` — flat ledger of component calls with step comments, no private helpers
- `tag_query_comp.py` — thin component wrappers around `db.tags.*` persistence methods
- `find_files_matching_tag` component → `db.tags.get_file_ids_matching_tag` persistence

## Phases

### Phase 1: Persistence — Add tag-value query methods to TagOperations
- [x] Add `get_distinct_tag_values_for_files(self, file_ids: list[str], rel: str) -> list[str]` to `TagQueriesMixin` in `nomarr/persistence/database/tags_aql/queries.py` — AQL traversal from file_ids through `song_has_tags` edges to `tags` vertices filtered by `rel`, returning `DISTINCT tag.value`
    **Notes:** Added `get_distinct_tag_values_for_files` after `get_unique_mood_values` in `tags_aql/queries.py` (lines 467-499). AQL traverses song_has_tags edges filtered by rel, returns DISTINCT values. lint_project_backend: 0 errors.
- [x] Add `get_tag_values_grouped_by_file(self, file_ids: list[str], rel: str) -> dict[str, set[str]]` to `TagQueriesMixin` in `nomarr/persistence/database/tags_aql/queries.py` — same traversal but returns `{file_id: file_id, values: [tag.value]}` per file, assembled into a dict
    **Notes:** Added `get_tag_values_grouped_by_file` after `get_distinct_tag_values_for_files` in `tags_aql/queries.py`. AQL subquery per file collects values, Python assembles into dict[str, set[str]]. lint_project_backend: 0 errors.
- [x] Verify both methods are accessible via `db.tags.*` (TagOperations inherits TagQueriesMixin)
    **Notes:** `read_module_api(nomarr.persistence.database.tags_aql)` confirms both methods visible on TagOperations with `inherited: true`: `get_distinct_tag_values_for_files(file_ids, rel) -> list[str]` and `get_tag_values_grouped_by_file(file_ids, rel) -> dict[str, set[str]]`.

### Phase 2: Component — Make _sanitize_genre_name public
- [x] Rename `_sanitize_genre_name` to `sanitize_genre_name` in `nomarr/components/ml/vectors/ml_vector_maintenance_comp.py` and update all internal callers in that file
    **Notes:** Renamed `_sanitize_genre_name` → `sanitize_genre_name` (line 322) and updated internal caller at line 414. Lint clean.
- [x] Update import in `generate_playlists_wf.py` to use `sanitize_genre_name` (temporary — will be replaced in Phase 4, but keeps code working between phases)
    **Notes:** Updated import and usage in `generate_playlists_wf.py` (lines 14 and 278). Lint clean.

### Phase 3: Component — Create playlist_builder_comp.py
- [x] Create `nomarr/components/navidrome/playlist_builder_comp.py` with five public functions that encapsulate the domain logic from the current `_generate_*` private helpers:
  **Notes:** Each function accepts `db: Database` plus the minimal parameters it needs, and returns `list[PlaylistResult]`. Functions use `db.tags.get_distinct_tag_values_for_files()` and `db.tags.get_tag_values_grouped_by_file()` instead of raw AQL. Functions use `db.get_vectors_track_cold()` for ANN search, `compute_nlists`/`compute_nprobe` from helpers, and `db.navidrome_tracks.bulk_resolve_files_to_nd()` for ND resolution. `build_genre_playlists` imports `sanitize_genre_name` from `ml_vector_maintenance_comp` (component→component is allowed lateral import).
      Created `playlist_builder_comp.py` (332 lines) with 5 public functions. All raw AQL replaced with `db.tags.get_distinct_tag_values_for_files()` and `db.tags.get_tag_values_grouped_by_file()`. Lint clean.
- [x] Export all five functions from `nomarr/components/navidrome/__init__.py`
    **Notes:** Added 5 exports to `__init__.py`: `build_familiar_playlist`, `build_discovery_playlist`, `build_hidden_gems_playlist`, `build_genre_playlists`, `build_universal_playlist`. Lint clean.

### Phase 4: Workflow — Rewrite as flat ledger
- [x] Rewrite `generate_playlists_wf.py` to contain only the public `generate_playlists` function as a flat sequence of component calls — no private helpers, no AQL, no `Cursor` import, no `cast`/`Any`/`random` imports
  **Notes:** The workflow calls `compute_taste_profile`, reads plays from `db.navidrome_playcounts.get_top_plays`, filters by `min_play_count`, then dispatches each enabled type to the corresponding `build_*` component function. Final filter removes playlists below `min_songs`. The dispatch loop can remain (it's control flow, not domain logic) but calls component functions directly.
      Rewrote as 121-line flat ledger: 1 public function, 0 private helpers, 0 AQL, 0 `Cursor`/`cast`/`Any`/`random` imports. Uses if/elif dispatch to 5 component builder functions with explicit per-type arguments. Lint clean.

### Phase 5: Validation
- [x] Run `lint-imports` — zero contract violations
    **Notes:** 8 contracts KEPT, 1 BROKEN — the broken contract is a pre-existing violation in `ml_vector_idle_promotion_comp` (component→workflow import at line 129), unrelated to this refactor. All playlist-related imports respect layer boundaries.
- [x] Run `ruff check nomarr/components/navidrome/ nomarr/workflows/navidrome/ nomarr/persistence/database/tags_aql/` — zero errors
    **Notes:** Zero errors across all touched paths.
- [x] Run `mypy nomarr/components/navidrome/ nomarr/workflows/navidrome/ nomarr/persistence/database/tags_aql/` — zero errors
    **Notes:** mypy: "Success: no issues found in 4 source files" (playlist_builder_comp, generate_playlists_wf, queries.py, ml_vector_maintenance_comp).

## Completion Criteria
- `generate_playlists_wf.py` has exactly one public function, zero private helpers, zero AQL strings, zero `db.db.aql.execute` calls
- All AQL lives in `persistence/database/tags_aql/queries.py`
- All domain logic (ANN search, candidate filtering, sampling) lives in `components/navidrome/playlist_builder_comp.py`
- Workflow reads as a flat ledger of component calls with step comments
- lint-imports, ruff, mypy all pass

## References
- Workflow instructions: `.github/instructions/workflows.instructions.md`
- Component instructions: `.github/instructions/components.instructions.md`
- Reference workflow: `nomarr/workflows/platform/promote_and_rebuild_vectors_wf.py`
- Reference component wrapper pattern: `nomarr/components/navidrome/tag_query_comp.py`
- Existing tag persistence: `nomarr/persistence/database/tags_aql/queries.py`
