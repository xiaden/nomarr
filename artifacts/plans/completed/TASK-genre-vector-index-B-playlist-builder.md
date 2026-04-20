# Task: Genre Playlist via Indexed Filter (Part B)

## Problem Statement

`build_genre_playlists` was removed from `playlist_builder_comp.py` when the old sub-collection
approach was discarded. Part A delivered `search_similar_by_genre` on `VectorsTrackColdOperations`
and `genres` stored in the indexed cold docs. This task restores the function using the new
indexed-filter API, then re-wires it into `generate_playlists_wf.py` (`_BUILDERS` dict) and the
component package `__init__.py`. No new persistence methods, endpoints, or front-end changes.

## Phases

### Phase 1: Implement build_genre_playlists in playlist_builder_comp

- [x] Verify `_GENRE_MIN_SONGS` module constant is present in `nomarr/components/navidrome/playlist_builder_comp.py` (expected at line ~34); the value must be `100` — correct it if it is not
    **Verified:** `_GENRE_MIN_SONGS: int = 100` confirmed at line ~34. No change needed.
- [x] Add `build_genre_playlists(db: Database, ctx: NavidromePersonalPlaylistContext) -> list[NavidromePersonalPlaylistEntry]` to `playlist_builder_comp.py`: call `db.tags.get_distinct_tag_values_for_files(ctx["played_file_ids"], "genre")` for genre affinities; for each genre call `db.get_vectors_track_cold(ctx["backbone_id"], ctx["library_key"]).search_similar_by_genre(ctx["centroid"], genre, fetch_limit, nprobe)` using `compute_nlists`/`compute_nprobe` (already imported); build one `NavidromePersonalPlaylistEntry` per genre named `Your {Genre} Mix`; skip genres with fewer than `_GENRE_MIN_SONGS` results; return the list
    **Implemented:** Added `build_genre_playlists` at line 245. Uses 3x over-fetch (matching `build_hidden_gems_playlist`), filters genres below `_GENRE_MIN_SONGS` after search, playlist_type=`genre_{genre.lower()}`, playlist_name=`Your {genre.title()} Mix`.
- [x] Run `lint_project_backend(path="nomarr/components/navidrome")` and fix any errors
    **Clean:** 0 errors, 2 files checked.

### Phase 2: Wire into workflow and component package

- [x] Add `build_genre_playlists` to the import block from `nomarr.components.navidrome.playlist_builder_comp` in `nomarr/workflows/navidrome/generate_playlists_wf.py`
- [x] Add `"genre": build_genre_playlists` to the `_BUILDERS` dict in `generate_playlists_wf.py` (alongside `familiar`, `discovery`, `hidden_gems`, `universal`)
- [x] Add `build_genre_playlists` to the `from .playlist_builder_comp import (...)` block in `nomarr/components/navidrome/__init__.py`
- [x] Add `"build_genre_playlists"` to `__all__` in `nomarr/components/navidrome/__init__.py`
- [x] Run `lint_project_backend(path="nomarr")` and fix any errors

### Phase 3: Document genre in navidrome-plugin

- [x] In `navidrome-plugin/README.md`, add a "Personal Playlists" section after the "How It Works" section: explain the `users` config JSON array format (`username`, `enabled_types`, `max_songs`, `min_songs`), list all valid `enabled_types` values (`familiar`, `discovery`, `hidden_gems`, `universal`, `genre`), and show a worked example JSON snippet
- [x] In `navidrome-plugin/dist/manifest.json`, add a `users` property to `config.schema.properties` with `type: "string"`, title `"Users (JSON)"`, and a description that documents the JSON array format and explicitly names all five valid `enabled_types` values including `genre`
- [x] Add the `users` control to `config.uiSchema.elements` in `manifest.json` after `pp_user_id`

## Completion Criteria

- `build_genre_playlists` is defined in `playlist_builder_comp.py` with the signature `(db: Database, ctx: NavidromePersonalPlaylistContext) -> list[NavidromePersonalPlaylistEntry]`
- It calls `db.get_vectors_track_cold(backbone_id, library_key)` with no `collection_suffix` argument
- It calls `.search_similar_by_genre(centroid, genre, limit, nprobe)` matching the Part A contract
- `_BUILDERS` in `generate_playlists_wf.py` contains `"genre": build_genre_playlists`
- `build_genre_playlists` is exported from `nomarr/components/navidrome/__init__.py` (in both the import and `__all__`)
- `lint_project_backend` reports zero errors
- `navidrome-plugin/README.md` has a Personal Playlists section documenting the `users` JSON format and all five `enabled_types` values
- `manifest.json` `users` property documents the JSON format and names all five valid `enabled_types` values

## References

- Design doc: `plans/dev/genre-vector-index-parts/README.md`
- Contracts ledger (Part A output): `plans/dev/genre-vector-index-parts/README.md`
- Part A plan: `plans/TASK-genre-vector-index-A-persistence-index.md`
- Existing builders for pattern reference: `nomarr/components/navidrome/playlist_builder_comp.py`
