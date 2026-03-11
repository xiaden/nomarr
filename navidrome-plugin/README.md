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

```bash
# Compile WASM from src/ into dist/
make build

# Compile and package as dist/nomarr.ndp
make package

# Clean dist/ directory
make clean
```

The `make package` command produces `dist/nomarr.ndp` — a ZIP archive containing
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
|---------|----------|-------------|
| **Nomarr API URL** | Yes | Base URL of your Nomarr instance (e.g. `http://nomarr:8356`) |
| **Nomarr API Key** | Yes | API key for authenticating with Nomarr's v1 API |
| **ML Backbone** | No | ML backbone model for similarity (default: `effnet-discogs`) |

### Generating a Nomarr API Key

In Nomarr's web UI, go to **Settings → API Keys** and create a new key.
Copy the key value into the plugin's configuration in Navidrome.

## How It Works

When a user triggers Instant Mix on a track in Navidrome:

1. Navidrome sends the track's mediafile ID to the plugin
2. The plugin POSTs to Nomarr's `/api/v1/navidrome/similar-tracks` endpoint
3. Nomarr performs vector ANN search over ML audio embeddings to find similar tracks
4. The plugin maps results back to Navidrome mediafile IDs
5. Navidrome creates a playlist from the similar tracks

The plugin uses Navidrome's host HTTP service for network requests, respecting
the sandbox permissions declared in `manifest.json`.

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
  curl -H "X-API-Key: YOUR_KEY" http://nomarr:8356/api/v1/navidrome/similar-tracks \
    -H "Content-Type: application/json" \
    -d '{"song_id": "SOME_NAVIDROME_ID", "count": 10}'
  ```

- Check that Navidrome's song map is synced (the Nomarr API needs to know the
  mapping between Navidrome mediafile IDs and Nomarr's internal IDs)
- Review Navidrome plugin logs for error messages from the nomarr plugin

### Configuration errors

- Ensure both **Nomarr API URL** and **Nomarr API Key** are set in the plugin
  settings
- The URL should not have a trailing slash
- The API key must match a valid key in Nomarr's settings

## Manual Integration Testing

1. Build and deploy the plugin as described above
2. Configure the plugin with your Nomarr instance URL and API key
3. Ensure the Navidrome song map is synced (trigger a sync from Nomarr's
   Navidrome settings page)
4. In a Navidrome client (web UI or Subsonic app), select a track and click
   **Instant Mix** (or "Play Radio")
5. Check Navidrome logs for plugin invocation messages:

   ```
   nomarr: querying http://nomarr:8356/api/v1/navidrome/similar-tracks for song <id>
   nomarr: found N similar tracks for song <id>
   ```

6. Verify similar tracks appear in the generated playlist

## License

Part of the [Nomarr](https://github.com/xiaden/nomarr) project.
