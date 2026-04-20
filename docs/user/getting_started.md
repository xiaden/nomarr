# Getting Started with Nomarr

**Quick Start Guide for Installing and Running Nomarr**

---

## ⚠️ Alpha Software

Nomarr is **alpha** software:

- Breaking changes are allowed before the 1.0 release
- Database schema changes include forward-only migrations (auto-applied on startup)
- No rollback support — backups recommended before major updates
- GPU strongly recommended for acceptable ML inference performance

---

## System Requirements

### Minimum Requirements

- **OS:** Linux (Ubuntu 22.04+ recommended) or Windows/macOS with Docker Desktop
- **RAM:** 8 GB minimum, 16 GB recommended
- **Storage:** 5 GB for application + space for your music library
- **Docker:** Docker 24.0+ and Docker Compose 2.20+

### GPU Requirements (Strongly Recommended)

Nomarr uses ONNX Runtime for audio analysis. CPU-only inference is **extremely slow** (10–30x slower than GPU).

**Supported GPUs:**

- **NVIDIA:** GTX 1060 or newer with CUDA support

**Not supported:**

- Intel integrated GPUs
- Older NVIDIA cards (pre-Pascal architecture)
- AMD GPUs (no ONNX Runtime ROCm support in Nomarr currently)

> **Performance Example:**
> Processing 1,000 tracks:
>
> - NVIDIA RTX 3060: ~15 minutes
> - CPU (16 cores): ~4–8 hours
> - CPU (8 cores): ~10–20 hours

---

## Installation (Docker)

Docker is the only supported installation method for end users.

### 1. Install Docker and Docker Compose

**Linux (Ubuntu/Debian):**

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Log out and log back in for group changes to take effect

# Install Docker Compose
sudo apt install docker-compose-plugin
```

**macOS:**

```bash
brew install --cask docker
# Start Docker Desktop from Applications
```

**Windows:**

- Install Docker Desktop from [docker.com](https://www.docker.com/products/docker-desktop)
- Enable WSL2 backend in Docker Desktop settings

### 2. Install NVIDIA Container Toolkit (Linux + NVIDIA GPU)

Required for GPU acceleration in Docker:

```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker
```

Verify GPU access:

```bash
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

### 3. Create Deployment Directory

```bash
mkdir -p /opt/nomarr
cd /opt/nomarr
```

### 4. Create Environment Files

**`nomarr-arangodb.env`** (for the ArangoDB container):

```bash
# Root password — REQUIRED for first-run provisioning
ARANGO_ROOT_PASSWORD=change_this_to_a_strong_password
ARANGO_NO_AUTH=0
```

**`nomarr.env`** (for the Nomarr container):

```bash
# ArangoDB connection
ARANGO_HOST=http://nomarr-arangodb:8529

# Root password — must match nomarr-arangodb.env
# Only needed for first-run provisioning
ARANGO_ROOT_PASSWORD=change_this_to_a_strong_password
```

!!! tip
    Generate a strong password with `openssl rand -hex 32`.

### 5. Create `config/nomarr.yaml`

```bash
mkdir -p config
```

Create `config/nomarr.yaml`:

```yaml
# Nomarr Configuration
# Most settings use sensible defaults. Libraries are managed via the Web UI.

# Library root — base path for all libraries (inside container)
library_root: "/media"

# Models directory (packaged in image, usually no need to change)
models_dir: "/app/models"
```

!!! note
    On first run, Nomarr connects to ArangoDB using `ARANGO_ROOT_PASSWORD`, provisions the database and user, then generates a secure application password stored in `config/nomarr.yaml` as `arango_password`. You never need to manage this manually.

### 6. Create `compose.yaml`

Create a `compose.yaml` in your deployment directory. The example below matches the official configuration:

```yaml
services:
  nomarr-arangodb:
    image: arangodb:latest
    container_name: nomarr-arangodb
    env_file:
      - nomarr-arangodb.env
    command: ["--vector-index"]
    volumes:
      - ./config/arangodb:/var/lib/arangodb3
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "arangosh --server.endpoint tcp://127.0.0.1:8529 --server.username root --server.password \"$$ARANGO_ROOT_PASSWORD\" --javascript.execute-string 'db._version()' >/dev/null 2>&1"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s

  nomarr:
    image: ghcr.io/xiaden/nomarr:latest
    container_name: nomarr
    user: "1000:1000"
    stop_grace_period: 30s
    ports:
      - "8356:8356"
    volumes:
      - ./config:/app/config
      - /path/to/your/music:/media:ro  # CHANGE THIS to your music library path
    env_file:
      - nomarr.env
    depends_on:
      nomarr-arangodb:
        condition: service_healthy
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

```

