# Navidrome Integration Research

Last updated: 2026-02-21  
Based on: Navidrome v0.60.3 (current latest)

---

## Overview

This document covers Navidrome's current technical surface from Nomarr's perspective:
what it exposes, what we can hook into, and what recently changed that affects our
integration strategy.

---

## Plugin System (v0.60.0 — full production release)

Plugins were introduced experimentally in **v0.57.0** (July 2025) and completely
rewritten in **v0.60.0** (February 2026). The v0.60.0 rewrite is the one to design
against — the v0.57 API should be considered obsolete.

### How it works

Plugins are compiled to **WebAssembly** (`.ndp` package files) and run inside the
[Extism](https://extism.org/) WASM sandbox. They cannot access the host filesystem
or network except via explicitly declared permissions in their manifest.

Supported authoring languages: **Go** (TinyGo), **Rust**, **Python**, **JavaScript**

### Plugin capabilities

Each plugin declares one or more capability types:

| Capability | Description |
| --- | --- |
| **Metadata Agent** | Fetches artist bios, album info, images, similar artists/songs from external sources. Registered as a named `ND_AGENTS` entry. |
| **Scrobbler** | Sends listening history to external services. Per-user scoped. |
| **Scheduled Task** | Runs background tasks on a timer. Has access to `SchedulerService.TimeNow`. |
| **Event Handler** | Reacts to Navidrome events (playback, library changes). |

Metadata agents are the most relevant to Nomarr: they slot directly into Navidrome's
`getSimilarSongs`, `getSimilarSongs2`, `getArtistInfo`, `getArtistInfo2`,
`getAlbumInfo`, and `getAlbumInfo2` Subsonic endpoints.

### Host functions exposed to plugins

From the v0.60.0/v0.60.2 changelogs:

- **SubsonicAPI** — Call Subsonic endpoints from within the plugin, including `CallRaw`
  for binary responses (v0.60.2). Lets plugins query Navidrome's own library.
- **StorageService** — Persistent key-value storage scoped to the plugin.
- **SchedulerService** — Register scheduled tasks; `TimeNow` added in v0.58.0.

### Plugin configuration

Server-side config keys (TOML / env var):

```toml
[Plugins]
Enabled = true
Folder = "/data/plugins"      # default: <DataFolder>/plugins
AutoReload = false            # watch for .ndp changes
LogLevel = "debug"            # independent of main LogLevel
CacheSize = "200MB"           # WASM compilation cache
```

Equivalent env vars: `ND_PLUGINS_ENABLED`, `ND_PLUGINS_FOLDER`,
`ND_PLUGINS_AUTORELOAD`, `ND_PLUGINS_LOGLEVEL`, `ND_PLUGINS_CACHESIZE`.

Plugins are managed through the Navidrome admin UI (Plugins section): enable/disable,
JSONForms-based per-plugin config, user-scope grants, library-scope grants.

### Permissions model (manifest)

Each `.ndp` package includes a `manifest.json` declaring:

- Which external HTTP hosts the plugin may contact
- Whether it needs persistent storage
- Whether it needs library access
- Whether it's user-scoped

### Existing ML-over-Navidrome precedent: AudioMuse-AI

The [AudioMuse-AI NV plugin](https://github.com/NeptuneHub/AudioMuse-AI-NV-plugin)
is a directly relevant reference implementation. It:

- Runs as a Navidrome Metadata Agent plugin
- Points at an external ML service (the AudioMuse-AI Flask+worker stack)
- Implements `getSimilarSongs2`, `getSimilarSongs`, `getArtistInfo`
- Enables Navidrome's **Instant Mix** feature (v0.60.0+) using ML-derived similarity

This is exactly the pattern Nomarr would follow. AudioMuse-AI is to their ML service
what a Nomarr plugin would be to Nomarr's ML/vector infrastructure.

The plugin is written in Go (TinyGo), compiled to WASM, deployed as `.ndp`.

---

## Subsonic API Surface (v1.16.1 + OpenSubsonic extensions)

Navidrome implements [Subsonic API](http://www.subsonic.org/pages/api.jsp) v1.16.1
plus a growing set of [OpenSubsonic extensions](https://opensubsonic.netlify.app/).

### Library inventory endpoints

Relevant for Nomarr's "Navidrome as library source" concept:

| Endpoint | Notes |
| --- | --- |
| `getMusicFolders` | Returns all libraries accessible to the authenticated user. Multi-library aware since v0.58.0. |
| `getIndexes` | Simulated directory tree (no real folder browsing). Format: `/Artist/Album/01 - Song.mp3`. |
| `getMusicDirectory` | Traversal of the simulated tree. |
| `getSong` | Full song metadata by ID. |
| `getArtists` | Full artist list. |
| `getArtist` | Artist with albums. |
| `getAlbum` | Album with tracks. |

**Important caveat:** `getIndexes` and `getMusicDirectory` return a *simulated* tree,
not real filesystem paths. Path resolution for Nomarr's file access would require
either maintaining path mappings or treating Navidrome file paths as opaque IDs and
resolving via mount prefix config.

### Playlist management

| Endpoint | Notes |
| --- | --- |
| `getPlaylists` | All playlists for the authenticated user. |
| `getPlaylist` | Playlist with full track list. |
| `createPlaylist` | Create with name and song IDs. |
| `updatePlaylist` | Update name, comment, songs, public flag. Also creates if no playlistId given. |
| `deletePlaylist` | Delete by ID. |

`createPlaylist` / `updatePlaylist` would allow Nomarr to push smart playlists
directly into Navidrome rather than writing `.nsp` files to disk and waiting for a
rescan.

OpenSubsonic extensions (v0.60.2) add `readonly` and `validUntil` fields to
playlists.

### Scan control

| Endpoint | Notes |
| --- | --- |
| `getScanStatus` | Returns scan status plus extra `lastScan` and `folderCount` fields. |
| `startScan` | Accepts `fullScan` boolean param (Navidrome extension). |

Nomarr could trigger a Navidrome library rescan after writing back tag changes, rather
than relying on Navidrome's own watch interval.

### Similarity / Instant Mix (v0.60.0+)

| Endpoint | Notes |
| --- | --- |
| `getSimilarSongs` | Requires external integration (Last.fm or plugin). |
| `getSimilarSongs2` | Same. |
| `getArtistInfo` / `getArtistInfo2` | Artist bio, images, similar artists. Requires external integration. |
| `getAlbumInfo` / `getAlbumInfo2` | Album info. Requires external integration. |

Navidrome's **Instant Mix** feature (v0.60.0) uses `getSimilarSongs2` under the hood,
populated by whichever agent/plugin is configured. A Nomarr plugin implementing this
endpoint would enable Instant Mix powered by Nomarr's ML vectors.

### Authentication

Subsonic uses a token-based auth scheme:
`?u=username&t=md5(password+salt)&s=salt`

Or with API keys (OpenSubsonic extension). For server-to-server use (Nomarr calling
Navidrome), a dedicated service account is the clean approach.

---

## Multi-Library Support (v0.58.0+)

Navidrome now supports multiple libraries with per-user access controls. Relevant
for Nomarr config:

- Each library is a separate music folder with its own path.
- `getMusicFolders` returns the libraries accessible to the authenticated user.
- All Subsonic endpoints are library-aware and filter by user access.
- Playlist tracks can span libraries (filtered by user access).

For Nomarr's path resolution, a multi-library Navidrome setup means the path prefix
mapping may need to be per-library, not global.

---

## Recent Notable Changes (v0.57–v0.60)

| Version | Change | Nomarr relevance |
| --- | --- | --- |
| v0.60.0 | Plugin system full rewrite (WASM, multi-language PDK) | Core opportunity |
| v0.60.0 | Instant Mix via plugin or Last.fm | Nomarr ML can power this |
| v0.60.2 | `SubsonicAPI.CallRaw` in plugins (binary responses) | Needed for any audio-touching plugin |
| v0.60.2 | PlayList `readonly` + `validUntil` OpenSubsonic fields | Relevant for managed playlist push |
| v0.59.0 | Native scrobble/listen history tracking | Future: Nomarr analytics correlation |
| v0.58.0 | Multi-library support (full, with per-user permissions) | Path mapping must be per-library |
| v0.57.0 | Plugin system (experimental, now superseded) | — |

---

## Nomarr Integration Opportunities

### 1. Nomarr as a Navidrome Metadata Agent plugin

Build a `.ndp` plugin (Go/TinyGo) that:

- Declares itself as a Metadata Agent in `manifest.json`
- Declares HTTP access permission to `http://nomarr:8000` (or configured URL)
- Implements `getSimilarSongs2`: queries Nomarr's vector similarity API, returns
  Navidrome song IDs
- Implements `getArtistInfo2`: returns ML-derived mood/energy profile or defers to
  existing agents

This would enable Navidrome's **Instant Mix** and **Artist Radio** features to use
Nomarr's ML without any changes to Nomarr's existing API. The AudioMuse-AI plugin is
the direct reference implementation to clone and adapt.

**Complexity:** Low–Medium. The plugin itself is ~200–400 lines of TinyGo. The hard
part is the Nomarr-side API endpoint that accepts `(navidrome_song_id) →
[similar_navidrome_song_ids]` — which requires having the ID mapping solved first.

### 2. Direct playlist push via Subsonic API

Instead of writing `.nsp` files to disk for Navidrome to pick up on next scan, Nomarr
calls `createPlaylist` / `updatePlaylist` directly. Smart playlists stored in
ArangoDB would be synced on demand or on schedule.

This replaces the current file-generation and drop workflow entirely for users who
have Navidrome configured.

**Complexity:** Low. `NavidromeService` gains a Subsonic HTTP client and a
`sync_playlist` method. The existing playlist generation logic stays, the output
destination changes.

### 3. Navidrome as optional library source adapter

When configured, Nomarr polls Navidrome's `getMusicFolders` + song inventory via
Subsonic rather than scanning the filesystem directly. File paths from Navidrome are
remapped via a configurable `path_prefix` to the local mount point for direct file
access (still needed for ML/audio analysis).

The scan-delegation is the largest scope item and can be deferred. The playlist push
and plugin are independently useful.

### 4. Rescan trigger after tag write-back

After Nomarr writes tags back to audio files, call `startScan?fullScan=false` to
trigger Navidrome's incremental rescan rather than waiting for the watch interval.
Closes the feedback loop between Nomarr's tagging and Navidrome's metadata view.

**Complexity:** Trivial. One HTTP call appended to the tag write-back workflow.

---

## Config Requirements (proposed)

Additions to `NavidromeConfig` / Nomarr config schema:

```toml
[Navidrome]
# Existing
Namespace = "nom"

# New: Subsonic API integration
ApiUrl = "http://navidrome:4533"   # Navidrome base URL
ApiUser = "nomarr"                  # Service account username
ApiPassword = "..."                 # Service account password (or ApiToken for OpenSubsonic)

# New: Path resolution
# Maps Navidrome's library root path to Nomarr's local mount path
# e.g. Navidrome sees /music, Nomarr mounts it at /library
LibraryPathPrefix = "/music"        # Path as Navidrome reports it
LocalPathPrefix = "/library"        # Path as Nomarr sees it
# For multi-library setups, this would become a list of mappings
```

---

## Plugin Development Reference

To build a Nomarr plugin for Navidrome:

- **Language:** Go with TinyGo (`tinygo build -o plugin.wasm -target=wasi ./...`)
- **SDK:** Navidrome PDK (no public docs yet; AudioMuse-AI source is the reference)
- **Packaging:** `make package` → `nomarr.ndp` (zip of WASM + manifest.json)
- **Manifest fields:**
  - `capabilities`: `["MetadataAgent"]`
  - `permissions.http`: `["http://nomarr:8000"]`
  - `config`: JSONForms schema for plugin config UI
- **Distribution:** Drop `.ndp` into `$ND_PLUGINS_FOLDER`; user enables via UI

Plugin developer docs from Navidrome are not yet published (noted in v0.60.0 release
notes). The AudioMuse-AI plugin source and the Navidrome PDK source code are the
practical references until official docs land.

---

## References

- Navidrome releases: <https://github.com/navidrome/navidrome/releases>
- Plugin usage docs: <https://www.navidrome.org/docs/usage/features/plugins/>
- Subsonic API compatibility: <https://www.navidrome.org/docs/developers/subsonic-api/>
- OpenSubsonic extensions tracker: <https://github.com/navidrome/navidrome/issues/2695>
- AudioMuse-AI NV plugin (reference impl): <https://github.com/NeptuneHub/AudioMuse-AI-NV-plugin>
- Extism WASM runtime: <https://extism.org/>
- Multi-library docs: <https://www.navidrome.org/docs/usage/features/multi-library/>
