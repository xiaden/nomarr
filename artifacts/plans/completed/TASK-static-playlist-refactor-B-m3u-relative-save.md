# Task: Static Playlist Refactor — M3U Relative Path Save

## Problem Statement

**Prerequisite:** `TASK-static-playlist-refactor-A-navidrome-push`

The `generate_static_playlist_workflow` builds M3U content using absolute container paths from the `library_files.path` field. These paths are internal to the Docker container (e.g. `/media/Music/Artist/Album/song.flac`) and break when the volume is mapped differently on the host or in another application.

This plan fixes M3U generation to use **relative paths** (relative to the library root) and saves the `.m3u` file **server-side** to a configurable output directory instead of returning content for browser download. A new `m3u_output_path` DynamicConfig key controls where playlists are written.

The M3U file becomes a portable artifact that works regardless of mount point, since media players resolve relative paths from the playlist file's location.

## Phases

### Phase 1: Add `m3u_output_path` config key

- [x] Add `m3u_output_path: str` field to `DynamicConfig` with default `""` (empty = disabled)
- [x] Add `FieldMeta` entry for `m3u_output_path` in `DYNAMIC_FIELD_META` with label "M3U Output Path", description "Directory path (relative to library root) where M3U playlist files are saved. Leave empty to disable M3U file output.", ui_type `text`
- [x] Verify drift guard assertion passes (DynamicConfig fields == DYNAMIC_FIELD_META keys)

### Phase 2: Fix M3U path generation to relative

- [x] Update `_build_m3u` in `generate_static_playlist_wf.py` to accept `library_root: str` parameter and emit paths relative to that root (strip library_root prefix, use forward slashes)
- [x] Update `generate_static_playlist_workflow` to accept `library_root: str` and pass it to `_build_m3u`
- [x] Update `StaticPlaylistResult` to add `saved_path: str | None` field (None when M3U output is disabled)

### Phase 3: Server-side M3U file save

- [x] Update `generate_static_playlist_workflow` to write the M3U content to `{library_root}/{m3u_output_path}/{playlist_name}.m3u` when `m3u_output_path` is non-empty, sanitizing the filename
- [x] Update `NavidromeService.generate_static_playlist` to read `m3u_output_path` from config and pass `library_root` + `m3u_output_path` to workflow
- [x] Handle edge cases: directory creation, filename sanitization, overwrite behavior
    **Notes:** Directory creation, filename sanitization, and overwrite behavior all handled in m3u_comp.save_m3u (mkdir parents=True, _UNSAFE_FILENAME_RE, silent overwrite).

### Phase 4: Update frontend to reflect server-side save

- [x] Update `StaticPlaylistResponse` interface in frontend to include `saved_path: string | null`
- [x] Update VectorSearchPage to show "M3U saved to {path}" notification instead of browser download when `saved_path` is present, keep download fallback when `saved_path` is null
    **Skipped:** VectorSearchPage already uses push-to-Navidrome from Plan A. The static M3U endpoint is retained for API consumers but the page no longer calls it. No page change needed.
- [x] Build the frontend.

### Phase 5: Validation

- [x] Run `lint_project_backend` on all touched Python paths — zero errors
- [x] Run `lint_project_frontend` — zero errors
- [x] Verify `lint-imports` has no new contract violations

## Completion Criteria

- M3U playlists use relative paths (relative to library root, forward slashes)
- M3U files are saved server-side to `{library_root}/{m3u_output_path}/` when config is set
- `m3u_output_path` is a DynamicConfig field editable via web UI
- Frontend shows save confirmation instead of triggering broken browser download
- `StaticPlaylistResult` carries `saved_path` for UI feedback
- All linters pass with zero errors

## References

- Sibling: `TASK-static-playlist-refactor-A-navidrome-push.md` — Navidrome push via IDs (must be done first)
- `generate_static_playlist_wf.py` — Current M3U generation with absolute paths
- `config_schema.py` — `DynamicConfig` + `DYNAMIC_FIELD_META` + drift guard pattern
- `StaticPlaylistResult` — Current DTO (playlist_name, m3u_content, track_count, missing_ids)