**Key changes to make:**

- Replace `/path/to/your/music` with your actual music library path
- If you don’t have a reverse proxy, uncomment the `ports:` section for direct access
- Remove the `deploy.resources` GPU section if running CPU-only (not recommended)
- If you don’t have an existing `front_network`, either create one (`docker network create front_network`) or replace with a simpler network setup

### 7. Start Nomarr

Models are **pre-packaged** in the Docker image — no separate download needed.

```bash
docker compose up -d
```

View logs:

```bash
docker compose logs -f nomarr
```

Stop Nomarr:

```bash
docker compose down
```

---

## First-Time Setup

### 1. Access the Web UI

Nomarr runs on port **8356** inside the container. How you access it depends on your setup:

- **With reverse proxy:** `https://nomarr.yourdomain.com`
- **Direct access:** Uncomment `ports` in compose.yaml, then open `http://localhost:8356`

You should see the Nomarr dashboard.

### 2. Add Your Music Library

All library management is done via the Web UI:

1. Navigate to the **Libraries** page from the sidebar
2. Click **Add Library**
3. Enter a library name (e.g., "My Music")
4. Use the path picker to select a directory (must be within the configured `library_root`)
5. Enable/disable the library as needed
6. Click **Create**

!!! note
    The library path must be accessible inside the Nomarr container. Ensure your music directory is mounted as a volume in `compose.yaml`.

### 3. Scan Your Library

1. Go to the **Libraries** page
2. Find your library in the list
3. Click the **Scan** button on the library card
4. Monitor progress — the scan state updates in real-time

**Scan behavior:**

- Finds all audio files in the library directory
- Reads file metadata (artist, album, title, duration)
- Discovers new and changed files for processing
- **Workers automatically start processing** discovered files (no manual intervention needed)

**Preview before scanning:** Click **Preview** to see how many files will be found without actually starting processing.

**Expected time:** 1–5 minutes for 10,000 tracks (scan only; ML processing is separate).

### 4. File Watching (Automatic Incremental Scanning)

Once a library is added and initially scanned, Nomarr automatically monitors the directory for changes:

- **Detects:** File additions, modifications, and deletions
- **Response time:** 2–5 seconds (event mode) or 30–120 seconds (polling mode)
- **Incremental scans:** Only changed folders are rescanned

**Watch Modes:**

 | Mode | How it works | Best for |
 | ------ | ------------- | ---------- |
 | **Event** (default) | Real-time filesystem events via watchdog | Local filesystems |
 | **Polling** | Periodic full scans at fixed intervals | Network mounts (NFS/SMB) |

**Enabling Polling Mode** (for network-mounted libraries):

Add to your `nomarr.env`:

```bash
NOMARR_WATCH_MODE=poll
```

Then restart: `docker compose restart nomarr`

### 5. Processing Runs Automatically

**Discovery workers start automatically** when Nomarr launches. There’s no need to manually start processing.

**How it works:**

- Workers discover files that need processing and analyze them
- Each file: compute audio embeddings → run ML head models → extract tags
- Results are stored in the database and visible in the Web UI
- Failed files are logged with errors

**Expected time:**

- With GPU: ~1–2 minutes per 100 tracks
- Without GPU: ~30–60 minutes per 100 tracks

**Pause/Resume workers:**

- Navigate to the **Admin** page in the Web UI
- Use the **Pause Workers** / **Resume Workers** buttons
- Workers finish their current work before pausing

### 6. Monitor Progress

The **Dashboard** page shows:

- Total tracks processed
- Worker status (active/paused)
- Processing rate (tracks/minute)
- Library statistics

The **Admin** page shows:

- Worker health and status
- Pause/Resume controls

---

## Common Workflows

### Adding New Music Files

**Automatic (Recommended):**

- Copy files to your library directory
- File watcher detects changes within seconds
- Incremental scan triggers automatically
- New files are discovered and processed
- **No manual action required**

**Manual:**

1. Go to the **Libraries** page
2. Click **Scan** on your library
3. Workers automatically process new files

### Pause Processing

Useful before system maintenance or to free GPU:

