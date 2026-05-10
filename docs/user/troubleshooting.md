# Troubleshooting

**Common Issues and How to Fix Them**

---

## Docker & Networking

### Containers Can’t Reach Each Other

**Symptoms:** Nomarr fails to start with "connection refused" to ArangoDB, or Navidrome push fails with timeout.

**Cause:** Docker containers on different networks can’t communicate.

**Solution:**

1. Ensure both containers are on the same Docker network. In compose.yaml, Nomarr and ArangoDB share `internal_network`:

    ```yaml
    networks:
      internal_network:
        internal: true
    ```

2. Use container names (not `localhost`) for inter-container communication:
    - ArangoDB: `http://nomarr-arangodb:8529`
    - Navidrome: `http://navidrome:4533` (if on a shared network)

3. Verify connectivity from inside the container:

    ```bash
    docker exec nomarr curl -s http://nomarr-arangodb:8529/_api/version
    ```

### ArangoDB Health Check Fails

**Symptoms:** Nomarr container stays in "waiting" state, logs show `depends_on: service_healthy` never satisfied.

**Cause:** ArangoDB hasn’t finished starting, or the root password is wrong.

**Solution:**

1. Check ArangoDB logs:

    ```bash
    docker compose logs nomarr-arangodb
    ```

2. Verify `ARANGO_ROOT_PASSWORD` matches in both `nomarr-arangodb.env` and `nomarr.env`.

3. If ArangoDB is stuck, remove its data and let it reinitialize:

    ```bash
    docker compose down
    rm -rf config/arangodb
    docker compose up -d
    ```

    !!! warning
        This deletes the database. Restore from backup if you have data to keep.

4. Ensure the health check matches your setup. The default compose.yaml includes a health check that uses `ARANGO_ROOT_PASSWORD` — it must be set correctly.

---

## GPU Not Detected

### GPU Not Available in Container

**Symptoms:** Processing is extremely slow. Logs may show CPU-only inference.

**Cause:** NVIDIA Container Toolkit not installed, or compose.yaml missing GPU configuration.

**Solution:**

1. **Verify GPU on the host:**

    ```bash
    nvidia-smi
    ```

    If this fails, install NVIDIA drivers first.

2. **Verify NVIDIA Container Toolkit:**

    ```bash
    docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
    ```

    If this fails, install the NVIDIA Container Toolkit (see [Getting Started](getting_started.md)).

3. **Verify compose.yaml has GPU config:**

    ```yaml
    services:
      nomarr:
        deploy:
          resources:
            reservations:
              devices:
                - driver: nvidia
                  count: 1
                  capabilities: [gpu]
    ```

4. **Verify GPU inside the Nomarr container:**

    ```bash
    docker exec -it nomarr nvidia-smi
    ```

5. **Check ONNX Runtime GPU support:**

    ```bash
    docker exec -it nomarr python -c "import onnxruntime; print(onnxruntime.get_available_providers())"
    ```

    Should include `CUDAExecutionProvider`. If only `CPUExecutionProvider` appears, the GPU is not available to the ML runtime.

### Docker Desktop (Windows/macOS) GPU Issues

**Symptoms:** GPU works on the host but not in Docker Desktop containers.

**Cause:** Docker Desktop on Windows requires WSL2 with GPU passthrough. macOS does not support NVIDIA GPU passthrough.

**Solution:**

- **Windows:** Enable WSL2 with GPU support in Docker Desktop settings. Requires Windows 11 or Windows 10 21H2+ with a compatible NVIDIA driver.
- **macOS:** NVIDIA GPU acceleration is not available in Docker on macOS.

---

## First-Run Database Provisioning

### Provisioning Fails on First Start

**Symptoms:** Nomarr crashes on first start with database errors. Logs show "authentication failed" or "database not found".

**Cause:** `ARANGO_ROOT_PASSWORD` mismatch between the two containers, or ArangoDB didn’t start cleanly.

**Solution:**

1. Ensure `ARANGO_ROOT_PASSWORD` is identical in `nomarr-arangodb.env` and `nomarr.env`.

2. Check that ArangoDB started successfully:

    ```bash
    docker compose logs nomarr-arangodb | tail -20
    ```

3. If the password was changed after ArangoDB was first created, you need to reset:

    ```bash
    docker compose down
    rm -rf config/arangodb  # Wipes database
    # Update both .env files with matching passwords
    docker compose up -d
    ```

### "arango_password" Missing from nomarr.yaml

**Symptoms:** Nomarr starts but can’t connect to the database after restart.

**Cause:** First-run provisioning didn’t complete, so the generated password wasn’t saved.

**Solution:**

1. Check `config/nomarr.yaml` for an `arango_password` entry.
2. If missing, delete the ArangoDB data and re-provision:

    ```bash
    docker compose down
    rm -rf config/arangodb
    docker compose up -d
    ```

3. Watch logs to confirm provisioning succeeds:

    ```bash
    docker compose logs -f nomarr
    ```

---

## Model Loading Issues

### Models Not Found

**Symptoms:** Logs show "model not found" or "FileNotFoundError" for model files.

**Cause:** Models are pre-packaged in the Docker image. This usually means a custom `models_dir` is misconfigured or a custom image is missing models.

**Solution:**

1. If using the official image (`ghcr.io/xiaden/nomarr:latest`), models are included. Don’t override `models_dir` unless you know what you’re doing.

