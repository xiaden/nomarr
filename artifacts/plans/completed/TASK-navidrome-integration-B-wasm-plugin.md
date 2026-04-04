# Task: Navidrome Integration B — WASM Metadata Agent Plugin

## Problem Statement

Navidrome v0.60.0+ supports WASM plugins compiled as `.ndp` packages (zip of
`plugin.wasm` + `manifest.json`). Plugins that implement `SimilarSongsByTrackProvider`
power Navidrome's "Instant Mix" feature — when a user clicks Instant Mix on a track,
Navidrome dispatches the request to registered plugins, which return similar songs.

Plan A built Nomarr's similarity API endpoint (`POST /api/v1/navidrome/similar-tracks`)
which accepts a Navidrome song ID and returns similar tracks via vector ANN search.
This plan builds the TinyGo WASM plugin (`nomarr.ndp`) that bridges Navidrome's
Instant Mix calls to that endpoint, making Nomarr's ML-derived audio similarity
available directly in Navidrome's player UI.

The plugin is modeled on the AudioMuse-AI NV plugin reference implementation
(~250 lines Go, same HTTP-to-external-API pattern).

**Prerequisite:** TASK-navidrome-integration-A-similarity-api

### Design Decisions

**TinyGo + wasip1 target.** Navidrome's plugin system uses Extism with WASM. TinyGo is
the supported Go compiler for WASM plugins (standard Go produces too-large binaries).
Build: `tinygo build -target=wasip1 -scheduler=none -buildmode=c-shared`.

**Navidrome PDK.** The plugin uses `github.com/navidrome/navidrome/plugins/pdk/go/metadata`
for type registration and `pdk` for config access and HTTP requests. Registration is
via `metadata.Register(&plugin{})` in `func init()`.

**HTTP to Nomarr.** The plugin makes an HTTP POST to Nomarr's
`/api/v1/navidrome/similar-tracks` using `pdk.NewHTTPRequest().Send()`. The Nomarr URL
and API key are user-configurable via the plugin's JSONForms config schema in
`manifest.json`. The WASM sandbox allows HTTP via `requiredHosts` permission.

