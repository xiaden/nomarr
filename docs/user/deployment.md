# Production Deployment Guide

**Deploy Nomarr in Production with Docker**

---

## ⚠️ Pre-Production Checklist

- [ ] Nomarr is **alpha software** (breaking changes possible before 1.0)
- [ ] Database migrations auto-apply on startup (forward-only, no rollback)
- [ ] Plan for regular backups
- [ ] GPU strongly recommended for acceptable performance
- [ ] Budget 5–10 GB storage for application + database
- [ ] Ensure library storage is reasonably fast (SSD recommended)

---

## Server Requirements

### Minimum Production Server

- **CPU:** 4 cores (8+ recommended)
- **RAM:** 16 GB (32 GB recommended)
- **Storage:**
  - System: 50 GB SSD
  - Database: ~100 MB per 10,000 tracks
- **GPU:** NVIDIA GTX 1660 or better (RTX series recommended)
- **Network:** 100 Mbps+ for remote library access

### Recommended Production Server

- **CPU:** 8+ cores (AMD Ryzen 7 / Intel i7 or better)
- **RAM:** 32 GB
- **Storage:** 100 GB NVMe SSD for system + database
- **GPU:** NVIDIA RTX 3060 (12 GB) or better
- **Network:** 1 Gbps or 10 Gbps for NAS

### Operating System

**Supported:**

- Ubuntu 22.04 LTS (recommended)
- Debian 12
- CentOS Stream 9 / Rocky Linux 9

---

## Initial Setup

### 1. Install Docker and Docker Compose

```bash
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose plugin
sudo apt install docker-compose-plugin

# Log out and back in for group changes
```

Verify installation:

```bash
docker --version
docker compose version
```

### 2. Install NVIDIA Container Toolkit

Required for GPU support:

```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify GPU access:

```bash
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

### 3. Create Deployment Directory

```bash
sudo mkdir -p /opt/nomarr
sudo chown $USER:$USER /opt/nomarr
cd /opt/nomarr
```

---

## Production Configuration

### 1. Environment Files

Nomarr uses two environment files:

**`nomarr-arangodb.env`**:

```bash
# Root password for initial database provisioning
ARANGO_ROOT_PASSWORD=<generate-with-openssl-rand-hex-32>
ARANGO_NO_AUTH=0
```

**`nomarr.env`**:

```bash
# ArangoDB connection
ARANGO_HOST=http://nomarr-arangodb:8529

# Root password — must match nomarr-arangodb.env
# Only needed for first-run provisioning
ARANGO_ROOT_PASSWORD=<same-as-above>
```

Generate a strong password:

```bash
openssl rand -hex 32
```

!!! note
    On first run, Nomarr automatically provisions the ArangoDB database, generates a secure application password, and stores it in `config/nomarr.yaml` as `arango_password`.

### 2. Production `config/nomarr.yaml`

```bash
mkdir -p config
```

Create `config/nomarr.yaml`:

```yaml
# Production Nomarr Configuration
# Database password is auto-generated on first run and stored here.

library_root: "/media"
models_dir: "/app/models"
```

Most settings have sensible defaults. Libraries are configured via the Web UI.

**Optional settings you may want to tune** (via `config/nomarr.yaml` or environment variables):

 | Setting | Default | Description |
 | --------- | --------- | ------------- |
 | `tagger_worker_count` | auto (1) | Number of ML worker processes (1–8) |
 | `library_auto_tag` | `true` | Automatically process discovered files |
 | `calibrate_heads` | `false` | Enable calibration for tag thresholds |

All settings can also be changed via the Web UI’s Settings page at runtime.

### 3. Production `compose.yaml`

```yaml
services:
  nomarr-arangodb:
    image: arangodb:latest
    container_name: nomarr-arangodb
    networks:
      - internal_network
    restart: unless-stopped
    env_file:
      - nomarr-arangodb.env
    command: ["--vector-index"]
    volumes:
      - ./config/arangodb:/var/lib/arangodb3
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
    networks:
      - front_network
      - internal_network
    restart: unless-stopped
    depends_on:
      nomarr-arangodb:
        condition: service_healthy
    env_file:
      - nomarr.env
    # Uncomment for direct access (without reverse proxy):
    # ports:
    #   - "8356:8356"
    volumes:
      - ./config:/app/config
      - /path/to/your/music:/media:ro  # CHANGE THIS
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

networks:
  internal_network:
    internal: true   # Isolated network for DB (no external access)
  front_network:
    external: true   # Your reverse proxy network
```

