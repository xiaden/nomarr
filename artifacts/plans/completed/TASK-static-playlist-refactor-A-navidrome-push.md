# Task: Static Playlist Refactor — Navidrome Push

## Problem Statement

The vector search "Generate Playlist" button currently generates an M3U file with absolute container paths and triggers a browser download. This is doubly broken: (1) the M3U paths are container-internal and don't resolve on mapped volumes, and (2) the service already silently pushes to Navidrome via Subsonic `createPlaylist.view` using song IDs — the correct approach — but the user never sees this result.

This plan introduces `NavidromeStaticPlaylistResult` as the platform-specific DTO for Navidrome playlist pushes from vector search. The frontend button becomes "Push to Navidrome" (greyed out when Navidrome is not configured), defaulting the playlist name to "Songs like {songname}". The Navidrome push result (playlist ID, resolved tracks, unresolved tracks) is surfaced to the user instead of downloading a broken M3U file.

The existing `StaticPlaylistResult` (M3U) is retained but will be fixed in a sibling plan (Part B) to use relative paths and save server-side via a new `m3u_output_path` config key.

**Why platform-prefixed DTOs:** Nomarr will eventually push playlists to Plex, Jellyfin, and other platforms. Each has different track ID schemes (Navidrome nd_id, Plex ratingKey, Jellyfin ItemId). `NavidromeStaticPlaylistResult` establishes the naming convention for platform-specific results.

## Phases

### Phase 1: Define DTO and expose Navidrome availability

- [x] Add `NavidromeStaticPlaylistResult` TypedDict to `navidrome_dto.py` with fields: `playlist_name: str`, `playlist_id: str`, `track_nd_ids: list[str]`, `unresolved_file_ids: list[str]`
- [x] Export `NavidromeStaticPlaylistResult` from `dto/__init__.py`
- [x] Add `is_navidrome_configured` method to `NavidromeService` that returns `bool` (checks if url+user+password are all non-empty without attempting connection)
- [x] Add web endpoint `GET /api/web/navidrome/status` returning `{"configured": bool}` for the frontend to gate the push button

### Phase 2: Update service and push workflow

- [x] Add `push_static_playlist` method to `NavidromeService` that takes `file_ids` and `playlist_name`, calls `push_playlist` workflow, resolves nd_ids, and returns `NavidromeStaticPlaylistResult`
- [x] Update `generate_static_playlist` service method to remove its silent Navidrome push (no longer embedded — the push is now a separate explicit action)

### Phase 3: Add web endpoint and update frontend API

- [x] Add web endpoint `POST /api/web/navidrome/playlists/push` accepting `file_ids` and `playlist_name`, returning the new result shape
- [x] Add `pushStaticPlaylist` function and `NavidromeStaticPlaylistResult` interface to `frontend/src/shared/api/navidrome.ts`
- [x] Add `useNavidromeStatus` hook or inline fetch in VectorSearchPage to check `/api/web/navidrome/status` on mount

### Phase 4: Update VectorSearchPage UI

- [x] Replace "Generate Navidrome Playlist" button logic: call `pushStaticPlaylist` instead of `generateStaticPlaylist`, default playlist name to "Songs like {artist} - {title}"
- [x] Grey out the push button with tooltip "Navidrome not configured" when status shows `configured: false`
- [x] Show success notification with playlist name and track count on push completion, error notification on failure

### Phase 5: Validation

- [x] Run `lint_project_backend` on all touched Python paths — zero errors
- [x] Run `lint_project_frontend` — zero errors
- [x] Verify `lint-imports` has no new contract violations
    **Notes:** Pre-existing violation: ml_vector_idle_promotion_comp -> workflows.platform. Not introduced by this plan.

## Completion Criteria

- Vector search push button sends file_ids to Navidrome via Subsonic API and surfaces the result to the user
- Button is disabled with explanatory tooltip when Navidrome is not configured
- Playlist name defaults to "Songs like {artist} - {title}" from the selected track
- `NavidromeStaticPlaylistResult` carries platform-specific data (nd_ids, playlist_id, unresolved file_ids)
- No browser M3U download in the push flow (M3U is a separate concern for Part B)
- All linters pass with zero errors

## References

- Sibling: `TASK-static-playlist-refactor-B-m3u-relative-save.md` — Fix M3U to relative paths, save server-side via `m3u_output_path` config
- Prior: `plans/completed/TASK-personal-playlist-dto-formalization.md` — Established `NavidromePersonalPlaylist*` DTO naming convention
- `push_playlist_wf.py` — Existing push workflow using Subsonic `createPlaylist.view` with song IDs
- `SubsonicClient.create_or_replace_playlist` — Uses repeated `songId` params, already ID-based