2. If you’ve mounted a custom models volume, ensure all required model files are present:

    ```bash
    docker exec -it nomarr ls /app/models/
    ```

3. Remove any custom `models_dir` config and restart to use the packaged models.

---

## Scan Not Finding Files

### No Files Detected During Scan

**Symptoms:** Library scan completes instantly with 0 files found.

**Cause:** Volume mount mismatch — the music directory isn’t accessible inside the container at the expected path.

**Solution:**

1. **Verify the volume mount** in compose.yaml:

    ```yaml
    volumes:
      - /your/actual/music/path:/media:ro
    ```

    The right side (`/media`) must match the `library_root` setting.

2. **Check files are visible inside the container:**

    ```bash
    docker exec -it nomarr ls /media/
    ```

    You should see your music directories.

3. **Check the library path** in the Web UI — it must be a subdirectory of `library_root` (typically `/media`).

### Permission Denied on Music Files

**Symptoms:** Scan finds files but processing fails with "Permission denied".

**Cause:** The container runs as user `1000:1000` and can’t read the music files.

**Solution:**

1. Check file ownership:

    ```bash
    docker exec -it nomarr ls -la /media/
    ```

2. Ensure files are readable by UID 1000, or adjust the `user:` setting in compose.yaml to match your file ownership:

    ```yaml
    services:
      nomarr:
        user: "1000:1000"  # Change to match your music file ownership
    ```

3. Or make the files world-readable on the host:

    ```bash
    chmod -R a+r /path/to/your/music
    ```

### File Watcher Not Detecting Changes

**Symptoms:** New files added to the library aren’t picked up automatically.

**Cause:** Event-based watching doesn’t work reliably on network mounts (NFS, SMB/CIFS).

**Solution:**

Switch to polling mode by adding to `nomarr.env`:

```bash
NOMARR_WATCH_MODE=poll
```

Then restart: `docker compose restart nomarr`

Polling mode checks for changes every 60 seconds, which is slower than event mode but works on any filesystem.

---

## Navidrome Connection Failures

### Ping Fails

**Symptoms:** Clicking Ping in the Navidrome API Settings panel returns an error.

**Cause:** Wrong URL, network issue, or incorrect credentials.

**Solution:**

1. **Check the URL** — Must include the scheme and port: `http://navidrome:4533` (not just `navidrome`)
2. **Docker networking** — Navidrome must be on a network shared with Nomarr. If using the default compose.yaml, add Navidrome to `front_network`.
3. **Test from inside the container:**

    ```bash
    docker exec nomarr curl -s http://navidrome:4533/rest/ping?v=1.16.1&c=nomarr
    ```

4. **Verify credentials** — The username and password must be for a valid Navidrome user

### Push Fails

**Symptoms:** Push to Navidrome returns errors about unresolved songs.

**Cause:** Nomarr can’t map its file IDs to Navidrome song IDs.

**Solution:**

1. Run **Sync Songs** from the Navidrome page to refresh the mapping
2. Ensure both Nomarr and Navidrome point to the **same music files** (paths may differ between containers, but the actual files must be the same)

!!! note
    This Sync Songs requirement applies to backend push flows.
    Navidrome plugin Instant Mix / similar-track recommendations use descriptor resolution in-plugin and do not require Nomarr song-map sync.

---

## Calibration

### Calibration Won’t Run

**Symptoms:** Calibration page shows no data or "not enough tracks".

**Cause:** Calibration needs a minimum number of processed tracks (at least 100) to calculate meaningful thresholds.

**Solution:**

1. Process more tracks — at least 100, ideally 1,000+
2. Check the Dashboard to see how many tracks have been processed
3. Once enough tracks are processed, visit the Calibration page and trigger calibration

### When to Recalibrate

**Symptoms:** Tags seem less accurate after adding a large batch of new music.

**Cause:** Calibration thresholds are based on the distribution of your library. Adding a significant amount of new music changes that distribution.

**Solution:**

- Recalibrate after adding >20% new music to your library
- Check the Calibration page periodically to see if metrics have drifted
- See [Calibration Troubleshooting](../dev/calibration-troubleshooting.md) for advanced details

---

## General Tips

### Check Logs First

Most issues can be diagnosed from the logs:

```bash
# Follow Nomarr logs
docker compose logs -f nomarr

# Filter for errors
docker compose logs nomarr 2>&1 | grep -i error

# Check ArangoDB logs
docker compose logs nomarr-arangodb
```

### Restart Services

Many transient issues resolve with a restart:

```bash
# Restart just Nomarr
docker compose restart nomarr

# Restart everything
docker compose restart

# Full stop and start (recreates containers)
docker compose down && docker compose up -d
```

### Check Versions

Nomarr version is shown in the Web UI footer. Include it when reporting issues.

```bash
# Check Docker versions
docker --version
docker compose version

# Check GPU driver
nvidia-smi
```

---

## Getting Help

If the solutions above don’t resolve your issue:

1. Search [GitHub Issues](https://github.com/xiaden/nomarr/issues) for similar problems
2. Open a new issue with:
   - Nomarr version
   - Relevant logs (last 50 lines)
   - GPU hardware and driver version (if GPU-related)
   - Steps to reproduce
3. Join [GitHub Discussions](https://github.com/xiaden/nomarr/discussions) for questions and community help