**Production features:**

- ArangoDB on isolated internal network (no external access)
- Nomarr waits for healthy database before starting
- Pre-built image from GitHub Container Registry
- Models packaged in image (no separate volume needed)
- Non-root user (1000:1000)
- GPU reservation for CUDA acceleration
- Reverse proxy network for external access
- 30-second graceful shutdown period

---

## Reverse Proxy Setup (Nginx)

### 1. Install Nginx

```bash
sudo apt install nginx certbot python3-certbot-nginx
```

### 2. Configure Nginx

Create `/etc/nginx/sites-available/nomarr`:

```nginx
upstream nomarr {
    server nomarr:8356;
    keepalive 32;
}

# HTTP → HTTPS redirect
server {
    listen 80;
    listen [::]:80;
    server_name nomarr.yourdomain.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name nomarr.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/nomarr.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/nomarr.yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    client_max_body_size 100M;

    # Main proxy
    location / {
        proxy_pass http://nomarr;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
    }

    # Server-Sent Events (SSE) endpoint
    location /api/web/events {
        proxy_pass http://nomarr;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_set_header Cache-Control 'no-cache';
        proxy_set_header X-Accel-Buffering 'no';
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
        tcp_nodelay on;
        proxy_read_timeout 24h;
    }
}
```

!!! tip
    If you use a reverse proxy manager like Nginx Proxy Manager or Traefik, configure it to proxy to `nomarr:8356` on the `front_network` Docker network.

### 3. Enable Site and Get SSL Certificate

```bash
sudo ln -s /etc/nginx/sites-available/nomarr /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Get Let's Encrypt certificate
sudo certbot --nginx -d nomarr.yourdomain.com

# Test auto-renewal
sudo certbot renew --dry-run
```

---

## GPU Configuration

### Optimize GPU Settings

```bash
# Check GPU status
nvidia-smi

# Enable persistence mode (reduces startup latency)
sudo nvidia-smi -pm 1
sudo systemctl enable nvidia-persistenced
```

### Monitor GPU Usage

```bash
# Real-time monitoring
watch -n 1 nvidia-smi

# Or install nvtop for a better UI
sudo apt install nvtop
nvtop
```

### Multi-GPU Setup

```yaml
services:
  nomarr:
    environment:
      - CUDA_VISIBLE_DEVICES=0,1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 2
              capabilities: [gpu]
```

Increase `tagger_worker_count` in `config/nomarr.yaml` or via the Web UI to take advantage of multiple GPUs.

---

## Logging

**View Docker logs:**

```bash
docker compose logs -f nomarr
```

**Export logs to external system:**

```yaml
# In compose.yaml
services:
  nomarr:
    logging:
      driver: "syslog"
      options:
        syslog-address: "tcp://logserver:514"
        tag: "nomarr"
```

### Health Checks

```bash
# From inside Docker network
docker exec nomarr curl -s http://localhost:8356/api/web/health
```

**Simple automated monitoring** (`/opt/nomarr/monitor.sh`):

```bash
#!/bin/bash
HEALTH_URL="http://localhost:8356/api/web/health"
LOG_FILE="/var/log/nomarr-monitor.log"

response=$(docker exec nomarr curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL")

if [ "$response" != "200" ]; then
    echo "$(date): Health check failed (HTTP $response)" >> "$LOG_FILE"
    docker compose -f /opt/nomarr/compose.yaml restart nomarr
else
    echo "$(date): OK" >> "$LOG_FILE"
fi
```

```bash
crontab -e
# Add: check every 5 minutes
*/5 * * * * /opt/nomarr/monitor.sh
```

---

## Backup Strategy

### Database Backup

**Automated backup script** (`/opt/nomarr/backup.sh`):

```bash
#!/bin/bash
BACKUP_DIR="/opt/nomarr/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Get password from config
PASSWORD=$(grep arango_password /opt/nomarr/config/nomarr.yaml | cut -d: -f2 | tr -d ' "')

# Hot backup using arangodump (no downtime)
docker exec nomarr-arangodb arangodump \
  --server.username nomarr \
  --server.password "$PASSWORD" \
  --server.database nomarr \
  --output-directory /tmp/backup_$DATE

# Copy backup out of container
docker cp nomarr-arangodb:/tmp/backup_$DATE "$BACKUP_DIR/nomarr_$DATE"

# Cleanup temp backup inside container
docker exec nomarr-arangodb rm -rf /tmp/backup_$DATE

# Keep only last 7 days
find "$BACKUP_DIR" -name "nomarr_*" -type d -mtime +7 -exec rm -rf {} +

echo "$(date): Backup completed: nomarr_$DATE"
```

