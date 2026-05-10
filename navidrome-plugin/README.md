# Nomarr — Navidrome Plugin

A Navidrome WASM plugin that powers **Instant Mix** with Nomarr's ML-derived audio
similarity. When a user clicks Instant Mix on a track in Navidrome, this plugin
queries Nomarr's vector similarity API and returns sonically similar tracks.

## Prerequisites

- **Go 1.24+** — required for native `//go:wasmexport` support
  ([download](https://go.dev/dl/))
- **make** and **zip** — for packaging
- **Nomarr** instance with the Navidrome integration API enabled and an API key
  configured
- **Navidrome v0.60.0+** with plugins enabled

> **Note:** TinyGo is also supported. Set `USE_TINYGO=1` when running `make build`
> to use TinyGo instead of standard Go.

## Build

### PowerShell (Windows / cross-platform)

```powershell
# Compile WASM from src/ into dist/
./build.ps1

# Compile and package as dist/nomarr.ndp
./build.ps1 -Package

# Clean dist/ directory
./build.ps1 -Clean

# Build with TinyGo instead of standard Go
./build.ps1 -UseTinyGo
```

### Make (Linux / macOS)

```bash
# Compile WASM from src/ into dist/
make build

# Compile and package as dist/nomarr.ndp
make package

# Clean dist/ directory
make clean
```

The package command produces `dist/nomarr.ndp` — a ZIP archive containing
`plugin.wasm` and `manifest.json`.

## Deployment

1. **Copy the plugin** to Navidrome's plugins directory:

   ```bash
   cp dist/nomarr.ndp /path/to/navidrome/plugins/nomarr/
   cd /path/to/navidrome/plugins/nomarr/
   unzip nomarr.ndp
   ```

   The directory should contain `plugin.wasm` and `manifest.json`.

2. **Enable plugins** in Navidrome's config (if not already):

   ```toml
   [Plugins]
   Enabled = true
   ```

   Or via environment variable: `ND_PLUGINS_ENABLED=true`

3. **Restart Navidrome** to load the plugin.

## Configuration

After the plugin is loaded, configure it in Navidrome's admin UI under
**Settings → Plugins → nomarr**:

 | Setting | Required | Description |
 | --------- | ---------- | ------------- |
 | **Nomarr API URL** | Yes | Base URL of your Nomarr instance (e.g. `http://nomarr:8356`) |
 | **Nomarr API Key** | Yes | API key for authenticating with Nomarr's v1 API |
 | **ML Backbone** | No | ML backbone model for similarity (default: `effnet`) |

### Generating a Nomarr API Key

In Nomarr's web UI, go to **Settings → API Keys** and create a new key.
Copy the key value into the plugin's configuration in Navidrome.

## How It Works

When a user triggers Instant Mix on a track in Navidrome:

1. Navidrome sends the track's mediafile ID to the plugin
2. The plugin POSTs a portable seed descriptor to Nomarr's
   `/api/v1/navidrome/similar-track` endpoint
3. Nomarr performs vector ANN search over ML audio embeddings to find similar tracks
4. Nomarr returns portable descriptors for similar tracks
5. The plugin resolves descriptors to Navidrome mediafile IDs locally
5. Navidrome creates a playlist from the similar tracks

The plugin uses Navidrome's host HTTP service for network requests, respecting
the sandbox permissions declared in `manifest.json`.

## Personal Playlists

The plugin can generate personal playlists on a schedule and push them directly
to Navidrome via the Subsonic `createPlaylist` API. Playlists are built from
Nomarr's ML audio embeddings and tailored per user.

### Configuration

Enable personal playlists with the **Enable Personal Playlists** toggle and set
a cron schedule via **Playlist Schedule** (default: `0 3 * * *`, daily at 3 AM).

The **Users (JSON)** field accepts a JSON array of user configurations. Each
entry maps a Navidrome username to the playlist types you want generated for
that user:

> **Tip:** In Navidrome's plugin settings UI, each playlist-user row is labeled
> with that entry's `username`, making it easier to tell users apart at a glance.

```json
[
  {
    "username": "alice",
    "enabled_types": ["familiar", "discovery", "genre"],
    "max_songs": 30,
    "max_genre_playlists": 5
  },
  {
    "username": "bob"
  }
]
```

 | Field | Type | Description |
 | ------- | ------ | ------------- |
 | `username` | string (required) | Navidrome username |
 | `enabled_types` | string[] (optional) | Playlist types to generate. Omit to generate all types. |
 | `max_songs` | int (optional) | Maximum tracks per playlist |
 | `min_songs` | int (optional) | Minimum tracks required to create a playlist |
 | `max_genre_playlists` | int (optional) | Maximum number of genre playlists to generate per user (1–25, default 5) |

### Playlist Types

 | `enabled_types` value | Playlist Name | Description |
 | ----------------------- | --------------- | ------------- |
 | `familiar` | Your Favorites | Sonically coherent mix of tracks near your taste centroid |
 | `discovery` | Discover Weekly | Unplayed tracks near your taste centroid |
 | `hidden_gems` | Hidden Gems | Unplayed tracks from unfamiliar artists |
 | `universal` | Your Mix | Diversified blend sampled across your full taste profile |
 | `genre` | Your {Genre} Mix | One playlist per genre in your taste profile (e.g. "Your Rock Mix") |

> **Note:** If `enabled_types` is omitted for a user, all five types are generated.

> **Note:** `genre` playlists are only created for genres that have at least 100
> similar tracks in the ML index.

### Playlist Generation Behavior

When the plugin asks Nomarr to generate personal playlists, it applies a few
guards before pushing anything back to Navidrome.

#### Empty playlists are skipped

If Nomarr returns a playlist with zero tracks, the plugin logs a WARN message
and skips that playlist instead of calling Navidrome's `createPlaylist` API.
This protects existing Navidrome playlists from being overwritten with empty
content when no Navidrome track IDs could be resolved for the generated
playlist.

#### Backend response status handling

The plugin now handles the following response statuses from Nomarr's
generate-playlists endpoint:

- `ok` (or an empty status for backward compatibility): process playlists
  normally
- `no_data`: no playlists were generated, such as when there is not enough
  listen history yet; logged at INFO and nothing is pushed to Navidrome
- `misconfigured`: the backend is misconfigured; logged at ERROR with the
  backend-provided message and nothing is pushed to Navidrome

#### Optional `backbone_id` override

The generate-playlists request also accepts an optional `backbone_id` field.
When provided, it allows the ML backbone model to be overridden for that
request. When omitted, Nomarr uses its normal backend default behavior.

## Troubleshooting

### Plugin not loading

- Check Navidrome logs for plugin load errors:

  ```
  ND_PLUGINS_LOGLEVEL=debug
  ```

- Verify `plugin.wasm` and `manifest.json` are in the plugins directory
- Ensure Navidrome v0.60.0+ is running with plugins enabled

### No results from Instant Mix

- Verify Nomarr is reachable from the Navidrome host:

  ```bash
  curl -H "X-API-Key: YOUR_KEY" http://nomarr:8356/api/v1/navidrome/similar-track \
    -H "Content-Type: application/json" \
    -d '{"seed":{"title":"Song","artist":"Artist"},"count":10}'
  ```

- Review Navidrome plugin logs for error messages from the nomarr plugin

### Configuration errors

- Ensure both **Nomarr API URL** and **Nomarr API Key** are set in the plugin
  settings
- The URL should not have a trailing slash
- The API key must match a valid key in Nomarr's settings

## Manual Integration Testing

1. Build and deploy the plugin as described above
2. Configure the plugin with your Nomarr instance URL and API key
3. In a Navidrome client (web UI or Subsonic app), select a track and click
   **Instant Mix** (or "Play Radio")
4. Check Navidrome logs for plugin invocation messages:

   ```
   nomarr: querying http://nomarr:8356/api/v1/navidrome/similar-track for song <id>
   nomarr: found N similar tracks for song <id>
   ```

5. Verify similar tracks appear in the generated playlist

## License

Part of the [Nomarr](https://github.com/xiaden/nomarr) project.
