# Nomarr

**Intelligent audio auto-tagging for your music library using state-of-the-art machine learning.**

Nomarr is a pre-alpha audio tagging system that analyzes your music files with Essentia's pre-trained ML models and writes rich metadata tags directly into MP3/M4A/FLAC/OGG/Opus files. Perfect for organizing large libraries, discovering moods, and enriching metadata for music servers like Navidrome and Plex.

## WARNING

This is a PRE-ALPHA program that is HEAVILY made with assistance of AI. I make no guarantee it is functional, useful, or even worth installing yet. The codebase changes DAILY in rather large ways, and I'm not done staging things at all yet. GitHub hosting is mainly to get CI tooling and a working image to test with.

That said, I will take PR and feature requests, and do guarantee that every line of code will be human-reviewed (and honestly... probably refactored into a much better shape than the current AI slop) prior to releasing as a version 1.

Do also note (WITH A BIG CAPITAL WARNING) that the EFFNET embedder (so any EFFNET HEADS used) REQUIRES 9 GB of VRAM to run on GPU. And you want it on GPU — it's the difference between a 40s per song tagging job and a 2 second per song tagging job. The embedder is cached in VRAM to prevent spin-up time each song, and will remain resident on VRAM for some time after the last song is tagged.

---

## 🎯 What Does It Do?

Nomarr automatically tags your audio files with:

- **Mood & Emotion** — Happy, sad, aggressive, relaxed, party, etc.
- **Acoustic Properties** — Danceability, energy, timbre, brightness
- **Audio Characteristics** — Vocal presence, tonal/atonal classification

All tags are written as native metadata (ID3v2 for MP3, iTunes atoms for M4A, Vorbis comments for OGG/FLAC/Opus) with the `nom:` namespace prefix — no external database required.

You set a library path, scan, and get high quality ML tags in roughly a day (based on an 18k song library over a NAS share — your time may be lower or higher).

**Note:** Nomarr comes with mood and acoustic property models. Additional models (genre, instruments, etc.) can be added by users but are not included by default.

---

## ✨ Key Features

- **🌐 Modern Web UI** — Full browser interface for library management, analytics, calibration, and integrations
- **📚 Library Scanner** — Automatic background scanning with tag extraction and real-time progress
- **👁️ File Watching** — Detects filesystem changes and triggers incremental scans automatically (2–5 second response)
- **📊 Calibration System** — Normalize model outputs across heads with convergence tracking and drift detection
- **🔍 Library Insights** — Collection overview, mood analysis, tag co-occurrence matrix, and genre/year distributions
- **🎵 Navidrome Integration** — Smart playlist (.nsp) generation and TOML config export
- **📥 Playlist Import** — Convert Spotify and Deezer playlists to local M3U with fuzzy matching, metadata display, and manual search
- **⚡ GPU Accelerated** — NVIDIA CUDA support for fast ML inference
- **🎨 Rich Metadata** — Writes probabilities, tiers, and aggregated mood tags in native format
- **📊 Queue System** — Background processing with pause/resume, status tracking, and error recovery
- **🔌 Lidarr Integration** — Drop-in Docker sidecar that auto-tags imports via webhooks
- **🔐 Secure** — API key authentication for automation, session-based auth for web UI
- **🐳 Docker Native** — Single container with NVIDIA GPU passthrough

---

## 🖥️ Web UI

### Dashboard

Real-time system overview with processing progress (including velocity tracking and ETA), library statistics with genre/year charts, and recent scan activity.

<img width="100%" alt="Dashboard" src="docs/screenshots/dashboard.png" />

### Browse

Hierarchical library browser with Artist → Album → Track drill-down, plus flat entity tabs for Artists, Albums, Genres, and Years. Tag-based exploration lets you find songs by exact string match or nearest numeric value.

<img width="100%" alt="Browse" src="docs/screenshots/browse.png" />

Library management is built in — add libraries, trigger scans, and monitor scan status from a collapsible panel:

<img width="60%" alt="Library Management" src="docs/screenshots/library-management.png" />

### Insights

Library analytics organized into three sections: **Collection Overview** (stats, top genres, years, artists), **Mood Analysis** (coverage, balance, vibes, mood combos), and **Advanced** (tag frequency distributions and a full co-occurrence matrix). All filterable by library.

<img width="100%" alt="Insights" src="docs/screenshots/insights.png" />

### Calibration

