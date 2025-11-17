# Nomarr

**Intelligent audio auto-tagging for your music library using state-of-the-art machine learning.**

Nomarr is a pre-alpha audio tagging system that analyzes your music files with Essentia's pre-trained ML models and writes rich metadata tags directly into MP3/M4A files. Perfect for organizing large libraries, discovering moods, and enriching metadata for music servers like Navidrome and Plex.

## WARNING

This is PRE-ALPHA program that is HEAVILY made with assistance of AI. I make no gaurentee it is functional, useful, or even worth installing yet. The codebase changes DAILY in rather large ways, and I'm not done staging things at all yet. Github hosting is mainly to get CI tooling and a working image to test with.

That said, I will take PR and feature requests, and do gaurentee that every line of code will be human-reviewed (and honestly... probably refactored into a much better shape than the current AI slop) Prior to releasing as a version 1.

Do also note (WITH A BIG CAPITAL WARNING) that the EFFNET embedder (so any EFFNET HEADS used) REQUIRES 9 GB of VRAM to run on GPU. and you want it on GPU, it's the difference between a 40s per song tagging job, and a 2 second per song tagging job. The embedder is cached in VRAM, to prevent spin up time
each song, and will remain resident on VRAM for some time after the last song is tagged (this is kinda legacy from API logic, where I'm expecting songs to trickle in)

## Roadmap

Currently, The program was designed with lidarr autotagging in mind, and a deep desire to "have ML inference that works without needing understanding and configuration of Tensorflow and Essentia" on music.

That evolved into the current shape, where the WEB UI is the first class citizen, and API takes a backseat.

Nomarr is currently in the process of being refactored into a ML tagging music library assistant, that will take a music library, tag using whatever essentia tf models are provided, monitor the library for changes, verify tags, calibrate heads to match in scale, and provide the user with
Tags that are ONLY high quality, playlists that work in navidrome, and analytics about their library's tags. So, you set the library path, scan, and get high quality ML tags in like... a day ish (based on my NAS share 18k song library I've built up... your time may be lower or higher).

![Web UI Dashboard](docs/images/placeholder-dashboard.png)
_Screenshot: Web UI dashboard - coming soon_

![CLI Processing](docs/images/placeholder-cli.png)
_Screenshot: CLI batch processing - coming soon_

---

## 🎯 What Does It Do?

Nomarr automatically tags your audio files with:

- **Mood & Emotion** - Happy, sad, aggressive, relaxed, party, etc.
- **Acoustic Properties** - Danceability, energy, timbre, brightness
- **Audio Characteristics** - Vocal presence, tonal/atonal classification

All tags are written as native metadata (ID3v2 for MP3, iTunes atoms for M4A, Vorbis comments for OGG/FLAC/Opus) with the `nom:` namespace prefix - no external database required.

**Note:** Nomarr comes with mood and acoustic property models. Additional models (genre, instruments, etc.) can be added by users but are not included by default.

---

## ✨ Key Features

- **🌐 Modern Web UI** - Browser interface for processing, monitoring, analytics, and configuration
- **🔌 Lidarr Integration** - Drop-in Docker sidecar that auto-tags imports via webhooks
- **📚 Library Scanner** - Automatic background scanning with tag extraction and analytics
- **📊 Calibration System** - Normalize model outputs with min-max scaling and drift tracking
- **⚡ GPU Accelerated** - NVIDIA CUDA support for fast ML inference
- **🎨 Rich Metadata** - Writes probabilities, tiers, and aggregated mood tags in native format (ID3v2/MP4)
- **📊 Queue System** - Background processing with pause/resume, status tracking, and error recovery
- **🎵 Navidrome Integration** - Smart playlist generation and config export
- **🔐 Secure** - API key authentication for automation, session-based auth for web UI
- **🐳 Docker Native** - Single container with NVIDIA GPU passthrough
- **🏗️ Clean Architecture** - Dependency injection, pure workflows, and isolated ML layer

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

2. **Start with Docker Compose:**

   ```yaml
   services:
     nomarr:
       build: .
       image: nomarr:latest
       container_name: nomarr
       user: "1000:1000"
       networks:
         - lidarr_network
       volumes:
         - ./config:/app/config
         - /path/to/music:/music # Must match Lidarr's path
       environment:
         - NOMARR_DB=/app/config/db/nomarr.sqlite
       deploy:
         resources:
           reservations:
             devices:
               - driver: nvidia
                 count: 1
                 capabilities: [gpu]
       restart: unless-stopped
   ```

   ```bash
   docker compose up -d
   ```

3. **Get your admin password:**

   Check container logs for the auto-generated password:

   ```bash
   docker compose logs nomarr | grep "Admin password"
   ```

4. **Access the Web UI:**

   - Navigate to `http://localhost:8356/`
   - Login with the admin password from step 3
   - Use the Process Files tab to tag your music!

5. **(Optional) For Lidarr Integration:**

   The API key is auto-generated and stored in the database. To retrieve it, query the database:

   ```bash
   docker compose exec nomarr sqlite3 /app/config/db/nomarr.sqlite \
     "SELECT value FROM meta WHERE key='api_key';"
   ```

---

## 📚 Usage

### Web UI (Recommended)

The easiest way to use Nomarr - modern browser interface for:

- **Processing files** - Single file or batch upload with real-time progress
- **Queue management** - Monitor jobs, pause/resume workers, clear errors
- **Library scanning** - Automatic tag scanning and analytics
- **Navidrome integration** - Smart playlist generation and config export
- **Calibration** - Generate and apply calibration to normalize model outputs
- **Tag analytics** - Mood distributions, correlations, and co-occurrences

Access at `http://localhost:8356/` (login with auto-generated admin password)

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

**Note:** For processing files, use the Web UI (`/`) which provides real-time progress and SSE streaming. The CLI focuses on administrative operations.

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

- **[API Reference](docs/API_REFERENCE.md)** - Complete endpoint documentation and Lidarr integration examples
- **[Calibration System](docs/CALIBRATION.md)** - ML model calibration with drift tracking (dev feature)
- **[Deployment Guide](docs/DEPLOYMENT.md)** - Docker setup, configuration, and troubleshooting
- **[Model Information](docs/modelsinfo.md)** - Details about Essentia ML models
- **[Navidrome Integration](docs/NAVIDROME_INTEGRATION.md)** - Smart playlist generation and config export
- **[Versioning Strategy](docs/VERSIONING.md)** - Semantic versioning and release process
- **[Configuration Guide](docs/README.md)** - Advanced configuration and architecture overview

---

## ⚠️ License & Usage

**Nomarr is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) - Non-Commercial use only**

This project is designed for the self-hosted music community and personal use. Commercial use is not permitted.

- **Attribution Required:** Credit Nomarr and the Music Technology Group, Universitat Pompeu Fabra (for Essentia models)
- **ShareAlike:** Derivative works must use the same license
- **Non-Commercial:** No commercial use without explicit permission

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for complete attribution and third-party license information.

---

## 🙏 Credits

Built with:

- **[Essentia](https://essentia.upf.edu/)** - Audio analysis and ML models by Music Technology Group, UPF
- **[TensorFlow](https://www.tensorflow.org/)** - Machine learning inference
- **[FastAPI](https://fastapi.tiangolo.com/)** - Modern Python web framework
- **[Rich](https://github.com/Textualize/rich)** - Beautiful terminal UI

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
