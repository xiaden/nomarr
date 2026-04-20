# Task: Refactor generate_playlists_wf to Respect Layer Boundaries

## Problem Statement

`generate_playlists_wf.py` violates nearly every workflow architecture rule:

1. **Raw AQL in workflow.** Three private functions (`_get_known_artist_tags`,
   `_get_artist_tags_for_files`, `_get_genre_tags_for_user`) execute AQL directly
   via `db.db.aql.execute`. AQL belongs exclusively in persistence `*_aql.py` modules.

2. **8 private helper functions.** Workflows must be flat recipes with zero private
   helpers. The 5 sub-pipeline functions (`_generate_familiar`, `_generate_discovery`,
   `_generate_hidden_gems`, `_generate_genre`, `_generate_universal`) plus the 3 AQL
   helpers all violate this rule.

3. **Domain logic in workflow.** ANN search + exclusion filtering, artist-based
   filtering, diversified sampling, and genre iteration are component-level work.
   Workflows are ledgers of component calls, not computation engines.

4. **Cross-module private import.** The workflow imports `_sanitize_genre_name` from
   `ml_vector_maintenance_comp` — a private function used outside its module.

### Refactoring Strategy

- **Persistence**: Add 2 generic tag-query methods to `TagQueriesMixin` that replace
  all 3 raw AQL queries. The queries only differ in the `rel` parameter.
- **Component**: Create `playlist_generation_comp.py` in `components/navidrome/` with
  5 public builder functions (one per playlist type) plus shared private helpers.
- **Workflow**: Flatten `generate_playlists` to a recipe of component calls. Remove
  all private functions, AQL, and direct cursor handling.

### Existing Assets

- `TagOperations` (inheriting `TagQueriesMixin`) already has `get_song_tags`,
  `get_file_ids_matching_tag`, etc. — but no "get tag values for a set of file IDs
  by rel" method. The 2 new methods fill this gap.
- `taste_profile_comp.py` already exists in `components/navidrome/` — the new
  component is a natural sibling.
- `find_similar_tracks_wf` is a good reference for proper workflow style in this
  domain (flat recipe, no private helpers).

## Phases

### Phase 1: Persistence — Tag Query Methods for File Sets

- [ ] Add `get_distinct_tag_values_for_files(self, file_ids: list[str], rel: str) -> set[str]` to `TagQueriesMixin` in `tags_aql/queries.py`. AQL: traverse `song_has_tags` from file IDs, filter `tag.rel == @rel`, return `DISTINCT tag.value`. Handle empty `file_ids` with early return.
- [ ] Add `get_tag_values_per_file(self, file_ids: list[str], rel: str) -> dict[str, set[str]]` to `TagQueriesMixin` in `tags_aql/queries.py`. AQL: subquery per file returning `{file_id, values}` grouped. Handle empty `file_ids` with early return.
- [ ] Verify `read_module_api(nomarr.persistence.database.tags_aql)` shows both new methods on `TagOperations`.

### Phase 2: Component — Playlist Builder Functions

- [ ] Make `_sanitize_genre_name` public in `ml_vector_maintenance_comp.py`: rename to `sanitize_genre_name`, update the 1 internal caller at line ~414, and update the import in `generate_playlists_wf.py` (temporary — will be removed in Phase 3 but needed so code doesn't break between phases).
- [ ] Create `nomarr/components/navidrome/playlist_generation_comp.py` with 5 public functions: `build_familiar_playlist`, `build_discovery_playlist`, `build_hidden_gems_playlist`, `build_genre_playlists` (returns list), `build_universal_playlist`. Each accepts `db: Database` + the parameters it needs (centroid, played_file_ids, backbone_id, library_key, max_songs, etc.), calls persistence and vector ops internally, returns `PlaylistResult` or `list[PlaylistResult]`. Shared patterns (ANN search + exclude + resolve-to-nd) extracted into private helpers within the component.
- [ ] Verify `read_module_api(nomarr.components.navidrome.playlist_generation_comp)` shows exactly 5 public functions.

### Phase 3: Workflow — Flatten to Recipe

- [ ] Rewrite `generate_playlists_wf.py`: the `generate_playlists` function body becomes a flat recipe calling component functions. Remove all 8 private helper functions and the AQL helpers section. Remove stale imports (`random`, `cast`, `Any`, `Cursor`). Keep only: component imports, DTO imports, helper imports.
- [ ] Verify `read_module_api(generate_playlists_wf)` shows only `generate_playlists` — zero private functions visible.

### Phase 4: Verification

- [ ] Lint all affected layers: `nomarr/persistence`, `nomarr/components/navidrome`, `nomarr/workflows/navidrome`. Zero errors required.
- [ ] Run existing tests. Update `tests/` if any test directly referenced removed private functions or changed signatures.

## Completion Criteria

- `generate_playlists_wf.py` contains exactly 1 public function, 0 private functions, 0 AQL queries
- All AQL lives in `tags_aql/queries.py` persistence methods
- All domain logic (ANN search, filtering, sampling) lives in `playlist_generation_comp.py`
- `_sanitize_genre_name` renamed to public `sanitize_genre_name`
- Lint passes on persistence, components, and workflows layers
- No `db.db.aql.execute` calls anywhere in workflows

## References

- `find_similar_tracks_wf.py` — reference for proper workflow style in this domain
- `.github/instructions/workflows.instructions.md` — recipe rule, no private helpers
- `.github/instructions/components.instructions.md` — heavy domain logic belongs here
- `.github/instructions/persistence.instructions.md` — AQL belongs here
