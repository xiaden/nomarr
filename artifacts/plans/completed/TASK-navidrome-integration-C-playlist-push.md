# Task: Navidrome Integration C — Playlist Push & Utilities

## Problem Statement

With the Subsonic client and bidirectional song index from Plan A in place, Nomarr can
optionally push generated playlists directly to Navidrome via the Subsonic API, instead
of relying on file-drop or manual copy. Additionally, Nomarr can trigger a Navidrome
library rescan after tag write-backs, and expose Navidrome API connection settings in
the frontend with a connection test.

These are quality-of-life features that make the Nomarr–Navidrome integration more
seamless. They are tertiary to the Instant Mix capability (Plans A + B).

**Prerequisite:** TASK-navidrome-integration-A-similarity-api

### Design Decisions

**Service-level fan-out.** Existing playlist generation workflows
(`generate_smart_playlist_wf`, `generate_static_playlist_wf`) remain unchanged — they
return playlist structures and M3U content respectively. `NavidromeService` does the
fan-out: call the generation workflow, then optionally call the push workflow if the
Subsonic client is available. Workflows never check config or skip conditionally; the
service makes all “call or don’t call” decisions.

**Smart playlist push as evaluated snapshots.** The Subsonic API only supports static
playlist creation (list of song IDs), not rule-based smart playlists. When pushing a
smart playlist via the API, the service executes the filter query to get matching file
IDs, resolves them to Navidrome song IDs, and pushes the result as a static Navidrome
playlist. The `.nsp` file‑write path is kept as the primary output (Navidrome evaluates
rules natively); the API push is an optional parallel action.

**Playlist create-or-replace via `createPlaylist`.** The Subsonic `createPlaylist`
endpoint handles both creation and full replacement: pass `name` + `songId` params to
create; pass `playlistId` + `name` + `songId` to replace all songs. `songId` uses
Subsonic’s repeated-parameter convention (`songId=1&songId=2&songId=3`), not a list.

**Navidrome-specific `startScan` extension.** Per the official Subsonic spec, `startScan`
takes no extra parameters. Navidrome extends it with an optional `fullScan` boolean.
The client accepts this parameter but documents it as Navidrome-specific.

**Rescan wired at interface level.** The rescan trigger is called from the
`reconcile_library_tags` endpoint after tag writes complete, not from inside the
tagging workflow itself. This keeps the workflow pure and the integration decision in
the interface/service layer.

## Phases

### Phase 1: Playlist Push Workflow

- [x] Create `nomarr/workflows/navidrome/push_playlist_wf.py` — workflow `push_playlist(db: Database, client: SubsonicClient, playlist_name: str, file_ids: list[str]) -> PushPlaylistResult` that: (1) resolves Nomarr file_ids to Navidrome song IDs via `db.navidrome_song_map.bulk_lookup_by_file_ids()`, (2) calls `client.get_playlists()` to find existing playlist by name (case-insensitive match), (3) calls `client.create_or_replace_playlist(name, resolved_ids, playlist_id)` where `playlist_id` is set if match found, (4) returns result DTO with resolved_count, unresolved_count, playlist_id. Logs warnings for unresolved files
    **Notes:** Created nomarr/workflows/navidrome/push_playlist_wf.py (100 lines) with push_playlist(db, client, playlist_name, file_ids) -> PushPlaylistResult. Added PushPlaylistResult DTO to navidrome_dto.py (resolved_count, unresolved_count, playlist_id). Workflow: bulk_lookup_by_file_ids for ID resolution, get_playlists for name match, create_or_replace_playlist for push. Logs warnings for unresolved files, returns empty result if no IDs resolve. lint_project_backend: 0 errors in new files (5 pre-existing mypy errors in navidrome_song_map_aql.py).
- [x] Update `NavidromeService.generate_playlist()` to also call `push_playlist` after `generate_smart_playlist_workflow` when `self._client` is not None — execute the smart playlist filter query via `execute_smart_playlist_filter` to get file IDs for the push. Update `generate_static_playlist()` similarly to push after generation when client is available
    **Notes:** Updated navidrome_svc.py: added imports for push_playlist, PushPlaylistResult, parse_smart_playlist_query, execute_smart_playlist_filter, logging. generate_playlist() now parses query, executes filter, and pushes evaluated snapshot when self._client is not None. generate_static_playlist() now pushes file_ids when client available. Both wrap push in try/except logging failures. lint_project_backend: 0 errors in navidrome_svc.py (5 pre-existing in navidrome_song_map_aql.py).
