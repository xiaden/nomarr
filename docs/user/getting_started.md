# Getting Started with Nomarr

**Quick Start Guide for Installing and Using Nomarr**

---

## ⚠️ Pre-Alpha Status

Nomarr is in **pre-alpha** development:

- No backward compatibility guarantees
- Database schemas may change between versions
- Breaking changes expected
- Recommended for testing and development only
- GPU recommended for acceptable performance

---

## System Requirements

### Minimum Requirements

- **OS:** Linux (Ubuntu 22.04+ recommended), macOS, Windows with WSL2
- **RAM:** 8 GB minimum, 16 GB recommended
- **Storage:** 10 GB for models + space for your music library
- **Python:** 3.10+ (for non-Docker installations)
- **Docker:** Docker 24.0+ and Docker Compose 2.20+ (for Docker installations)

### GPU Requirements (Strongly Recommended)

Nomarr uses TensorFlow models for audio analysis. CPU-only inference is **extremely slow** (10-30x slower than GPU).

**Supported GPUs:**
- **NVIDIA:** GTX 1060 or newer (CUDA 11.8+ required)
- **AMD:** ROCm-compatible GPUs (experimental, less tested)
- **Apple Silicon:** M1/M2/M3 with Metal acceleration (experimental)

**Not supported:**
- Intel integrated GPUs
- Older NVIDIA cards (pre-Pascal architecture)

> **Performance Example:**  
> Processing 1000 tracks:
> - NVIDIA RTX 3060: ~15 minutes
> - AMD CPU (16 cores): ~4-8 hours
> - Intel CPU (8 cores): ~10-20 hours

---

## Installation

### Docker Installation (Recommended)

Docker installation is the easiest way to run Nomarr with GPU support.

#### 1. Install Docker and Docker Compose

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

#### 2. Install NVIDIA Container Toolkit (Linux + NVIDIA GPU)

Required for GPU acceleration in Docker:

```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker
```

Verify GPU access:
```bash
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

#### 3. Clone Nomarr Repository

```bash
git clone https://github.com/yourusername/nomarr.git
cd nomarr
```

#### 4. Configure Nomarr

Create environment files as described in the repository's example files:

**`nomarr-arangodb.env`** (for the ArangoDB container):
```bash
ARANGO_ROOT_PASSWORD=your-secure-root-password
```

**`nomarr.env`** (for the Nomarr container):
```bash
ARANGO_HOST=http://nomarr-arangodb:8529
ARANGO_ROOT_PASSWORD=your-secure-root-password
```

Create `config/config.yaml`:

```yaml
# Nomarr Configuration
# Note: Database credentials are managed automatically.
# On first run, Nomarr provisions the ArangoDB database and stores
# the generated password in this file under 'arango_password'.

library:
  paths:
    - "/music"  # Path inside container
  extensions:
    - ".flac"
    - ".mp3"
    - ".ogg"
    - ".m4a"
    - ".wav"

processing:
  workers: 2  # Number of parallel workers (adjust based on GPU memory)
  queue_sizes:
    processing: 500
    calibration: 100
  batch_size: 8  # Increase with more GPU memory

ml:
  models_dir: "/models"
  backends:
    - "essentia"
  cache_embeddings: true

server:
  host: "0.0.0.0"
  port: 8356  # Internal port (mapped to 8888 externally)

navidrome:
  export_dir: "/data/playlists"
```

**Important settings:**
- `library.paths`: Map your music directory (configured in docker-compose.yml)
- `processing.workers`: Start with 2, increase if you have >8GB GPU memory
- `processing.batch_size`: Increase to 16-32 with high-end GPUs

#### 5. Configure Docker Compose

The repository includes a working `docker-compose.yml`. Key sections:

```yaml
services:
  nomarr-arangodb:
    image: arangodb:3.12
    container_name: nomarr-arangodb
    env_file:
      - nomarr-arangodb.env
    volumes:
      - nomarr-arangodb-data:/var/lib/arangodb3
    restart: unless-stopped

  nomarr:
    build: .
    container_name: nomarr
    depends_on:
      - nomarr-arangodb
    env_file:
      - nomarr.env
    ports:
      - "8888:8356"  # External:Internal
    volumes:
      - ./config:/config
      - ./models:/models
      - /path/to/your/music:/music:ro  # CHANGE THIS
    environment:
      - NVIDIA_VISIBLE_DEVICES=all  # For GPU support
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

volumes:
  nomarr-arangodb-data:
```

**Key changes:**
- Replace `/path/to/your/music` with your actual music library path
- Remove GPU configuration if running CPU-only (not recommended)

#### 6. Download Models

Nomarr requires pre-trained TensorFlow models:

```bash
# Download models (run from nomarr directory)
./scripts/download_models.sh