1. Go to the **Admin** page
2. Click **Pause Workers**
3. Workers finish current work and stop
4. Click **Resume Workers** when ready to continue

### Export Tags to Navidrome

After processing, generate smart playlists:

1. Go to the **Navidrome** page
2. Preview your tag statistics
3. Use playlist templates or create custom queries
4. Generate playlist files or push directly to Navidrome

See [Navidrome Integration](navidrome.md) for detailed instructions.

---

## CLI Reference

Nomarr provides a small set of CLI commands for maintenance tasks that run **outside** the main application:

 | Command | Description |
 | --------- | ------------- |
 | `nom cleanup` | Remove orphaned entities (artists, albums, genres, labels, years) with no songs |
 | `nom cleanup --dry-run` | Preview what would be cleaned up without deleting |
 | `nom manage-password show` | Display current password hash |
 | `nom manage-password verify` | Test if a password is correct |
 | `nom manage-password reset` | Change the admin password |

**Running CLI commands in Docker:**

```bash
# Remove orphaned entities
docker exec -it nomarr nom cleanup

# Preview orphaned entities (dry run)
docker exec -it nomarr nom cleanup --dry-run

# Change admin password
docker exec -it nomarr nom manage-password reset
```

!!! note
    Library management, scanning, and worker control are handled through the Web UI, not the CLI.

---

## Troubleshooting

### GPU Not Detected

**Symptoms:** Processing is extremely slow, or logs show CPU-only inference.

**Solutions:**

1. **Verify GPU access in the container:**

    ```bash
    docker exec -it nomarr nvidia-smi
    ```

    Should show GPU info. If not, check NVIDIA Container Toolkit installation.

2. **Check compose.yaml has GPU config:**

    ```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    ```

3. **Verify ONNX Runtime sees GPU:**

    ```bash
    docker exec -it nomarr python -c "import onnxruntime; print(onnxruntime.get_available_providers())"
    ```

    Should include `CUDAExecutionProvider`. If only `CPUExecutionProvider`, the GPU is not available to ONNX Runtime.

### Workers Not Processing

**Symptoms:** Files are scanned but nothing is being processed.

**Solutions:**

1. **Check logs:**

    ```bash
    docker compose logs -f nomarr
    ```

    Look for worker startup errors.

2. **Verify workers are active:**

    Check the **Admin** page in the Web UI to see worker status.

3. **Restart Nomarr:**

    ```bash
    docker compose restart nomarr
    ```

### Database Connection Errors

**Symptoms:** "Connection refused" or "database unavailable" errors.

**Solutions:**

1. **Check ArangoDB is running:**

    ```bash
    docker compose ps nomarr-arangodb
    docker compose logs nomarr-arangodb
    ```

2. **Verify credentials:**

    Check that `ARANGO_ROOT_PASSWORD` matches in both `.env` files.
    After first run, check `config/nomarr.yaml` has a generated `arango_password`.

3. **Restart services:**

    ```bash
    docker compose restart
    ```

### Calibration

Calibration adjusts tag confidence thresholds based on your specific library. It improves tagging accuracy.

- Need at least 100 processed tracks for calibration to run
- More tracks = better calibration (1,000+ recommended)
- Navigate to the **Calibration** page in the Web UI to see status
- See [Calibration Troubleshooting](../dev/calibration-troubleshooting.md) for advanced details

---

## Next Steps

1. **Explore the API** → Visit `http://localhost:8356/docs` for interactive API documentation
2. **Configure Navidrome Integration** → [Navidrome Integration](navidrome.md)
3. **Import Streaming Playlists** → [Playlist Import](playlist_import.md)
4. **Production Deployment** → [Deployment Guide](deployment.md)
5. **Troubleshooting** → [Troubleshooting](troubleshooting.md)

---

## Getting Help

**Before asking for help:**

1. Check logs: `docker compose logs -f nomarr | grep -i error`
2. Check system health in the Web UI (**Dashboard** and **Admin** pages)
3. Verify GPU status: `docker exec -it nomarr nvidia-smi`
4. Check the [Troubleshooting](troubleshooting.md) guide

**Community support:**

- GitHub Issues: Report bugs and feature requests
- GitHub Discussions: Ask questions and share experiences

**When reporting issues, include:**

- Nomarr version (shown in Web UI footer)
- Relevant logs (last 50 lines)
- GPU hardware and driver version
- Steps to reproduce
