# Navidrome Integration Guide

**Generate Smart Playlists for Navidrome Using Nomarr Tags**

---

## Overview

Nomarr can generate smart playlists for [Navidrome](https://www.navidrome.org/) based on the ML tags it extracts from your music. You can create playlists like "Energetic Electronic", "Mellow Acoustic", or "Danceable Pop" and either download them as files or push them directly to Navidrome.

**What this integration provides:**

- **Smart playlist generation** using a visual rule builder with nested AND/OR logic
- **Direct push to Navidrome** via the Subsonic API (no file copying needed)
- **Static M3U playlists** from hand-picked tracks
- **Playlist templates** for common genres and moods with batch generation
- **Song sync** to pull your Navidrome library into Nomarr for cross-referencing
- **Connectivity testing** to verify your Navidrome connection

**Flow boundary:**

- **Plugin Instant Mix / similar-track**: descriptor-only flow; plugin resolves Navidrome IDs locally.
- **Backend push / personal playlists**: may use Nomarr’s synced Navidrome ID mapping for file-id → song-id translation.

---

## How It Works

```
Nomarr Processing
    ↓
Audio Analysis (ML models)
    ↓
Tag Extraction (mood, genre, energy, etc.)
    ↓
Tag Storage (database)
    ↓
Playlist Builder (Web UI rule builder)
    ↓
Download .nsp file  OR  Push directly to Navidrome via Subsonic API
```

Unlike file-based export workflows, Nomarr connects to Navidrome over the network using the Subsonic API. You configure the connection in the Web UI, and playlists are pushed directly — no shared volumes or file copying required.

---

## Prerequisites

1. **Nomarr installed and running** (see [Getting Started](getting_started.md))
2. **Music library processed** (at least some tracks analyzed)
3. **Navidrome installed** and accessible over the network

**Navidrome requirements:**

- Navidrome with Subsonic API enabled (enabled by default)
- A Navidrome user account with playlist permissions
- Network connectivity between Nomarr and Navidrome containers (or hosts)

---

## Configuration

All Navidrome configuration is done through the Web UI — no config file editing required.

### 1. Open the Navidrome Page

In the Nomarr Web UI, click **Navidrome** in the sidebar.

### 2. Configure API Settings

Expand the **API Settings** panel at the bottom of the page:

1. **Navidrome URL** — The base URL of your Navidrome server (e.g., `http://navidrome:4533` or `https://music.yourdomain.com`)
2. **Username** — Your Navidrome username
3. **Password** — Your Navidrome password
4. Click **Save**

### 3. Test Connectivity

Click the **Ping** button to verify Nomarr can reach your Navidrome server. You should see a success message.

!!! tip
    If Navidrome and Nomarr both run in Docker, use the Navidrome container name and internal port (e.g., `http://navidrome:4533`). They must share a Docker network.

### 4. Sync Songs (Optional; non-plugin flows)

Click **Sync Songs** to pull your Navidrome library into Nomarr’s database. This enables:

- Resolving Nomarr file IDs to Navidrome song IDs when pushing playlists
- Better cross-referencing between the two systems

Sync is **not required** for Navidrome plugin Instant Mix / similar-track recommendations.
That plugin flow uses portable descriptors and resolves Navidrome IDs inside the plugin.

---

## Generating Smart Playlists

The **Playlist Maker** panel is where you build smart playlists using Nomarr’s ML tags.

### Using the Rule Builder

1. **Add a rule** — Select a tag (e.g., "electronic"), an operator (e.g., "greater than"), and a threshold value (e.g., 0.7)
2. **Combine rules** — Use AND/OR logic to combine multiple tag conditions
3. **Add groups** — Click "Add Group" to create nested rule groups for complex boolean logic
4. **Sort and limit** — Use the sort picker and limit to control playlist order and size
5. **Preview** — Click "Preview" to see matching tracks before generating
6. **Generate** — Click "Generate" to create a `.nsp` playlist file for download

### Example Queries

**Energetic Electronic:**

```
tag:electronic > 0.7 AND tag:energetic > 0.7
```

**Mellow Acoustic:**

```
tag:mellow > 0.7 AND tag:acoustic > 0.6
```

**Rock or Metal (Energetic):**

```
(tag:rock > 0.7 OR tag:metal > 0.7) AND tag:energetic > 0.6
```

**Happy Dance Music OR Calm Acoustic:**

```
(tag:happy > 0.6 AND tag:danceable > 0.6) OR (tag:calm > 0.7 AND tag:acoustic > 0.6)
```

### Nested Rule Groups

The rule builder supports nested AND/OR groups up to 5 levels deep, giving you full boolean control over playlist criteria.

Without nesting, you can only express "all must match" (AND) or "any can match" (OR). Nesting lets you combine both:

```
# Electronic dance OR acoustic chill, but must be happy
((tag:electronic > 0.7 AND tag:danceable > 0.7) OR (tag:acoustic > 0.7 AND tag:mellow > 0.6)) AND tag:happy > 0.5
```

### Using Templates

Templates are predefined playlist configurations for common genres and moods:

1. Expand the **Playlist Maker** panel
2. View available templates with descriptions
3. Click a template to load its rules into the builder
4. Preview matching tracks
5. Generate the playlist

**Batch generation:** Use the **Generate All Templates** option to create all template playlists at once.

---

## Pushing Playlists to Navidrome

Instead of downloading `.nsp` files, you can push playlists directly to Navidrome:

1. Build your playlist using the rule builder or templates
2. Preview the matching tracks
3. Click **Push to Navidrome**
4. Nomarr resolves your local file IDs to Navidrome song IDs via the synced library
5. The playlist is created (or updated) in Navidrome via the Subsonic API

!!! note
    Push and other backend-managed playlist flows require **Sync Songs** so Nomarr can map file IDs to Navidrome song IDs.
    This requirement does **not** apply to plugin Instant Mix recommendations.

---

## Static Playlists (M3U)

For hand-picked playlists (not based on tags), you can create static M3U playlists:

1. Select specific tracks by their file IDs
2. Generate an M3U playlist file
3. Download or use in Navidrome

This is useful for curated playlists that don’t follow tag-based rules.

---

## Generating Navidrome Config

The **Generate Config** panel lets you:

1. **Preview tag statistics** — See which tags are available and how they’re distributed across your library
2. **Generate TOML config** — Create a Navidrome-compatible configuration file based on your tag data

---

## Tag Vocabulary Reference

**Common tags extracted by Nomarr:**

 | Category | Examples |
 | ---------- | ---------- |
 | **Mood** | energetic, mellow, happy, sad, aggressive, peaceful |
 | **Genre** | rock, pop, electronic, jazz, classical, hip hop, metal |
 | **Instrumentation** | acoustic, electric, vocal, instrumental |
 | **Rhythm** | danceable, fast, slow |
 | **Production** | live, studio, lo-fi, hi-fi |

See the full tag vocabulary in the Nomarr Web UI under the **Tags** page.

**Tag scores** range from 0.0 to 1.0, where higher values indicate stronger presence of that characteristic. When building playlists, you set threshold values to filter tracks.

If you’ve enabled **calibration**, tag thresholds are automatically tuned to your specific library for better accuracy.

---

## Personal Playlists (Taste-Based)

Nomarr can generate playlists automatically based on your Navidrome play history by building a *taste profile* — a vector centroid derived from your most-played tracks. These playlists are distinct from the rule-builder playlists: they require no configuration of tag thresholds and adapt to your listening over time.

**Playlist types generated:**

 | Type | Description |
 | ------ | ------------- |
 | `familiar` | Songs you have played frequently that match your taste profile |
 | `discovery` | Unheard songs that are similar to your favourites |
 | `hidden_gems` | Rarely-played songs that match your taste profile |
 | `genre` | One playlist per top genre preference (up to `pp_max_genre_playlists`) |
 | `universal` | A broad mix blending all taste dimensions |

### Prerequisites

1. **Navidrome connection configured** — URL, username, and password saved
2. **Sync Songs run** — required for backend-managed playlist push/personal playlist flows
3. **Music processed** — Tracks need ML embeddings; run a library scan first
4. **`pp_enabled`** set to `true` in settings

### Configuration

All `pp_*` settings are configurable from the Web UI settings panel:

 | Setting | Default | Description |
 | --------- | --------- | ------------- |
 | `pp_enabled` | `false` | Enable personal playlist generation |
 | `pp_backbone_id` | `effnet-discogs` | Embedding backbone model used for similarity calculations |
 | `pp_half_life_days` | `30` | Half-life in days for time-decay weighting of play history |
 | `pp_top_n` | `200` | Number of top-played songs to consider when building taste profiles |
 | `pp_min_play_count` | `3` | Minimum play count for a song to count toward the taste profile |
 | `pp_max_songs` | `50` | Maximum songs per generated playlist |
 | `pp_min_songs` | `10` | Minimum songs required for a playlist to be kept |
 | `pp_max_genre_playlists` | `5` | Maximum number of genre-focused playlists to generate per run (max: 25) |
 | `pp_overwrite_playlists` | `true` | Replace existing playlists instead of appending |
 | `pp_type_familiar` | `true` | Generate Familiar Favorites playlist |
 | `pp_type_discovery` | `true` | Generate Discovery playlist |
 | `pp_type_hidden_gems` | `true` | Generate Hidden Gems playlist |
 | `pp_type_genre` | `true` | Generate genre-focused playlists |
 | `pp_type_universal` | `true` | Generate universal mix playlist |

### API Usage

Personal playlists are generated via a direct API call (not the Web UI rule builder):

```
POST /api/v1/navidrome/generate-playlists
```

Request body:

 | Field | Type | Description |
 | ------- | ------ | ------------- |
 | `user_id` | string | Navidrome user identifier |
 | `enabled_types` | string[] \ | null | Override which playlist types to generate; `null` uses config |
 | `max_songs` | int \ | null | Override max songs per playlist; `null` uses config |
 | `min_songs` | int \ | null | Override min songs per playlist; `null` uses config |
 | `max_genre_playlists` | int \ | null | Override max genre playlists (1–25); `null` uses config |

Returns `status: "ok"` with a list of generated playlists, or `status: "no_data"` when there is insufficient play history. Returns HTTP 422 if `library_key` is not configured.

---

## Troubleshooting

### Cannot Connect to Navidrome

**Symptoms:** Ping fails, "connection refused" or timeout errors.

**Solutions:**

1. **Check the URL** — Ensure the Navidrome URL is correct and includes the port (e.g., `http://navidrome:4533`)
2. **Docker networking** — If both run in Docker, they must share a network. Add Navidrome to your `front_network` or create a shared network.
3. **Firewall** — Ensure the Navidrome port is accessible from the Nomarr container
4. **Credentials** — Verify username and password are correct

### Push Fails with "Song Not Found"

**Symptoms:** Push to Navidrome reports unresolved songs.

**Solutions:**

1. **Run Sync Songs** — required for backend push flows that resolve file IDs to Navidrome song IDs
2. **Check library paths** — Both Nomarr and Navidrome must see the same music files. Path mismatches prevent song resolution.

### Empty Playlist Results

**Symptoms:** Preview shows no matching tracks.

**Solutions:**

1. **Check processing** — Ensure tracks have been analyzed (check the Dashboard)
2. **Lower thresholds** — Try reducing tag threshold values (e.g., from 0.8 to 0.5)
3. **Check calibration** — If calibration is enabled, ensure it has completed. Visit the Calibration page.
4. **Preview tags** — Use the Generate Config panel to see which tags have data in your library

---

## API Integration

For programmatic access, Nomarr provides a full REST API for all Navidrome operations. Visit `http://localhost:8356/docs` for interactive API documentation.

**Key endpoints:**

 | Endpoint | Method | Description |
 | ---------- | -------- | ------------- |
 | `/api/web/navidrome/preview` | GET | Tag statistics for your library |
 | `/api/web/navidrome/tag-values` | GET | Distinct values for a specific tag |
 | `/api/web/navidrome/config` | GET | Generate TOML config text |
 | `/api/web/navidrome/playlists/preview` | POST | Preview playlist query results |
 | `/api/web/navidrome/playlists/generate` | POST | Generate .nsp playlist file |
 | `/api/web/navidrome/playlists/static` | POST | Generate static M3U playlist |
 | `/api/web/navidrome/playlists/push` | POST | Push playlist to Navidrome |
 | `/api/web/navidrome/templates` | GET | List available templates |
 | `/api/web/navidrome/templates` | POST | Batch generate from templates |
 | `/api/web/navidrome/sync-songs` | POST | Sync Navidrome songs to Nomarr |
 | `/api/web/navidrome/ping` | POST | Test Navidrome connectivity |
 | `/api/web/navidrome/status` | GET | Check if Navidrome is configured |

---

## Example Workflow

### First-Time Setup

1. **Process your music** — Scan and process your library in Nomarr (see [Getting Started](getting_started.md))
2. **Configure Navidrome connection** — Go to Navidrome page → API Settings → enter URL, username, password → Save
3. **Test connectivity** — Click Ping to verify the connection works
4. **Sync songs** — optional for plugin Instant Mix; required for backend push/personal playlist flows

### Creating Playlists

1. **Preview tags** — Check tag statistics to see what’s available
2. **Build rules** — Use the rule builder to define your playlist criteria
3. **Preview results** — See which tracks match before committing
4. **Generate or push** — Download as `.nsp` file or push directly to Navidrome

### Ongoing Use

- After processing new music, revisit the Navidrome page to regenerate playlists
- Run Sync Songs periodically if you use backend push/personal playlist flows and your Navidrome library changes independently
- Use templates for quick batch generation of common playlist types

---

## FAQ

**Q: Do I need to set up shared volumes between Nomarr and Navidrome?**

A: No. Nomarr pushes playlists to Navidrome over the Subsonic API. No shared filesystem is needed for playlist delivery. However, both must be able to access the same music files at some path.

**Q: What’s an .nsp file?**

A: It’s a Navidrome Smart Playlist file containing a query expression. You can download it and import it into Navidrome, or use the Push feature to skip the file entirely.

**Q: How often should I push or regenerate playlists?**

A: After processing new music or running calibration. Playlists are based on current tag data, so they reflect whatever has been analyzed.

**Q: Can I edit playlists after pushing?**

A: Yes, in Navidrome. However, if you push the same playlist name again from Nomarr, it will be replaced with the new version.

**Q: Do playlists update when calibration changes?**

A: Calibration affects tag thresholds, which affects which tracks match your rules. Regenerate playlists after recalibration to reflect the changes.

---

## See Also

- [Getting Started](getting_started.md) — Initial setup
- [Playlist Import](playlist_import.md) — Import Spotify/Deezer playlists
- [Troubleshooting](troubleshooting.md) — Common issues and solutions
- [Calibration Troubleshooting](../dev/calibration-troubleshooting.md) — Tune tag thresholds
- Interactive API docs at `http://localhost:8356/docs`

**Navidrome resources:**

- [Navidrome Documentation](https://www.navidrome.org/docs/)
- [Smart Playlists](https://www.navidrome.org/docs/usage/playlists/)
