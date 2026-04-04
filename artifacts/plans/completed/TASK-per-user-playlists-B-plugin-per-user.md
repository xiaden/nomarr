# Task: Plugin Per-User Config and Dispatch

## Problem Statement

The Navidrome plugin currently supports only a single user for personal playlists via a flat `pp_user_id` config field. Playlist creation calls `host.SubsonicAPICall("createPlaylist?name=...&songId=...")` without `?u=username`, so playlists are created under the plugin's admin context rather than the target user's account. The plugin also sends `backbone_id` to the Nomarr API, but backbone selection should stay server-side (PDK config is static JSON Schema — no dynamic dropdowns).

This plan refactors the plugin to support multiple users via a `users` JSON Schema array in `manifest.json`, where each entry has a `username` and optional per-user prefs (`enabled_types`, `max_songs`, `min_songs`). The dispatch loop iterates users, sends per-user prefs to the Nomarr API (Plan A contract), and pushes playlists via Subsonic API with `?u=username` for correct ownership. Existing playlists are found by name and updated rather than duplicated.

**Prerequisite:** TASK-per-user-playlists-A-api-passthrough

## Phases

### Phase 1: Manifest config, Go types, and Subsonic helpers

- [x] Update `navidrome-plugin/manifest.json`: remove `backbone_id` and `pp_user_id` from `config.schema.properties` and their `uiSchema` elements. Add a `users` property as JSON Schema array of objects with `username` (string, required), `enabled_types` (array of enum strings, optional, default all 5 types), `max_songs` (integer, optional, default 50), `min_songs` (integer, optional, default 5). Add uiSchema control for `#/properties/users`. Keep `nomarr_url`, `nomarr_api_key`, `pp_enabled`, `pp_schedule_cron` as global config.
    **PreExisting:** manifest.json already has `users` array property with all required fields (username, enabled_types, max_songs, min_songs), correct enum values, defaults, and uiSchema control. `backbone_id` and `pp_user_id` are absent. No changes needed.
- [x] In `navidrome-plugin/src/main.go`, add a `userConfig` struct with `Username string`, `EnabledTypes []string` (json `enabled_types,omitempty`), `MaxSongs *int` (json `max_songs,omitempty`), `MinSongs *int` (json `min_songs,omitempty`). Update `generatePlaylistsRequest` to add matching optional fields. Use `*int` pointers so zero-vs-absent is distinguishable with `omitempty`.
    **PreExisting:** `userConfig` struct already present with Username/EnabledTypes/MaxSongs/MinSongs using correct json tags and *int pointers. `generatePlaylistsRequest` already has matching optional fields. No changes needed.
- [x] Add `subsonicCallAs(endpoint string, username string) (string, error)` helper that builds URI as `fmt.Sprintf("/rest/%s?u=%s", endpoint, username)` and delegates to `host.SubsonicAPICall`. Follows the LBZ plugin pattern.
    **PreExisting:** `subsonicCallAs` already present. Implementation uses `url.QueryEscape(username)` which is a correct improvement over the bare string spec — encodes special characters in usernames safely.
- [x] Add `findExistingPlaylists(username string) (map[string]string, error)` helper that calls `subsonicCallAs("getPlaylists", username)`, parses XML response using string operations to extract playlist name→ID map. Handle XML attribute escaping. Return empty map on failure with warning log (graceful degradation).
    **PreExisting:** `findExistingPlaylists` already present with full string-based XML parser. Handles self-closing and open tag forms, uses `xmlAttr`/`xmlDecodeEntities` helpers, returns empty map with warning on any failure. No `encoding/xml` used.
  **Warning:** TinyGo/WASM cannot use `encoding/xml`. String-based parser must handle both self-closing and open+close tag forms.
- [x] Verify the project compiles: `cd navidrome-plugin/src && GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o ../dist/plugin.wasm .`
    **Verified:** `.\build.ps1` ran successfully and produced dist/plugin.wasm. No compile errors.

### Phase 2: Multi-user dispatch loop

- [x] Rewrite `generateAndPushPlaylists()`: read `users` config via `pdk.GetConfig("users")`, unmarshal JSON into `[]userConfig`. If empty or missing, log warning and return. Iterate each user — build `generatePlaylistsRequest` with `UserID = user.Username` and user's prefs (only non-nil fields via `omitempty`), POST to Nomarr API. If one user fails, log error and continue to next (error isolation).
- [x] Within per-user loop after API response: call `findExistingPlaylists(user.Username)` to get name→ID map. For each playlist in response, if name exists in map use `createPlaylist?playlistId={id}&songId=...` (update), otherwise use `createPlaylist?name={name}&songId=...` (create new). All calls via `subsonicCallAs` for `?u=username` ownership. URL-encode names and IDs. Log each push with type, name, track count, and create/update status.
- [x] Verify project compiles and `manifest.json` is well-formed JSON. Run `./build.ps1` to produce `dist/plugin.wasm`.

## Completion Criteria

- `./build.ps1` succeeds producing `dist/plugin.wasm`
- `manifest.json` has no `backbone_id`, no `pp_user_id`, has `users` array schema
- `generateAndPushPlaylists` reads `users` config and iterates per user
- API request body includes `user_id` plus optional `enabled_types`/`max_songs`/`min_songs` matching Plan A contract
- All Subsonic calls use `?u=username` for per-user ownership
- Existing playlists found by name are updated, not duplicated
- Single-user failure does not abort other users

## References

- Design doc: `plans/dev/design-per-user-playlists.md`
- Plan A: `plans/TASK-per-user-playlists-A-api-passthrough.md`
- Parts README: `plans/dev/per-user-playlists-parts/README.md`
- Contracts ledger: `plans/dev/per-user-playlists-parts/CONTRACTS.md`