# Or manually download and extract to models/
# Expected structure:
# models/
#   effnet/
#     embeddings/
#       discogs-effnet-bs64-1.pb
#     heads/
#       msd-musicnn-1.pb
#       ...
```

Model files total ~2GB. See [docs/upstream/modelsinfo.md](../upstream/modelsinfo.md) for details.

#### 7. Start Nomarr

```bash
docker-compose up -d
```

View logs:
```bash
docker-compose logs -f nomarr
```

Stop Nomarr:
```bash
docker-compose down
```

---

### Native Installation (Advanced)

For development or if you can't use Docker:

#### 1. Install System Dependencies

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install -y python3.10 python3-pip python3-venv \
  libsndfile1 ffmpeg libavcodec-extra
```

**macOS:**
```bash
brew install python@3.10 libsndfile ffmpeg
```

#### 2. Install NVIDIA Drivers and CUDA (Linux + NVIDIA GPU)

```bash
# Install NVIDIA driver (525+ recommended)
sudo apt install nvidia-driver-525

# Download and install CUDA 11.8
wget https://developer.download.nvidia.com/compute/cuda/11.8.0/local_installers/cuda_11.8.0_520.61.05_linux.run
sudo sh cuda_11.8.0_520.61.05_linux.run

# Add to ~/.bashrc
export PATH=/usr/local/cuda-11.8/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda-11.8/lib64:$LD_LIBRARY_PATH
```

Reboot after installation.

#### 3. Clone and Setup Python Environment

```bash
git clone https://github.com/yourusername/nomarr.git
cd nomarr

# Create virtual environment
python3.10 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install TensorFlow with GPU support
pip install tensorflow[and-cuda]==2.15.0
```

#### 4. Download Models

```bash
./scripts/download_models.sh
```

#### 5. Configure Nomarr

Set up environment variables:
```bash
export ARANGO_HOST=http://localhost:8529
export ARANGO_ROOT_PASSWORD=your-root-password
```

Create `config/config.yaml`:

```yaml
# Database credentials are auto-generated on first run.
# See 'arango_password' after initialization.

library:
  paths:
    - "/home/user/Music"  # Your actual music path

ml:
  models_dir: "./models"

navidrome:
  export_dir: "./data/playlists"
```

#### 6. Start ArangoDB

For native installations, you need ArangoDB running locally:

```bash
# Using Docker (recommended for development)
docker run -d --name arangodb \
  -e ARANGO_ROOT_PASSWORD=your-root-password \
  -p 8529:8529 \
  arangodb:3.12
```

#### 7. Run Nomarr

```bash
python -m nomarr.start
```

On first run, Nomarr will:
1. Connect to ArangoDB using `ARANGO_HOST` and `ARANGO_ROOT_PASSWORD`
2. Create the `nomarr` database and user
3. Generate a secure password and store it in `config/nomarr.yaml`

Access web UI at `http://localhost:8888`

---

## First-Time Setup

### 1. Access Web UI

Open your browser to:
- Docker: `http://localhost:8888`
- Native: `http://localhost:8888`

You should see the Nomarr dashboard.

### 2. Add Your Music Library

**All library management is done via the Web UI:**

1. Navigate to the "Libraries" page from the sidebar
2. Click "Add Library"
3. Enter a library name (e.g., "My Music")
4. Use the path picker to select a directory (must be within the configured `library_root`)
5. Enable/disable the library as needed
6. Click "Create"

**Note:** The library path must be accessible from within the Nomarr container. For Docker installations, ensure your music directory is mounted as a volume.

### 3. Scan Your Library

**Via Web UI:**
1. Go to the "Libraries" page
2. Find your library in the list
3. Click the "Scan" button on the library card
4. Monitor progress - the scan state will update in real-time

**Scan behavior:**
- Finds all audio files matching configured extensions
- Reads file metadata (artist, album, title, duration)
- Creates processing queue entries for new/changed files
- **Workers automatically start processing** (no manual intervention needed)

**Preview before scanning:** Click "Preview" to see how many files will be found without actually queuing them.

**Expected time:** 1-5 minutes for 10,000 tracks (scan only; processing is separate)

### 4. Processing Runs Automatically

**Workers start automatically** when Nomarr launches. There's no need to manually start or resume them.

**Processing behavior:**
- Workers continuously pick up jobs from the queue
- Each file: compute embeddings → run head models → extract tags
- Results stored in ArangoDB
- Failed files logged with errors

**Expected time:**
- With GPU: 1-2 minutes per 100 tracks
- Without GPU: 30-60 minutes per 100 tracks