Generate calibration profiles from your library data, apply them to normalize model outputs, and update new files. Convergence tracking shows per-head stability across calibration rounds with summary stats and P5/P95 charts.

<img width="100%" alt="Calibration" src="docs/screenshots/calibration.png" />

### Navidrome

Two tools for Navidrome users: **Generate Config** creates a TOML configuration file mapping Nomarr tags to Navidrome's smart playlist fields. **Playlist Maker** builds `.nsp` smart playlist files using tag-based filter groups with preview and sort options.

<img width="100%" alt="Navidrome" src="docs/screenshots/navidrome.png" />

### Playlist Import

Paste a Spotify or Deezer playlist URL and Nomarr converts it to a local M3U file by fuzzy-matching tracks against your library. Results show match confidence, matched file metadata (artist, album, duration, bitrate), and let you search for alternatives or manually add tracks.

<img width="100%" alt="Playlist Import" src="docs/screenshots/playlist-import.png" />

---

## 🚀 Quick Start

### Prerequisites

- Docker with NVIDIA GPU support (for GPU acceleration)
- Lidarr (optional, for automatic tagging)
- Music library mounted at consistent path

### Installation

1. **Clone and configure:**

   ```bash
   git clone https://github.com/xiaden/nomarr.git
   cd nomarr
   mkdir -p config/db
   ```

2. **Configure environment files:**

   ```bash
   # Copy example env files
   cp docker/nomarr-arangodb.env.example docker/nomarr-arangodb.env
   cp docker/nomarr.env.example docker/nomarr.env

   # Edit docker/nomarr-arangodb.env and set a strong root password
   # Edit docker/nomarr.env and set the same root password
   ```

3. **Start with Docker Compose:**

   ```bash
   docker compose up -d
   ```

   On first run, Nomarr will:
   - Provision the ArangoDB database
   - Generate an app password (stored in `config/nomarr.yaml`)
   - Create an admin password for the web UI

4. **Get your admin password:**

   Check container logs for the auto-generated password:

   ```bash
   docker compose logs nomarr | grep "Admin password"
   ```

5. **Access the Web UI:**

   - Navigate to `http://localhost:8356/`
   - Login with the admin password from step 4
   - Add a library and start scanning!

6. **(Optional) For Lidarr Integration:**

   The API key is auto-generated on first run. Retrieve it from the web UI settings page or check the container logs:

   ```bash
   docker compose logs nomarr | grep "API key"
   ```

---

## 📚 Usage

### Web UI (Recommended)

The easiest way to use Nomarr — modern browser interface for:

- **Library management** — Add libraries, trigger scans, view scan history
- **File watching** — Automatic incremental scanning when files are added/modified (enabled by default)
- **Browse & explore** — Hierarchical drill-down and flat entity tabs with tag-based search
- **Insights** — Mood distributions, tag correlations, and co-occurrence analysis
- **Calibration** — Generate and apply calibration to normalize model outputs
- **Navidrome integration** — Smart playlist generation and config export
- **Playlist import** — Convert Spotify/Deezer playlists to local M3U files

Access at `http://localhost:8356/` (login with auto-generated admin password)

**File Watching:** Once a library is added and scanned, Nomarr automatically monitors it for changes. When files are added, modified, or deleted, an incremental scan is triggered within 2–5 seconds (event mode) or 30–120 seconds (polling mode).

For network mounts (NFS/SMB/CIFS), use polling mode for reliable detection:
```bash
# Add to docker-compose.yml environment:
environment:
  - NOMARR_WATCH_MODE=poll
```

### CLI

Administrative commands for queue and system management:

```bash
# Remove jobs from queue
docker exec nomarr nom remove <job_id>          # Remove specific job
docker exec nomarr nom remove --all             # Remove all non-running jobs
docker exec nomarr nom remove --status error    # Remove failed jobs

# Clean up old completed jobs
docker exec nomarr nom cleanup --hours 168      # Remove jobs older than 7 days

# Reset stuck or failed jobs
docker exec nomarr nom admin-reset --stuck      # Reset jobs stuck in 'running' state
docker exec nomarr nom admin-reset --errors     # Reset all failed jobs to retry

# Model cache management
docker exec nomarr nom cache-refresh            # Rebuild cache after adding models

# Admin password management
docker exec nomarr nom manage-password show     # Display password hash
docker exec nomarr nom manage-password verify   # Test a password
docker exec nomarr nom manage-password reset    # Change admin password
```