- [x] Write unit tests for `push_playlist_wf` with mock SubsonicClient responses (create new, replace existing, partial resolution); run `lint_project_backend`
    **Notes:** Created tests/unit/workflows/navidrome/test_push_playlist_wf.py (119 lines, 5 tests). Test classes: TestPushPlaylistCreateNew (create new, no match among existing), TestPushPlaylistReplaceExisting (case-insensitive name match), TestPushPlaylistPartialResolution (partial resolution pushes resolved only, no resolvable IDs skips push). All 5 tests pass. lint_project_backend: 0 errors in test file.

### Phase 2: Rescan Trigger & Frontend Config

- [x] Create `nomarr/components/navidrome/rescan_trigger_comp.py` — function `trigger_rescan(client: SubsonicClient, full_scan: bool = False) -> bool` that calls `client.start_scan(full_scan)` and returns True on success. Add `NavidromeService.trigger_rescan()` method that calls this when `self._client` is not None. Wire into `reconcile_library_tags` endpoint in `library_if.py` by calling `navidrome_service.trigger_rescan()` after `tagging_service.reconcile_library()` completes
    **Notes:** Created nomarr/components/navidrome/rescan_trigger_comp.py (37 lines) with trigger_rescan(client, full_scan=False) -> bool. Added NavidromeService.trigger_rescan() method in navidrome_svc.py (import as _do_rescan, delegates to component when _client not None). Wired into reconcile_library_tags in library_if.py: added NavidromeService TYPE_CHECKING import (line 44), navidrome_service param with Depends(get_navidrome_service) (line 579), trigger_rescan call after reconcile (line 603-604). lint_project_backend: 0 errors in modified files (5 pre-existing in navidrome_song_map_aql.py).
- [x] Add `POST /api/web/navidrome/ping` endpoint to `navidrome_if.py` — reads API credentials from current config via `ConfigService`, constructs a temporary `SubsonicClient`, calls `client.ping()`, returns `{"ok": true}` or `{"ok": false, "error": "..."}`. This supports the frontend connection test button
    **Notes:** Added PingResponse model to navidrome_types.py (ok: bool, error: str | None). Added NavidromeService.ping() method in navidrome_svc.py — constructs client via _get_client(), calls client.ping(), returns (ok, error_message) tuple. Added POST /api/web/navidrome/ping endpoint in navidrome_if.py using asyncio.to_thread. Endpoint calls navidrome_service.ping() and returns PingResponse. Architecture respected: interface calls service, no direct component imports. lint_project_backend: 0 errors in navidrome_if.py and navidrome_svc.py.
- [x] Update the frontend Navidrome config section (`frontend/src/features/navidrome/`) to include URL, username, and password text fields bound to the config API, with a "Test Connection" button that calls the ping endpoint; run `lint_project_frontend`
    **Notes:** Created ApiSettingsPanel.tsx with URL/user/password fields, Test Connection button via pingNavidrome(). Added navidrome_api_url/user/password to both GET and POST editable_keys whitelists in config_if.py. Frontend lint clean.

## Completion Criteria

- Smart and static playlist generation in `NavidromeService` optionally pushes to Navidrome via `createPlaylist` when the Subsonic client is configured, with no changes to existing generation workflows
- Tag reconciliation triggers an incremental Navidrome rescan when API is configured, wired at the interface level
- Frontend exposes Navidrome API config fields (URL, username, password) with a working connection test button
- `lint_project_backend` and `lint_project_frontend` pass with zero errors

## References

- Prerequisite: `plans/TASK-navidrome-integration-A-similarity-api.md`
- NavidromeService: `nomarr/services/domain/navidrome_svc.py`
- Existing playlist workflows: `nomarr/workflows/navidrome/generate_smart_playlist_wf.py`, `nomarr/workflows/navidrome/generate_static_playlist_wf.py`
- Filter engine: `nomarr/workflows/navidrome/filter_engine_wf.py`
- Tag reconciliation endpoint: `nomarr/interfaces/api/web/library_if.py` (`reconcile_library_tags`)
- Frontend navidrome features: `frontend/src/features/navidrome/`
- Subsonic API spec: <http://www.subsonic.org/pages/api.jsp>
- Part A (prerequisite): `plans/TASK-navidrome-integration-A-similarity-api.md`
- Part B (WASM plugin): `plans/TASK-navidrome-integration-B-wasm-plugin.md`