**Schedule daily backups:**

```bash
crontab -e
# Add (backup at 3 AM):
0 3 * * * /opt/nomarr/backup.sh >> /var/log/nomarr-backup.log 2>&1
```

### Configuration Backup

```bash
tar -czf /opt/nomarr/backups/config_$(date +%Y%m%d).tar.gz \
  /opt/nomarr/config \
  /opt/nomarr/compose.yaml
```

---

## Performance Optimization

### Database

ArangoDB handles optimization automatically. For large libraries, ensure the database volume is on fast storage (SSD/NVMe).

### Disk I/O

**Mount music library read-only:**

```yaml
volumes:
  - /mnt/music:/media:ro
```

### Worker Tuning

Start with the default worker count (1) and increase via the Web UI’s Settings page:

- **Increase if:** GPU memory usage < 80%, GPU utilization < 90%
- **Decrease if:** Out of memory errors or instability

**Typical configurations:**

 | GPU | Workers | Notes |
 | ----- | --------- | ------- |
 | 6 GB (GTX 1660) | 1 | Default is fine |
 | 12 GB (RTX 3060) | 1–2 | Monitor GPU memory |
 | 24 GB (RTX 4090) | 2–4 | Can handle more parallel work |

---

## Security Hardening

### Firewall Configuration

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### Container Security

The default compose.yaml already runs as non-root (`user: "1000:1000"`). For additional hardening:

```yaml
services:
  nomarr:
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
```

### Authentication

Nomarr includes built-in admin password authentication for the Web UI. Change the default password:

```bash
docker exec -it nomarr nom manage-password reset
```

---

## Updating Nomarr

### Update Procedure

```bash
cd /opt/nomarr

# Backup database first
./backup.sh

# Pull latest image
docker compose pull

# Restart with new image
docker compose down
docker compose up -d

# Check logs for migration messages
docker compose logs -f nomarr
```

!!! warning
    Database migrations are forward-only. Always back up before updating. Rollback requires restoring from backup.

### Rollback Procedure

```bash
# Stop current version
docker compose down

# Use previous image version
# Edit compose.yaml to pin: image: ghcr.io/xiaden/nomarr:<previous-tag>
docker compose up -d

# If database is incompatible, restore from backup:
PASSWORD=$(grep arango_password /opt/nomarr/config/nomarr.yaml | cut -d: -f2 | tr -d ' "')
docker cp /opt/nomarr/backups/nomarr_YYYYMMDD nomarr-arangodb:/tmp/restore
docker exec nomarr-arangodb arangorestore \
  --server.username nomarr \
  --server.password "$PASSWORD" \
  --server.database nomarr \
  --input-directory /tmp/restore \
  --overwrite true
```

---

## Troubleshooting Production Issues

### High CPU / Memory Usage

```bash
docker stats nomarr
nvidia-smi  # GPU memory
```

**Common causes:** Too many workers, scanning a very large library

**Solutions:** Reduce `tagger_worker_count` via Web UI Settings, restart

### Slow Processing

**Common causes:** GPU not being used (CPU fallback), disk I/O bottleneck on NAS

**Solutions:**

1. Verify GPU: `docker exec -it nomarr nvidia-smi`
2. Move database to fast SSD
3. Reduce worker count if seeing errors

### Connection Refused

```bash
docker compose ps
docker exec nomarr curl -s http://localhost:8356/api/web/health
sudo nginx -t
```

**Common causes:** Container not running, port binding conflict, Nginx misconfiguration

---

## Additional Resources

- [Getting Started](getting_started.md) — Initial setup guide
- [Navidrome Integration](navidrome.md) — Smart playlists for Navidrome
- [Troubleshooting](troubleshooting.md) — Common issues and solutions
- [Worker System](../dev/workers.md) — Worker architecture (developer reference)
- [Architecture](../dev/architecture.md) — System design (developer reference)
- Interactive API docs at `http://localhost:8356/docs`
