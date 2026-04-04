# Task: Personal Playlist G — Plugin Scrobbler + Scheduler

## Problem Statement

The Navidrome WASM plugin currently implements `SimilarSongsByTrackProvider` only. It needs two new capabilities: a **Scrobbler** that intercepts per-user play events and forwards them to Nomarr's scrobble endpoint (Plan B), and a **Scheduler** that periodically triggers playlist generation (Plan E) and pushes playlists into Navidrome via the Subsonic API. Both are pure relay — no ML, no state beyond config. The single `nomarrPlugin` struct implements all three provider interfaces.

**Prerequisites:** Plan B (scrobble endpoint), Plan E (generate-playlists endpoint)

## Phases

### Phase 1: Scrobbler Capability

- [x] Add config fields to `navidrome-plugin/manifest.json`: `pp_enabled` (boolean, default false), `pp_schedule_cron` (string, default "0 3 * * *"), `pp_user_id` (string, required when pp_enabled is true). Add corresponding `uiSchema` elements. Update top-level description to mention playlist generation.
- [x] Add Go structs for API request/response types in `navidrome-plugin/src/main.go`: `scrobbleTrack` (ID, Title, Duration), `scrobbleRequest` (Username, Track, Timestamp), `generatePlaylistsRequest` (UserID), `playlistResult` (PlaylistType, Name, TrackNdIDs, TrackCount), `generatePlaylistsResponse` (Playlists). JSON tags must match the exact field names from Plans B and E contracts.
- [x] Extract `readConfig() (url string, apiKey string, ok bool)` helper function. Currently `GetSimilarSongsByTrack` reads `nomarr_url` + `nomarr_api_key` inline — extract to shared helper. Refactor `GetSimilarSongsByTrack` to use it (reads `backbone_id` separately).
- [x] Implement `Scrobble(req metadata.ScrobbleRequest) error` method on `nomarrPlugin`. Read config via `readConfig()`. Build `scrobbleRequest` from `req` fields (username, track ID/title/duration, timestamp). POST to `{url}/api/v1/navidrome/scrobble` with `X-API-Key` header via `host.HTTPSend`. Best-effort: on any error, log and return nil — never fail the scrobble event.
- [x] Verify `go vet ./...` passes in `navidrome-plugin/src/` with zero diagnostics.

### Phase 2: Scheduler + Playlist Push

- [x] Implement `generateAndPushPlaylists()` function. Read `pp_user_id`, URL, API key from config. POST `{"user_id": ppUserID}` to `{url}/api/v1/navidrome/generate-playlists`. Parse response. For each `playlistResult`, call `host.SubsonicAPICall("createPlaylist", params)` with `name={playlist.Name}` and repeated `songId={id}` for each track in `TrackNdIDs`. Log each playlist pushed. On error at any stage, log and continue to next playlist.
- [x] Register scheduler in `init()`: after `metadata.Register(...)`, check `pdk.GetConfig("pp_enabled")`. If `"true"`, read `pp_schedule_cron` (default "0 3 * * *"). Call `pdk.ScheduleTask("nomarr-playlist-gen", cronExpr, generateAndPushPlaylists)`. Log cron expression at Info. If not enabled, skip and log at Debug.
- [x] Update `nomarrPlugin` struct doc comment to list all three interfaces. Verify `go vet ./...` passes and WASM build succeeds via `./build.ps1` (or `GOOS=wasip1 GOARCH=wasm go build`).

## Completion Criteria

- `go vet ./...` passes in `navidrome-plugin/src/` with zero diagnostics
- WASM build produces valid binary without errors
- `manifest.json` is valid JSON with `pp_enabled`, `pp_schedule_cron`, `pp_user_id` config fields
- Scrobble method logs but never returns error (best-effort contract)
- Scheduler triggers playlist generation on configured cron and pushes playlists via `createPlaylist`
- Existing `GetSimilarSongsByTrack` behavior unchanged after `readConfig` refactor
- `pp_user_id` is single string for v1 (multi-user scheduling deferred)
