# Nomarr

**Intelligent audio auto-tagging for your music library using state-of-the-art machine learning.**

Nomarr analyzes your music files with Essentia's pre-trained ML models and writes rich metadata tags directly into MP3/M4A files. Perfect for organizing large libraries, discovering moods, and enriching metadata for music servers like Navidrome and Plex.

![Web UI Dashboard](docs/images/placeholder-dashboard.png)
_Screenshot: Web UI dashboard - coming soon_

![CLI Processing](docs/images/placeholder-cli.png)
_Screenshot: CLI batch processing - coming soon_

---

## 🎯 What Does It Do?

Nomarr automatically tags your audio files with:

- **Mood & Emotion** - Happy, sad, aggressive, relaxed, party, etc.
- **Genre Classification** - Electronic, rock, classical, jazz, and more
- **Instruments** - Piano, guitar, strings, voice, percussion
- **Acoustic Properties** - Danceability, energy, timbre
- **Multi-value Tags** - Native support for complex metadata

All tags are written as native metadata (ID3v2 for MP3, iTunes atoms for M4A) - no external database required.

---

## ✨ Key Features

- **🔌 Lidarr Integration** - Drop-in Docker sidecar that auto-tags imports via webhooks
- **🌐 Web UI** - Modern browser interface for monitoring, queue management, and batch processing
- **⚡ GPU Accelerated** - NVIDIA CUDA support for ~10x faster processing
- **🎨 Rich Metadata** - Writes probabilities, tiers, and aggregated mood tags
- **📊 Queue System** - Background processing with pause/resume, status tracking, and cleanup
- **🔐 Secure** - API key authentication for automation, session-based auth for web UI
- **🐳 Docker Native** - Single container with NVIDIA GPU passthrough

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
         - NOMARR_DB=/app/config/db/essentia.sqlite
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

3. **Get your API key:**

   ```bash
   docker compose exec nomarr python3 -m nomarr.manage_key --show
   ```

4. **Access the Web UI:**
   - Navigate to `http://localhost:8356/`
   - Login with auto-generated admin password (check logs: `docker compose logs nomarr | grep "Admin password"`)

---

## 📚 Usage

### Web UI

The easiest way to use Nomarr - point and click interface for processing files, managing the queue, and monitoring system status.

### CLI

Process files directly from the command line:

```bash
# Process a single file
docker exec nomarr nom run /music/Album/Track.mp3

# Process entire directory
docker exec nomarr nom run /music/Album --recursive

# Check queue status
docker exec nomarr nom list

# View tags in file
docker exec nomarr nom show-tags /music/Track.mp3
```

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

Nomarr writes tags under the `essentia:` namespace:

```
essentia:danceability = 0.7234
essentia:danceability_tier = medium
essentia:aggressive = 0.1203
essentia:aggressive_tier = low
essentia:mood-strict = ["happy", "party", "not sad", "not aggressive"]
essentia:mood-regular = ["happy", "party", "energetic", "not sad"]
essentia:genre_electronic = 0.8941
essentia:voice_instrumental = 0.2341
```

---

## 📖 Documentation

- **[API Reference](docs/API_REFERENCE.md)** - Complete endpoint documentation and Lidarr integration examples
- **[Deployment Guide](docs/DEPLOYMENT.md)** - Docker setup, configuration, and troubleshooting
- **[Model Information](docs/modelsinfo.md)** - Details about Essentia ML models
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