**Note:** For processing files, use the Web UI which provides real-time progress and SSE streaming. The CLI focuses on administrative operations.

### Lidarr Integration

Configure a custom script in Lidarr (Settings → Connect) to auto-tag on import:

```bash
#!/bin/bash
API_KEY="your-api-key-here"
curl -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"$lidarr_trackfile_path\",\"force\":true}" \
  http://nomarr:8356/api/v1/tag
```

---

## 🎵 Example Output

Nomarr writes tags using the `nom:` namespace prefix:

```
nom:danceability_essentia21-beta6-dev_effnet20220217_danceability20220825 = 0.7234
nom:aggressive_essentia21-beta6-dev_effnet20220217_aggressive20220825 = 0.1203
nom:genre_electronic_essentia21-beta6-dev_effnet20220217_genre_electronic20220825 = 0.8941
nom:voice_instrumental_essentia21-beta6-dev_effnet20220217_voice_instrumental20220825 = 0.2341
nom:bright_essentia21-beta6-dev_effnet20220217_bright20220825 = 0.4514
nom:mood-strict = ["peppy", "party-like", "synth-like", "bright timbre"]
nom:mood-regular = ["peppy", "party-like", "synth-like", "bright timbre", "easy to dance to"]
nom:mood-loose = ["peppy", "party-like", "synth-like", "bright timbre", "easy to dance to", "has vocals"]
nom_version = 1.0.0
```

Each numeric tag includes the full model head identifier (model version, backbone, head name, and date). Aggregated mood tags combine predictions across multiple heads using human-readable labels. The version tag tracks which tagger version processed each file.

---

## 📖 Documentation

- **[Getting Started](docs/user/getting_started.md)** — Installation, setup, and first steps
- **[API Reference](docs/user/api_reference.md)** — Complete endpoint documentation and examples
- **[Deployment Guide](docs/user/deployment.md)** — Docker setup, configuration, and production best practices
- **[Navidrome Integration](docs/user/navidrome.md)** — Smart playlist generation guide
- **[Architecture](docs/dev/architecture.md)** — System design and component overview
- **[Developer Documentation](docs/index.md)** — Complete documentation index

---

## 🗂️ Repository Structure

This is currently a **monorepo** containing multiple independent projects:

| Directory | Purpose | Future |
|-----------|---------|--------|
| `nomarr/` | Python backend (FastAPI, clean architecture) | Core project |
| `frontend/` | React/TypeScript SPA | Core project |
| `code-intel/` | MCP server for Python code navigation | → Separate repo |
| `.github/skills/` | GitHub Copilot skill definitions | → Separate repo or archive |
| `scripts/` | Build tools, viewers, analysis scripts | Part of core |
| `e2e/`, `tests/` | Integration and unit tests | Part of core |

**Note:** `code-intel/` is architecturally independent and will eventually split into its own repository. Until then, it's tracked in the main git history but maintains its own `pyproject.toml`, tests, and documentation.

---

## ⚠️ License & Usage

**Nomarr is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) — Non-Commercial use only**

This project is designed for the self-hosted music community and personal use. Commercial use is not permitted.

- **Attribution Required:** Credit Nomarr and the Music Technology Group, Universitat Pompeu Fabra (for Essentia models)
- **ShareAlike:** Derivative works must use the same license
- **Non-Commercial:** No commercial use without explicit permission

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for complete attribution and third-party license information.

---

## 🙏 Credits

Built with:

- **[Essentia](https://essentia.upf.edu/)** — Audio analysis and ML models by Music Technology Group, UPF
- **[TensorFlow](https://www.tensorflow.org/)** — Machine learning inference
- **[FastAPI](https://fastapi.tiangolo.com/)** — Modern Python web framework
- **[Rich](https://github.com/Textualize/rich)** — Beautiful terminal UI

See [Credits & Technologies](docs/README.md#credits) for complete list.

---

## 🤝 Contributing

Contributions are welcome! This project is in active development.

**Note:** Please consult with MTG, UPF regarding any contributions that modify model processing or create derivative works of the ML models, as they are subject to CC BY-NC-SA 4.0 ShareAlike terms.

---

## 💬 Support

- **Issues:** [GitHub Issues](https://github.com/xiaden/nomarr/issues)
- **Discussions:** [GitHub Discussions](https://github.com/xiaden/nomarr/discussions)

---

**Made with ❤️ for the self-hosted music community**
