# Task: Personal Playlist — Navidrome Sync Rewrite

## Problem Statement

The current `sync_song_map_wf.py` populates a flat `navidrome_song_map` document collection with simple nd_id ↔ file_id mappings. The personal playlist feature requires graph-based sync that writes to `navidrome_tracks` vertices, `has_nd_id` edges, and captures per-user play counts as `has_plays` edges. This plan replaces the old workflow with `sync_navidrome_wf.py`, migrates all callers of `db.navidrome_song_map` to `db.navidrome_tracks.resolve_*` methods, removes the deprecated operations registration, and adds new persistence methods needed for bulk reverse-lookups and orphan cleanup.

All persistence calls use concrete Plan A contracts plus new methods added by this plan.

**Prerequisite:** TASK-personal-playlist-A-graph-collections

## Phases

### Phase 1: New Workflow + Persistence Additions

- [x] Add methods to `NavidromeTracksOperations` in `nomarr/persistence/database/navidrome_tracks_aql.py`: `bulk_resolve_files_to_nd(file_ids: list[str]) -> dict[str, str]` (reverse traversal of `has_nd_id` edges), `get_all_track_keys() -> list[str]`, and `delete_tracks_cascade(nd_ids: list[str]) -> int` (removes vertices + all connected `has_nd_id` and `has_plays` edges via AQL).
- [x] Create `NdSyncResult` TypedDict in `nomarr/helpers/dto/navidrome_dto.py` with fields: `total_songs: int`, `resolved: int`, `unresolved: int`, `tracks_upserted: int`, `play_edges_upserted: int`, `orphans_removed: int`, `duration_ms: int`.
- [x] Create `nomarr/workflows/navidrome/sync_navidrome_wf.py` with `sync_navidrome(client: SubsonicClient, path_prefix_map: list[tuple[str, str]], db: Database, user_id: str) -> NdSyncResult`. Preserve album walk pattern from old WF (`getAlbumList2` paginated, `getAlbum` per album). Collect nd_id, path, playCount, played from each Child. Remap paths, resolve via `db.library_files`, call `db.navidrome_tracks.bulk_upsert_tracks`, `bulk_ensure_file_links`, `db.navidrome_playcounts.ensure_user`, `bulk_upsert_play_edges`. Run orphan cleanup (diff DB track keys vs seen set, cascade-delete removed). Return `NdSyncResult`.
- [x] Verify `lint_project_backend` passes on `nomarr/workflows/navidrome`, `nomarr/persistence/database`, `nomarr/helpers/dto` with zero errors.

### Phase 2: Caller Migration + Cleanup

- [x] Update `NavidromeService` in `nomarr/services/domain/navidrome_svc.py`: replace `sync_song_map` method to call `sync_navidrome` from the new workflow, passing `user_id` from config. Rename method to `sync_navidrome`. Update return type to `NdSyncResult`.
- [x] Update `find_similar_tracks_wf.py`: replace `db.navidrome_song_map.lookup_by_nd_id` with `db.navidrome_tracks.resolve_nd_to_file`, replace `db.navidrome_song_map.bulk_lookup_by_file_ids` with `db.navidrome_tracks.bulk_resolve_files_to_nd`.
- [x] Update `push_playlist_wf.py`: replace `db.navidrome_song_map.bulk_lookup_by_file_ids` with `db.navidrome_tracks.bulk_resolve_files_to_nd`.
- [x] Update sync endpoint handlers in `navidrome_v1_if.py` and web `navidrome_if.py` to call renamed service method `sync_navidrome` and map `NdSyncResult` fields to response.
- [x] Remove `navidrome_song_map` registration from `nomarr/persistence/db.py` (delete import + `self.navidrome_song_map = ...` line). Delete `sync_song_map_wf.py`. Delete `navidrome_song_map_aql.py`.
- [x] Update tests: rewrite `test_sync_song_map_wf.py` as `test_sync_navidrome_wf.py`; update mocks in `test_find_similar_tracks_wf.py` and `test_push_playlist_wf.py` from `db.navidrome_song_map.*` to `db.navidrome_tracks.*`.
- [x] Verify `lint_project_backend` (full workspace) passes with zero errors. Confirm `grep -r "navidrome_song_map" nomarr/` returns zero hits.

## Completion Criteria

- New `sync_navidrome_wf.py` replaces old `sync_song_map_wf.py` with graph-based writes
- Play counts captured from Subsonic `Child.playCount`/`played` as `has_plays` edges
- Orphan cleanup removes tracks no longer in Navidrome
- All callers of `db.navidrome_song_map` migrated to `db.navidrome_tracks.resolve_*`
- Old `navidrome_song_map_aql.py`, `sync_song_map_wf.py` deleted; registration removed from `db.py`
- `NdSyncResult` TypedDict with sync statistics available downstream
- `lint_project_backend` passes with zero errors; no `navidrome_song_map` references remain in `nomarr/`

## References

- Design doc: `plans/dev/design-personal-playlist.md` (sync data path section)
- Contracts ledger: `plans/dev/personal-playlist-parts/CONTRACTS.md`
- Existing workflow: `nomarr/workflows/navidrome/sync_song_map_wf.py` (album walk pattern)
- Prerequisite: `plans/TASK-personal-playlist-A-graph-collections.md`
