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

#### 6. Initialize Database

```bash
python -m nomarr.start --init-db
```

#### 7. Run Nomarr

```bash
python -m nomarr.start
```

Access web UI at `http://localhost:8888`

---

## First-Time Setup

### 1. Access Web UI

Open your browser to:
- Docker: `http://localhost:8888`
- Native: `http://localhost:8888`

You should see the Nomarr dashboard.

### 2. Add Your Music Library

**Via Web UI:**
1. Navigate to "Libraries" page
2. Click "Add Library"
3. Enter library name (e.g., "My Music")
4. Enter path (must match config.yaml)
5. Click "Create"

**Via CLI:**
```bash
# Docker
docker exec -it nomarr nom-cli library add "My Music" /music

# Native
python -m nomarr.interfaces.cli library add "My Music" /home/user/Music
```

### 3. Scan Your Library

**Via Web UI:**
1. Go to "Libraries" page
2. Click "Scan" button next to your library
3. Monitor progress on Dashboard

**Via CLI:**
```bash
# Docker
docker exec -it nomarr nom-cli library scan "My Music"

# Native
python -m nomarr.interfaces.cli library scan "My Music"
```

**Scan behavior:**
- Finds all audio files matching configured extensions
- Reads metadata (artist, album, title, duration)
- Creates processing queue entries
- Does **not** start analysis (see next step)

**Expected time:** 1-5 minutes for 10,000 tracks

### 4. Start Processing Queue

Processing analyzes audio files using ML models.

**Via Web UI:**
1. Go to "Admin" page
2. Click "Resume Workers" (if paused)
3. Monitor progress on Dashboard

**Via CLI:**
```bash
# Docker
docker exec -it nomarr nom-cli queue resume

# Native
python -m nomarr.interfaces.cli queue resume
```

**Processing behavior:**
- Workers pick up jobs from queue
- Each file: compute embeddings → run head models → extract tags
- Results stored in database
- Failed files logged with errors

**Expected time:**
- With GPU: 1-2 minutes per 100 tracks
- Without GPU: 30-60 minutes per 100 tracks

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

**Worker page shows:**
- Worker health (heartbeat status)
- Current job per worker
- Worker process IDs
- Restart counts

---

## Common Workflows

### Rescan After Adding Music

When you add new music files to your library:

```bash
# Scan library (finds new files)
docker exec -it nomarr nom-cli library scan "My Music"

# Processing starts automatically if workers are running
# Check queue to see new jobs
```

### Process Specific Files

```bash
# Add specific file to queue
docker exec -it nomarr nom-cli queue enqueue /music/album/track.flac

# Or enqueue entire directory
docker exec -it nomarr nom-cli queue enqueue-dir /music/new-album/
```

### Pause Processing

Useful before system maintenance or to free GPU:

```bash
# Pause workers (finish current jobs, don't start new ones)
docker exec -it nomarr nom-cli queue pause

# Resume later
docker exec -it nomarr nom-cli queue resume
```

### View Processing Errors

```bash
# List failed jobs
docker exec -it nomarr nom-cli queue list --status error

# Show error details for specific job
docker exec -it nomarr nom-cli queue show <job-id>
```

### Retry Failed Jobs

```bash
# Retry all failed jobs
docker exec -it nomarr nom-cli queue retry-errors

# Or manually requeue
docker exec -it nomarr nom-cli queue requeue <job-id>
```

### Export Tags to Navidrome

After processing, export smart playlists:

```bash
# Generate TOML playlists for Navidrome
docker exec -it nomarr nom-cli navidrome export

# Output in /data/playlists/ (or configured export_dir)
# Copy these to Navidrome's playlist directory
```

See [navidrome.md](navidrome.md) for integration details.

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
- Worker page shows no workers or "crashed" status

**Solutions:**

1. **Check logs:**
   ```bash
   docker-compose logs -f nomarr
   ```
   Look for worker startup errors.

2. **Check worker status:**
   ```bash
   docker exec -it nomarr nom-cli worker status
   ```

3. **Restart workers:**
   ```bash
   docker exec -it nomarr nom-cli worker restart
   ```

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

2. **Check calibration queue:**
   ```bash
   docker exec -it nomarr nom-cli queue list --queue calibration
   ```

3. **Manually trigger calibration:**
   ```bash
   docker exec -it nomarr nom-cli calibration generate
   docker exec -it nomarr nom-cli calibration apply
   ```

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

2. Check system health:
   ```bash
   docker exec -it nomarr nom-cli worker status
   docker exec -it nomarr nom-cli queue status
   ```

3. Verify GPU status:
   ```bash
   docker exec -it nomarr nvidia-smi
   ```

**Community support:**
- GitHub Issues: Report bugs and feature requests
- GitHub Discussions: Ask questions and share experiences

**When reporting issues:**
- Include Nomarr version (`docker exec -it nomarr nom-cli version`)
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