**Pause/Resume workers:**
- Navigate to the Admin page in the Web UI
- Use the "Pause Workers" / "Resume Workers" buttons
- Workers will finish current jobs before pausing

### 5. Monitor Progress

**Dashboard page shows:**
- Total tracks processed
- Queue depth (pending, running, completed, errors)
- Worker status (active/paused)
- Processing rate (tracks/minute)

**Queue page shows:**
- Individual job status
- Error messages for failed jobs
- Estimated time remaining

**Admin page shows:**
- Worker health (heartbeat status)
- Current job per worker
- Pause/Resume controls

---

## Common Workflows

### Rescan After Adding Music

When you add new music files to your library:

1. Go to the **Libraries** page in the Web UI
2. Find your library and click **Scan**
3. The scan will detect new/changed files and queue them for processing
4. Workers will automatically process the new files

### Pause Processing

Useful before system maintenance or to free GPU:

1. Go to the **Admin** page in the Web UI
2. Click **Pause Workers**
3. Workers will finish their current jobs and then stop taking new ones
4. Click **Resume Workers** when ready to continue

### View Processing Errors

1. Go to the **Queue** page in the Web UI
2. Filter by status to see failed jobs
3. Click on a job to see error details
4. Jobs can be retried using the admin controls

### Reset Stuck or Failed Jobs

If jobs are stuck in "running" state (e.g., after a crash) or you want to retry errors:

```bash
# Docker - reset stuck jobs
docker exec -it nomarr nom admin-reset --stuck

# Docker - retry all failed jobs
docker exec -it nomarr nom admin-reset --errors

# Native
python -m nomarr.interfaces.cli admin-reset --stuck
python -m nomarr.interfaces.cli admin-reset --errors
```

### Clean Up Old Jobs

Remove completed jobs older than a certain age to keep the database clean:

```bash
# Docker - remove jobs older than 7 days (168 hours)
docker exec -it nomarr nom cleanup --hours 168

# Native
python -m nomarr.interfaces.cli cleanup --hours 168
```

### Export Tags to Navidrome

After processing, generate smart playlists via the Web UI:

1. Go to the **Navidrome** page
2. Preview your tag statistics
3. Use playlist templates or create custom queries
4. Generate and export playlist files

See [navidrome.md](navidrome.md) for detailed integration instructions.

---

## CLI Reference

Nomarr provides a small set of administrative CLI commands for maintenance tasks:

| Command | Description |
|---------|-------------|
| `nom cleanup --hours N` | Remove completed jobs older than N hours |
| `nom admin-reset --stuck` | Reset jobs stuck in "running" state |
| `nom admin-reset --errors` | Retry all failed jobs |
| `nom cache-refresh` | Rebuild model predictor cache |
| `nom remove --status <status>` | Remove jobs by status (pending, error, done) |
| `nom manage-password reset` | Change admin password |

**Note:** Library management, scanning, and worker control are handled through the Web UI, not the CLI.

---

## Troubleshooting

### GPU Not Detected

**Symptoms:**
- Processing extremely slow
- Logs show "Using CPU for inference"

**Solutions:**

1. **Verify GPU in container:**
   ```bash
   docker exec -it nomarr nvidia-smi
   ```
   Should show GPU info. If not, check NVIDIA Container Toolkit installation.

2. **Check docker-compose.yml has GPU config:**
   ```yaml
   deploy:
     resources:
       reservations:
         devices:
           - driver: nvidia
             count: 1
             capabilities: [gpu]
   ```

3. **Verify TensorFlow sees GPU:**
   ```bash
   docker exec -it nomarr python -c "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"
   ```
   Should list GPU. If empty, TensorFlow installation issue.

### Workers Not Starting

**Symptoms:**
- Queue depth shows "pending" but nothing processing
- Admin page shows no active workers

**Solutions:**

1. **Check logs:**
   ```bash
   docker-compose logs -f nomarr
   ```
   Look for worker startup errors.

2. **Verify workers are active:**
   Workers start automatically with Nomarr. Check the Admin page in the Web UI to see worker status.

3. **Restart Nomarr:**
   ```bash
   docker compose restart nomarr
   ```
   Workers will be restarted with the application.

4. **Check database connectivity:**
   ```bash
   docker exec -it nomarr python -c "from nomarr.persistence.db import Database; db = Database(); print('Connected to ArangoDB')"
   ```
   Should print "Connected to ArangoDB".

### Processing Jobs Fail Immediately

**Symptoms:**
- Jobs move to "error" status within seconds
- Error message: "File not found" or "Access denied"

**Solutions:**

1. **Verify file paths in queue match container paths:**
   - Queue stores paths as seen inside container (e.g., `/music/track.flac`)
   - Volume mount must match (e.g., `-v /home/user/Music:/music`)

