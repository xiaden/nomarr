# Getting Started with Nomarr

**Audience:** New users setting up Nomarr for the first time.

This guide covers installation, basic configuration, and first-time usage of Nomarr's audio tagging system.

## What is Nomarr?

Nomarr is an AI-powered audio tagging system that analyzes music files using machine learning models and writes rich metadata tags directly into audio files. It's designed for:

- **Personal music library organization** - Automatic mood and acoustic tagging
- **Lidarr integration** - Auto-tag new imports via webhooks
- **Navidrome smart playlists** - Generate playlists from ML-derived tags
- **Library analytics** - Understand your music collection through tag statistics

> **⚠️ Pre-Alpha Software**  
> Nomarr is under active development. Expect frequent changes, breaking updates, and incomplete features. See the [main README](../readme.md) for current status and warnings.

## Prerequisites

Before installing Nomarr, ensure you have:

- **Docker with NVIDIA GPU support** - Required for GPU-accelerated ML inference
  - NVIDIA GPU with ≥9GB VRAM (for effnet embeddings)
  - NVIDIA Container Toolkit installed
- **Music library** - Supported formats: MP3, M4A, OGG, FLAC, Opus
- **Lidarr** (optional) - For automated import tagging
- **Navidrome** (optional) - For smart playlist integration

### GPU Requirements

The effnet embedding model requires **9GB of VRAM** and provides significant performance benefits:

- **With GPU:** ~2 seconds per track
- **Without GPU:** ~40 seconds per track

The embedder is cached in VRAM between tracks to avoid spinup time, and remains resident for some time after processing completes.

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/xiaden/nomarr.git
cd nomarr
```

### 2. Create Configuration Directory

```bash
mkdir -p config/db
```

### 3. Configure Docker Compose

Create `docker-compose.yml`:

```yaml
services:
  nomarr:
    build: .
    image: nomarr:latest
    container_name: nomarr
    user: "1000:1000"
    networks:
      - lidarr_network # Optional: for Lidarr integration
    ports:
      - "8356:8356"
    volumes:
      - ./config:/app/config
      - /path/to/your/music:/music # Must match Lidarr's path if using integration
    environment:
      - NOMARR_DB=/app/config/db/nomarr.sqlite
      - NOMARR_CONFIG=/app/config/config.yaml
      - PORT=8356
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
```

**Important:** The music library path must be consistent between Nomarr and any integrated services (Lidarr, Navidrome).

### 4. Start Nomarr

```bash
docker compose up -d
```

On first startup, Nomarr will:

- Initialize the database
- Generate an admin password
- Load ML models into GPU memory
- Start the web server on port 8356

### 5. Retrieve Admin Password

Check the container logs for the auto-generated password:

```bash
docker compose logs nomarr | grep "Admin password"
```

You should see output like:

```
[KeyManagement] AUTO-GENERATED ADMIN PASSWORD:
[KeyManagement]   Xk8pL2mN9qR5tV3w
[KeyManagement] Save this password - it won't be shown again!
```

**Save this password immediately** - it's not shown again after startup.

## Basic Configuration

### Configuration File

Nomarr uses `config/config.yaml` for settings. On first run, a default config is created.

Key settings:

```yaml
# Library path (must match Docker mount)
library_path: /music

# Tag namespace prefix (configurable, default: nom)
namespace: nom

# Model directories
models_dir: /app/models

# Database path
database_path: /app/config/db/nomarr.sqlite

# Processing options
batch_size: 11 # Segments per GPU batch
cache_idle_timeout: 300 # Model cache timeout (seconds)

# Admin password (optional - uses auto-generated if not set)
# admin_password: your_password_here
```

**Note on namespace:** The namespace is configurable but defaults to `nom`. All tag examples in this documentation use `nom:` prefix, but your actual tags will use whatever namespace you configure.

### Accessing the Web UI

1. Navigate to `http://localhost:8356/`
2. Login with the admin password from container logs
3. You're ready to start tagging!

## First Time Usage

### Web UI Overview

The web interface provides:

- **Dashboard** - System status, queue stats, worker health
- **Process Files** - Upload files or scan directories for tagging
- **Queue** - Monitor processing jobs, pause/resume workers
- **Library** - Browse tagged files, view tag statistics
- **Navidrome** - Generate smart playlists, preview tag mappings
- **Calibration** - Generate and apply calibration for output normalization
- **Settings** - Configure namespace, paths, and processing options

### Processing Your First File

1. **Via Web UI:**

   - Click "Process Files" tab
   - Enter a file path or directory path
   - Click "Process" or "Batch Process"
   - Watch real-time progress in the queue view