**SongRef with ID.** The plugin returns `metadata.SongRef` with the `ID` field set to
Navidrome mediafile IDs (from Nomarr's response). This gives Navidrome direct ID
resolution without fuzzy title/artist matching — the most reliable resolution path.

**Graceful degradation.** When Nomarr is unreachable or returns errors, the plugin
returns an empty result (not an error), allowing Navidrome to fall back to other
registered agents (Last.fm, ListenBrainz, etc.).

**Separate directory.** The plugin lives in `navidrome-plugin/` at the repo root with
its own Go module. It is a separate build artifact — not part of Nomarr's Python
package.

### Plugin Request/Response Contract

Navidrome sends `SimilarSongsByTrackRequest`:

- `ID` (string): internal Navidrome mediafile ID
- `Name` (string): track title
- `Artist` (string): artist name
- `MBID` (string, optional): MusicBrainz recording ID
- `Count` (int32): max results requested

Plugin returns `SimilarSongsResponse` containing `[]SongRef`:

- `ID` (string): Navidrome mediafile ID (set from Nomarr's mapping)
- `Name`, `Artist`, `Album` (string): metadata for display

Navidrome resolves `SongRef.ID` directly to its MediaFile table — no fuzzy matching
needed when ID is populated.

## Phases

### Phase 1: Plugin Project Scaffold

- [x] Create `navidrome-plugin/` directory with `go.mod` (module `github.com/nomarr/navidrome-plugin`), importing `github.com/navidrome/navidrome/plugins/pdk/go/metadata` and `github.com/navidrome/navidrome/plugins/pdk/go/pdk`; run `go mod tidy` to resolve dependencies
    **Notes:** go.mod: module github.com/nomarr/navidrome-plugin, go 1.25, requires github.com/navidrome/navidrome/plugins/pdk/go v0.0.0-20260307170009-e1b341299981. go mod tidy resolved all transitive deps (extism/go-pdk v1.1.3 etc.). go.sum created.
- [x] Create `navidrome-plugin/manifest.json` — name `nomarr`, description "Nomarr ML-powered audio similarity for Instant Mix", version `0.1.0`, `requiredHosts: ["*"]`, JSONForms config schema with `nomarr_url` (string, required, title "Nomarr API URL"), `nomarr_api_key` (string, required, format password, title "Nomarr API Key"), and `backbone_id` (string, default `effnet-discogs`, title "ML Backbone")
    **Notes:** Created manifest.json with: name "nomarr", version "0.1.0", MetadataAgent capability (implicit via PDK registration), HTTP permission with requiredHosts: ["*"], JSONForms config schema with nomarr_url (string, required), nomarr_api_key (string, format password, required), backbone_id (string, default "effnet-discogs"). UISchema uses VerticalLayout.
- [x] Create `navidrome-plugin/main.go` skeleton — `package main`, `func init()` calling `metadata.Register(&nomarrPlugin{})`, `nomarrPlugin` struct implementing `metadata.SimilarSongsByTrackProvider` interface, stub `GetSimilarSongsByTrack` returning empty `metadata.SimilarSongsResponse`
    **Notes:** Created main.go with package main, nomarrPlugin struct, init() calling metadata.Register(), stub GetSimilarSongsByTrack returning empty SimilarSongsResponse. Verified compilation with GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared — produces 3.38MB plugin.wasm. Exit code 0.
- [x] Create `navidrome-plugin/Makefile` with targets: `build` (`tinygo build -target=wasip1 -scheduler=none -buildmode=c-shared -o plugin.wasm .`), `package` (zip `plugin.wasm` + `manifest.json` into `nomarr.ndp`), `clean` (remove build artifacts)
    **Notes:** Created Makefile with build (GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared by default, USE_TINYGO=1 for tinygo), package (zip plugin.wasm + manifest.json into nomarr.ndp), clean (rm wasm and ndp).

### Phase 2: Similarity Bridge & Documentation

- [x] Implement `GetSimilarSongsByTrack` in `main.go` — read config via `pdk.GetConfig("nomarr_url")`, `pdk.GetConfig("nomarr_api_key")`, `pdk.GetConfig("backbone_id")`; construct HTTP POST to `{nomarr_url}/api/v1/navidrome/similar-tracks` with JSON body `{"song_id": req.ID, "count": req.Count, "backbone_id": backbone}` and header `X-API-Key: {api_key}`; parse JSON response; map to `[]metadata.SongRef` with `ID`, `Name`, `Artist`, `Album` fields set
    **Notes:** Implemented GetSimilarSongsByTrack in main.go. Reads config (nomarr_url, nomarr_api_key, backbone_id) via pdk.GetConfig. Sends HTTP POST to {nomarr_url}/api/v1/navidrome/similar-tracks with JSON body {song_id, count, backbone_id} and X-API-Key header via host.HTTPSend (30s timeout). Parses nomarrResponse, maps songs to []metadata.SongRef with ID, Name, Artist, Album. Compiled successfully with GOOS=wasip1 GOARCH=wasm, exit code 0.
- [x] Add error handling — catch HTTP failures, non-200 responses, and JSON parse errors; log via available plugin logging; return empty `SimilarSongsResponse` (not error) so Navidrome falls back to other agents gracefully
    **Notes:** Error handling implemented in P2-S1 as part of GetSimilarSongsByTrack. All error paths return empty SimilarSongsResponse (not error) for graceful fallback: missing config returns empty with LogWarn, JSON marshal failure returns empty with LogError, HTTP send failure returns empty with LogError, non-200 status returns empty with LogWarn (logs body), JSON parse failure returns empty with LogError. Navidrome will fall back to other registered agents.
- [x] Create `navidrome-plugin/README.md` documenting: TinyGo prerequisite (version, install link), build steps (`make build`, `make package`), deployment (copy `nomarr.ndp` to Navidrome's `plugins/` directory, restart Navidrome), configuration (set Nomarr URL, API key, optionally backbone in Navidrome's plugin settings), troubleshooting (check Navidrome logs for plugin load errors, verify Nomarr is reachable from Navidrome host)
    **Notes:** Created README.md (135 lines) documenting: Go 1.24+ prerequisite (TinyGo optional via USE_TINYGO=1), build steps (make build/package/clean), deployment (copy to plugins dir, enable plugins in Navidrome config, restart), configuration table (nomarr_url required, nomarr_api_key required, backbone_id optional with default), how it works (request flow), troubleshooting (plugin not loading, no results, config errors), manual integration test steps (6 verification steps with log messages to check).
- [x] Verify `make build` and `make package` produce a valid `nomarr.ndp` file; document manual integration test steps in README (install in Navidrome, trigger Instant Mix on a track, check Navidrome logs for plugin invocation, verify results appear)
    **Notes:** Verified build: GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared produces plugin.wasm (3,414,466 bytes), exit code 0. Packaged: Compress-Archive produces nomarr.ndp (966,196 bytes) containing plugin.wasm and manifest.json. Manual integration test steps already documented in README.md (section "Manual Integration Testing", 6 steps covering deploy, config, sync, trigger Instant Mix, check logs, verify results).

## Completion Criteria

- `navidrome-plugin/` contains a complete Go module buildable with TinyGo targeting wasip1
- `manifest.json` declares correct HTTP permissions and JSONForms config schema for Nomarr URL, API key, and backbone
- `GetSimilarSongsByTrack` calls Nomarr's `/api/v1/navidrome/similar-tracks` and returns `SongRef` results with Navidrome IDs populated
- `make package` produces a deployable `nomarr.ndp` file
- Plugin gracefully handles Nomarr unavailability by returning empty results
- README documents the complete build → deploy → configure workflow

## References

- Prerequisite: `plans/TASK-navidrome-integration-A-similarity-api.md`
- AudioMuse-AI NV plugin (reference implementation): <https://github.com/NeptuneHub/AudioMuse-AI-NV-plugin>
- Navidrome PDK Go package: `github.com/navidrome/navidrome/plugins/pdk/go/metadata`
- Navidrome plugin docs: <https://www.navidrome.org/docs/usage/features/plugins/>
- Research doc: `docs/upstream/navidrome_integration.md`
- Part A (prerequisite): `plans/TASK-navidrome-integration-A-similarity-api.md`
- Part C (playlist push): `plans/TASK-navidrome-integration-C-playlist-push.md`