2. **Check file permissions:**
   ```bash
   docker exec -it nomarr ls -l /music/problematic-file.flac
   ```
   File must be readable by container user.

3. **Verify file format support:**
   ```bash
   docker exec -it nomarr ffmpeg -i /music/track.flac -f null -
   ```
   Should decode without errors.

### Out of Memory Errors

**Symptoms:**
- Workers crash with OOM errors
- Log shows "ResourceExhaustedError"
- `nvidia-smi` shows 100% GPU memory usage

**Solutions:**

1. **Reduce batch size in config.yaml:**
   ```yaml
   processing:
     batch_size: 4  # Lower from 8
   ```

2. **Reduce number of workers:**
   ```yaml
   processing:
     workers: 1  # Lower from 2
   ```

3. **Enable GPU memory growth (advanced):**
   Add to config.yaml:
   ```yaml
   ml:
     gpu_memory_growth: true
   ```

### Database Connection Errors

**Symptoms:**
- Error: "connection refused" or "database unavailable"
- Operations timeout
- Workers fail to start

**Solutions:**

1. **Check ArangoDB is running:**
   ```bash
   docker compose ps nomarr-arangodb
   docker compose logs nomarr-arangodb
   ```

2. **Verify credentials in config:**
   Check `config/nomarr.yaml` has correct `arango_password` (auto-generated on first run).

3. **Restart services:**
   ```bash
   docker compose restart
   ```

### Calibration Never Completes

**Symptoms:**
- Calibration status stuck at partial completion
- Some tags never get threshold values

**Solutions:**

1. **Ensure enough tracks processed:**
   - Need 1000+ tracks for reliable calibration
   - More is better (5000+ recommended)

2. **Check calibration status:**
   Navigate to the **Calibration** page in the Web UI to see which tags have been calibrated.

3. **Trigger recalibration:**
   Use the **Calibration** page in the Web UI to recalculate thresholds for all tags.

---

## Next Steps

**After initial setup:**

1. **Read API Reference** → [api_reference.md](api_reference.md)
   - Integrate Nomarr with other tools
   - Build custom scripts

2. **Configure Navidrome Integration** → [navidrome.md](navidrome.md)
   - Export smart playlists
   - Use tags in music player

3. **Learn Calibration** → [../dev/calibration.md](../dev/calibration.md)
   - Understand tag normalization
   - Tune for your library

4. **Production Deployment** → [deployment.md](deployment.md)
   - Secure your instance
   - Optimize performance
   - Set up monitoring

---

## Getting Help

**Before asking for help:**

1. Check logs:
   ```bash
   docker-compose logs -f nomarr | grep -i error
   ```

2. Check system health in the Web UI:
   - **Dashboard** page shows overall status
   - **Admin** page shows worker health
   - **Queue** page shows job status

3. Verify GPU status:
   ```bash
   docker exec -it nomarr nvidia-smi
   ```

**Community support:**
- GitHub Issues: Report bugs and feature requests
- GitHub Discussions: Ask questions and share experiences

**When reporting issues:**
- Include Nomarr version (shown in Web UI footer)
- Include relevant logs (last 50 lines)
- Describe GPU hardware and driver version
- Describe steps to reproduce

---

## Performance Tips

### Optimal Configuration

**For NVIDIA RTX 3060 (12GB):**
```yaml
processing:
  workers: 2
  batch_size: 16
```

**For NVIDIA GTX 1660 (6GB):**
```yaml
processing:
  workers: 1
  batch_size: 8
```

**For high-end GPUs (RTX 4090, 24GB):**
```yaml
processing:
  workers: 4
  batch_size: 32
```

### Processing Speed

**Expected rates (tracks per minute):**
- RTX 4090: ~60-80
- RTX 3060: ~30-40
- GTX 1660: ~15-25
- CPU (16 cores): ~1-2
- CPU (8 cores): ~0.5-1

**Bottlenecks:**
- GPU compute: Increase batch size
- Disk I/O: Use SSD for music library
- Database: Reduce workers if seeing "locked" errors

### Storage Requirements

**Per track:**
- Database entry: ~5 KB (metadata + tags)
- Embedding cache: ~100 KB (if enabled)

**Example (10,000 tracks):**
- Database: ~50 MB
- Embeddings: ~1 GB
- Models: ~2 GB (one-time)

---

## Configuration Reference

See example `config/config.yaml` with all options and explanations.

**Key sections:**
- `arango_password`: Auto-generated database password
- `library`: Music paths and file extensions
- `processing`: Workers, batch size, queue limits
- `ml`: Model paths, backends, caching
- `server`: Web UI host and port
- `navidrome`: Export path and format

For full configuration documentation, see [../dev/services.md](../dev/services.md).