2. **Via Library Scan:**
   - Configure `library_path` in config.yaml
   - Click "Scan Library" in the Library tab
   - Nomarr will discover all audio files and queue them

### Understanding Tag Output

Nomarr writes tags with the configured namespace prefix (default `nom:`):

**Individual model outputs:**

```
nom:danceability_essentia21-beta6-dev_effnet20220217_danceability20220825 = 0.7234
nom:aggressive_essentia21-beta6-dev_effnet20220217_aggressive20220825 = 0.1203
```

**Aggregated mood tags:**

```
nom:mood-strict = ["peppy", "party-like", "synth-like"]
nom:mood-regular = ["peppy", "party-like", "synth-like", "easy to dance to"]
nom:mood-loose = ["peppy", "party-like", "synth-like", "easy to dance to", "has vocals"]
```

Each tag includes:

- **Namespace prefix** - Configurable (default: `nom`)
- **Model identifier** - Essentia version, backbone, head name, date
- **Value** - Probability (0.0 to 1.0) or aggregated labels

See [Architecture Overview](architecture/overview.md) for details on tag structure and versioning.

## Lidarr Integration (Optional)

To automatically tag new imports from Lidarr:

### 1. Get API Key

Query the database for your auto-generated API key:

```bash
docker compose exec nomarr sqlite3 /app/config/db/nomarr.sqlite \
  "SELECT value FROM meta WHERE key='api_key';"
```

### 2. Create Connection Script

Create `lidarr-nomarr-tag.sh`:

```bash
#!/bin/bash
API_KEY="your-api-key-from-step-1"
curl -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"$lidarr_trackfile_path\",\"force\":true}" \
  http://nomarr:8356/api/v1/tag
```

Make it executable:

```bash
chmod +x lidarr-nomarr-tag.sh
```

### 3. Configure Lidarr

In Lidarr:

1. Go to Settings → Connect
2. Add "Custom Script"
3. Name: "Nomarr Auto-Tag"
4. Path: `/path/to/lidarr-nomarr-tag.sh`
5. Triggers: "On Import", "On Upgrade"

Now Lidarr will automatically tag all new imports!

See [Lidarr Integration](integration/lidarr.md) for detailed setup and troubleshooting.

## CLI Usage

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

**Note:** For processing files, use the Web UI which provides real-time progress and monitoring. The CLI focuses on administrative operations.

## Common Tasks

### Scanning Your Library

The library scanner discovers all audio files and queues them for processing:

1. Ensure `library_path` is set in `config.yaml`
2. Use Web UI → Library → "Scan Library"
3. Or use API: `POST /admin/scan` with API key

The scanner runs in the background and tracks progress in the database.

### Generating Calibration

Calibration normalizes model outputs across your library:

1. Tag at least 100 tracks (more is better)
2. Use Web UI → Calibration → "Generate Calibration"
3. Review min/max values and apply to library

See [Calibration System](../calibration/index.md) for details.

### Viewing Tag Analytics

The Web UI provides analytics:

- **Tag frequencies** - Most common tags in your library
- **Mood distribution** - Breakdown of aggregated moods
- **Correlations** - Which tags appear together
- **Co-occurrences** - Tags that commonly pair with a specific tag

Access via Web UI → Library → Analytics tab.

## Next Steps

- **[Deployment Guide](deployment.md)** - Production setup, optimization, troubleshooting
- **[API Reference](api/endpoints.md)** - Complete HTTP API documentation
- **[Navidrome Integration](integration/navidrome.md)** - Smart playlist generation
- **[Architecture Overview](architecture/overview.md)** - Understand how Nomarr works
- **[Calibration System](../calibration/index.md)** - Advanced tag tuning

## Troubleshooting

### Container Won't Start

Check logs for errors:

```bash
docker compose logs nomarr
```

Common issues:

- GPU not accessible - verify NVIDIA Container Toolkit
- Port 8356 already in use - change port in docker-compose.yml
- Volume mount permissions - ensure user 1000:1000 has access

### No Tags Written

Check:

1. File format is supported (MP3, M4A, OGG, FLAC, Opus)
2. File path is accessible from container
3. Queue shows job as "done" not "error"
4. Check job error message in queue view

### Slow Processing

- Verify GPU is being used (check logs for "Using GPU" messages)
- Ensure ≥9GB VRAM available
- Check model cache is active (warmup on first file takes ~30s)

### Can't Login to Web UI

- Verify admin password from container logs
- Check browser console for errors
- Try incognito/private browsing mode
- Clear browser cache and cookies

For more help, see [GitHub Issues](https://github.com/xiaden/nomarr/issues) or [Discussions](https://github.com/xiaden/nomarr/discussions).
