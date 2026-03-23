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

### 4. Sync Songs (Optional but Recommended)

Click **Sync Songs** to pull your Navidrome library into Nomarr’s database. This enables:

- Resolving Nomarr file IDs to Navidrome song IDs when pushing playlists
- Better cross-referencing between the two systems

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
    Push requires that you’ve run **Sync Songs** at least once so Nomarr can map its files to Navidrome’s song IDs.

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
|----------|----------|
| **Mood** | energetic, mellow, happy, sad, aggressive, peaceful |
| **Genre** | rock, pop, electronic, jazz, classical, hip hop, metal |
| **Instrumentation** | acoustic, electric, vocal, instrumental |
| **Rhythm** | danceable, fast, slow |
| **Production** | live, studio, lo-fi, hi-fi |

See the full tag vocabulary in the Nomarr Web UI under the **Tags** page.

**Tag scores** range from 0.0 to 1.0, where higher values indicate stronger presence of that characteristic. When building playlists, you set threshold values to filter tracks.

If you’ve enabled **calibration**, tag thresholds are automatically tuned to your specific library for better accuracy.

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

1. **Run Sync Songs** — Nomarr needs an up-to-date copy of Navidrome’s library to resolve file IDs to song IDs
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
|----------|--------|-------------|
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
4. **Sync songs** — Click Sync Songs to import Navidrome’s library

### Creating Playlists

1. **Preview tags** — Check tag statistics to see what’s available
2. **Build rules** — Use the rule builder to define your playlist criteria
3. **Preview results** — See which tracks match before committing
4. **Generate or push** — Download as `.nsp` file or push directly to Navidrome

### Ongoing Use

- After processing new music, revisit the Navidrome page to regenerate playlists
- Run Sync Songs periodically if your Navidrome library changes independently
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
