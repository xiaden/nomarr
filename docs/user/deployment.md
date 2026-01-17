# Production Deployment Guide

**Deploy Nomarr in Production with Docker**

---

## Overview

This guide covers production deployment of Nomarr with:

- Docker and Docker Compose
- GPU acceleration
- Reverse proxy (Nginx)
- SSL/TLS with Let's Encrypt
- Monitoring and logging
- Backup strategies
- Performance optimization

---

## ⚠️ Pre-Production Checklist

**Before deploying to production:**

- [ ] Nomarr is pre-alpha software (no stability guarantees)
- [ ] Database schema may change between versions
- [ ] Plan for regular backups
- [ ] GPU required for acceptable performance
- [ ] Budget 10-20 GB storage for models and cache
- [ ] Ensure library storage is fast (SSD recommended)

**Production-ready status:** Not yet recommended for mission-critical deployments.

---

## Server Requirements

### Minimum Production Server

- **CPU:** 4 cores (8+ recommended for concurrent users)
- **RAM:** 16 GB (32 GB recommended)
- **Storage:**
  - System: 50 GB SSD
  - Models: 10 GB
  - Database: 100 MB per 10,000 tracks
  - Embedding cache: 1 GB per 10,000 tracks (optional)
- **GPU:** NVIDIA GTX 1660 or better (RTX series recommended)
- **Network:** 100 Mbps+ for remote library access

### Recommended Production Server

- **CPU:** 8+ cores (AMD Ryzen 7 / Intel i7 or better)
- **RAM:** 32 GB
- **Storage:**
  - System: 100 GB NVMe SSD
  - Music library: Fast SSD or NAS with 10GbE
  - Models + cache: 50 GB SSD
- **GPU:** NVIDIA RTX 3060 (12GB) or better
- **Network:** 1 Gbps or 10 Gbps for NAS

### Operating System

**Supported:**
- Ubuntu 22.04 LTS (recommended)
- Debian 12
- CentOS Stream 9
- Rocky Linux 9

**Not recommended:**
- Windows Server (WSL2 adds overhead)
- macOS (GPU support experimental)

---

## Initial Setup

### 1. Install Docker and Docker Compose

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
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
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### 3. Create Deployment Directory

```bash
sudo mkdir -p /opt/nomarr
sudo chown $USER:$USER /opt/nomarr
cd /opt/nomarr
```

### 4. Clone Repository

```bash
git clone https://github.com/yourusername/nomarr.git .
```

---

## Production Configuration

### 1. Environment Files

Nomarr uses two environment files:

**`nomarr-arangodb.env`** (for ArangoDB container):
```bash
# Root password for initial database provisioning
ARANGO_ROOT_PASSWORD=<generate-with-openssl-rand-hex-32>
```

**`nomarr.env`** (for Nomarr container):
```bash
# ArangoDB connection
ARANGO_HOST=http://nomarr-arangodb:8529
ARANGO_ROOT_PASSWORD=<same-as-above>

# Paths (optional - uses defaults if not set)
MUSIC_LIBRARY=/mnt/music

# GPU
NVIDIA_VISIBLE_DEVICES=all
CUDA_VISIBLE_DEVICES=0

# Logging
LOG_LEVEL=INFO
```

Generate secrets:
```bash
openssl rand -hex 32  # For ARANGO_ROOT_PASSWORD
```

**Note:** On first run, Nomarr automatically:
1. Provisions the ArangoDB database and user
2. Generates a secure application password
3. Stores the password in `config/nomarr.yaml` as `arango_password`

### 2. Production config.yaml

Create `config/config.yaml`:

```yaml
# Production Nomarr Configuration
# Note: Database password is auto-generated on first run and stored here.
# The 'arango_password' key will be added automatically.

library:
  paths:
    - "/music"
  extensions:
    - ".flac"
    - ".mp3"
    - ".ogg"
    - ".m4a"
    - ".wav"
    - ".opus"
    - ".aac"
  scan_interval: 3600  # Auto-rescan every hour

processing:
  workers: 2  # Adjust based on GPU memory
  queue_sizes:
    processing: 1000
    calibration: 200
  batch_size: 16  # Adjust based on GPU memory
  retry_limit: 3
  timeout: 300  # 5 minutes per job

ml:
  models_dir: "/models"
  backends:
    - "essentia"
  cache_embeddings: true
  cache_dir: "/data/embeddings"
  gpu_memory_growth: false  # Set to true if OOM issues

server:
  host: "0.0.0.0"
  port: 8356  # Internal port (mapped to 8888 externally)
  session_lifetime: 86400  # 24 hours
  cors_origins:
    - "https://yourdomain.com"
  trust_proxy: true  # Behind reverse proxy

navidrome:
  export_dir: "/data/playlists"
  auto_export: true
  export_interval: 3600  # Export every hour

logging:
  level: "INFO"  # DEBUG for troubleshooting
  file: "/data/nomarr.log"
  max_size: 100  # MB
  max_backups: 5
  format: "json"  # Structured logging for production

monitoring:
  enable_metrics: true
  metrics_port: 9090
  health_check_interval: 30
```

**Key production settings:**
- `library.scan_interval`: Automatic rescans
- `processing.timeout`: Prevent stuck jobs
- `server.trust_proxy`: Required behind reverse proxy
- `server.cors_origins`: Restrict to your domain
- `logging.format: json`: Machine-readable logs

### 3. Production docker-compose.yml

```yaml
services:
  nomarr-arangodb:
    image: arangodb:3.12
    container_name: nomarr-arangodb
    hostname: nomarr-arangodb
    restart: unless-stopped
    env_file:
      - nomarr-arangodb.env
    volumes:
      - nomarr-arangodb-data:/var/lib/arangodb3
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8529/_api/version"]
      interval: 30s
      timeout: 10s
      retries: 3

  nomarr:
    build:
      context: .
      dockerfile: dockerfile
    container_name: nomarr
    hostname: nomarr
    restart: unless-stopped
    depends_on:
      nomarr-arangodb:
        condition: service_healthy
    env_file:
      - nomarr.env
    
    ports:
      - "127.0.0.1:8888:8356"  # Only localhost (behind proxy)
      - "127.0.0.1:9090:9090"  # Metrics endpoint
    
    volumes:
      - ./config:/config
      - ./models:/models:ro
      - ${MUSIC_LIBRARY}:/music:ro
      - nomarr-cache:/data/embeddings
    
    environment:
      - LOG_LEVEL=${LOG_LEVEL}
      - NVIDIA_VISIBLE_DEVICES=all
      - TZ=America/New_York  # Set your timezone
    
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          memory: 4G
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8356/api/web/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    
    security_opt:
      - no-new-privileges:true
    
    user: "1000:1000"  # Run as non-root (adjust UID/GID)

volumes:
  nomarr-arangodb-data:
    driver: local
  nomarr-cache:
    driver: local

networks:
  default:
    name: nomarr-network
```

**Production features:**
- ArangoDB service with health check
- Nomarr waits for healthy database before starting
- Bind to localhost only (reverse proxy handles external access)
- Memory limits prevent OOM killing other services
- Health checks for automatic restart
- Log rotation
- Security hardening (no-new-privileges, non-root user)
- Persistent volumes for data and cache

---

## Reverse Proxy Setup (Nginx)

### 1. Install Nginx

```bash
sudo apt install nginx certbot python3-certbot-nginx
```

### 2. Configure Nginx

Create `/etc/nginx/sites-available/nomarr`:

```nginx
# Nomarr reverse proxy configuration
upstream nomarr {
    server 127.0.0.1:8888;
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
    
    # SSL certificates (managed by certbot)
    ssl_certificate /etc/letsencrypt/live/nomarr.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/nomarr.yourdomain.com/privkey.pem;
    
    # SSL configuration (Mozilla Intermediate)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_stapling on;
    ssl_stapling_verify on;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Logging
    access_log /var/log/nginx/nomarr.access.log;
    error_log /var/log/nginx/nomarr.error.log;
    
    # Client limits
    client_max_body_size 100M;
    
    # Proxy settings
    location / {
        proxy_pass http://nomarr;
        proxy_http_version 1.1;
        
        # Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Buffering
        proxy_buffering off;
    }
    
    # Server-Sent Events (SSE) endpoint
    location /api/web/events {
        proxy_pass http://nomarr;
        proxy_http_version 1.1;
        
        # SSE requires these settings
        proxy_set_header Connection '';
        proxy_set_header Cache-Control 'no-cache';
        proxy_set_header X-Accel-Buffering 'no';
        
        proxy_buffering off;
        proxy_cache off;
        
        chunked_transfer_encoding on;
        tcp_nodelay on;
        
        # Long timeout for persistent connections
        proxy_read_timeout 24h;
    }
    
    # Metrics endpoint (restrict access)
    location /metrics {
        proxy_pass http://127.0.0.1:9090/metrics;
        allow 10.0.0.0/8;  # Internal network only
        deny all;
    }
}
```

**Key features:**
- HTTP to HTTPS redirect
- SSL/TLS with strong ciphers
- Security headers
- Special handling for SSE endpoint (no buffering, long timeout)
- Restricted metrics endpoint

### 3. Enable Site and Get SSL Certificate

```bash
# Enable site
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

**Check current GPU status:**
```bash
nvidia-smi
```

**Configure persistence mode (survives reboots):**
```bash
# Enable persistence mode (reduces latency)
sudo nvidia-smi -pm 1

# Set power limit (optional, for power savings)
sudo nvidia-smi -pl 200  # 200W limit (adjust for your card)

# Make permanent (Ubuntu)
sudo systemctl enable nvidia-persistenced
```

**Monitor GPU usage:**
```bash
# Real-time monitoring
watch -n 1 nvidia-smi

# Or use nvtop for better UI
sudo apt install nvtop
nvtop
```

### Multi-GPU Setup

If you have multiple GPUs:

**docker-compose.yml:**
```yaml
services:
  nomarr:
    environment:
      - CUDA_VISIBLE_DEVICES=0,1  # Use GPU 0 and 1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 2  # Reserve 2 GPUs
              capabilities: [gpu]
```

**config.yaml:**
```yaml
processing:
  workers: 4  # 2 workers per GPU
  gpu_per_worker: 0.5  # Each worker uses half a GPU
```

---

## Monitoring and Logging

### System Monitoring

**Install monitoring tools:**
```bash
sudo apt install prometheus node-exporter grafana
```

**Configure Prometheus** (`/etc/prometheus/prometheus.yml`):
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'nomarr'
    static_configs:
      - targets: ['localhost:9090']
  
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
  
  - job_name: 'nvidia'
    static_configs:
      - targets: ['localhost:9445']  # nvidia-smi exporter
```

**Install NVIDIA GPU exporter:**
```bash
docker run -d --restart=unless-stopped \
  --gpus all \
  -p 9445:9445 \
  nvidia/dcgm-exporter:latest
```

### Log Aggregation

**View Docker logs:**
```bash
docker-compose logs -f nomarr
```

**View Nomarr application logs:**
```bash
docker exec -it nomarr tail -f /data/nomarr.log
```

**Export logs to external system:**

```yaml
# docker-compose.yml
services:
  nomarr:
    logging:
      driver: "syslog"
      options:
        syslog-address: "tcp://logserver:514"
        tag: "nomarr"
```

### Health Checks

**Manual health check:**
```bash
curl http://localhost:8888/api/web/health
```

**Automated monitoring script** (`/opt/nomarr/monitor.sh`):
```bash
#!/bin/bash
# Simple health check script

HEALTH_URL="http://localhost:8888/api/web/health"
LOG_FILE="/var/log/nomarr-monitor.log"

response=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL")

if [ "$response" != "200" ]; then
    echo "$(date): Health check failed (HTTP $response)" >> "$LOG_FILE"
    docker-compose -f /opt/nomarr/docker-compose.yml restart nomarr
else
    echo "$(date): Health check OK" >> "$LOG_FILE"
fi
```

**Add to crontab:**
```bash
crontab -e
# Add line:
*/5 * * * * /opt/nomarr/monitor.sh
```

---

## Backup Strategy

### Database Backup

**Automated backup script** (`/opt/nomarr/backup.sh`):
```bash
#!/bin/bash
# Nomarr ArangoDB backup using arangodump

BACKUP_DIR="/opt/nomarr/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Get password from config
PASSWORD=$(grep arango_password /opt/nomarr/config/nomarr.yaml | cut -d: -f2 | tr -d ' "')

# Backup database using arangodump (hot backup, no downtime)
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
# Add line (backup at 3 AM):
0 3 * * * /opt/nomarr/backup.sh >> /var/log/nomarr-backup.log 2>&1
```

### Hot Backup (Alternative Method)

Use ArangoDB's built-in backup directly:

```bash
# Backup via arangodump
docker compose exec nomarr-arangodb arangodump \
  --server.database nomarr \
  --output-directory /var/lib/arangodb3/backup_$(date +%Y%m%d)

# Copy backup out of container
docker cp nomarr-arangodb:/var/lib/arangodb3/backup_$(date +%Y%m%d) /opt/nomarr/backups/
```

### Configuration Backup

```bash
# Backup config and models list
tar -czf /opt/nomarr/backups/config_$(date +%Y%m%d).tar.gz \
  /opt/nomarr/config \
  /opt/nomarr/docker-compose.yml \
  /opt/nomarr/.env
```

---

## Performance Optimization

### Database Optimization

ArangoDB handles optimization automatically. For large deployments:

**Check collection statistics:**
```bash
docker compose exec nomarr-arangodb arangosh --server.database nomarr \
  --javascript.execute-string 'db._collections().forEach(c => print(c.name(), c.count()))'
```

**Compact collections (rarely needed):**
```bash
docker compose exec nomarr-arangodb arangosh --server.database nomarr \
  --javascript.execute-string 'db.queue.compact()'
```

### Disk I/O Optimization

**Use SSD for database and cache:**
```yaml
volumes:
  nomarr-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /mnt/nvme/nomarr-data  # Fast SSD mount
```

**Mount music library read-only:**
```yaml
volumes:
  - ${MUSIC_LIBRARY}:/music:ro  # Read-only reduces writes
```

### Worker Tuning

**Find optimal worker count:**

Start with `workers: 1` and gradually increase:

```bash
# Edit config.yaml
vim /opt/nomarr/config/config.yaml

# Change workers: 2
# Restart
docker-compose restart nomarr

# Monitor GPU memory
watch -n 1 nvidia-smi

# Check processing rate in Web UI Dashboard
```

**Increase if:**
- GPU memory < 80% used
- GPU utilization < 90%

**Decrease if:**
- Out of memory errors
- Database locked errors

**Typical configurations:**
- 6GB GPU: 1 worker, batch 8
- 12GB GPU: 2 workers, batch 16
- 24GB GPU: 3-4 workers, batch 32

---

## Security Hardening

### Firewall Configuration

```bash
# Allow SSH, HTTP, HTTPS only
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### Container Security

**Run as non-root** (in docker-compose.yml):
```yaml
services:
  nomarr:
    user: "1000:1000"  # Non-root user
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE  # Only if binding to port 80/443
```

### Authentication

**Enable API key authentication:**

```yaml
# config.yaml
server:
  require_auth: true
  api_key: "${API_KEY}"  # From .env
```

**Restrict CORS:**
```yaml
server:
  cors_origins:
    - "https://yourdomain.com"  # Only your domain
```

### SSL/TLS Best Practices

**Strong cipher suites** (already in Nginx config above)

**Test SSL configuration:**
```bash
# Using SSL Labs
# Visit: https://www.ssllabs.com/ssltest/analyze.html?d=nomarr.yourdomain.com

# Or using testssl.sh
git clone https://github.com/drwetter/testssl.sh.git
cd testssl.sh
./testssl.sh https://nomarr.yourdomain.com
```

---

## Updating Nomarr

### Update Procedure

```bash
cd /opt/nomarr

# Backup database first
./backup.sh

# Pull latest code
git fetch origin
git checkout main
git pull origin main

# Rebuild container
docker-compose build --no-cache

# Restart
docker-compose down
docker-compose up -d

# Check logs
docker-compose logs -f nomarr
```

### Rollback Procedure

```bash
# Stop current version
docker-compose down

# Restore previous version
git checkout <previous-commit-hash>

# Rebuild and restart
docker-compose build --no-cache
docker-compose up -d

# If database incompatible, restore from backup using arangorestore
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

### High CPU Usage

**Diagnose:**
```bash
docker stats nomarr
htop
```

**Common causes:**
- Too many workers for CPU cores
- Database locked (workers retrying)
- Scanning large library

**Solutions:**
- Reduce worker count
- Increase database timeout
- Limit scan intervals

### High Memory Usage

**Diagnose:**
```bash
docker stats nomarr
nvidia-smi  # GPU memory
```

**Common causes:**
- Batch size too high
- Embedding cache growing
- Memory leak (rare)

**Solutions:**
- Reduce batch size
- Disable embedding cache
- Restart container regularly (cron job)

### Slow Processing

**Diagnose:**
Check queue status in Web UI Dashboard, then run:
```bash
nvidia-smi dmon  # GPU monitoring
```

**Common causes:**
- GPU not being used (CPU fallback)
- Disk I/O bottleneck (slow NAS)
- Database locked errors

**Solutions:**
- Verify GPU with `nvidia-smi` inside container
- Move database to fast SSD
- Reduce worker count if locked errors

### Connection Refused

**Diagnose:**
```bash
docker-compose ps
curl http://localhost:8888/api/web/health
sudo nginx -t
```

**Common causes:**
- Container not running
- Port binding conflict
- Nginx misconfiguration

**Solutions:**
- Check container status: `docker-compose ps`
- Check logs: `docker-compose logs nomarr`
- Verify Nginx config: `sudo nginx -t`

---

## Additional Resources

- [Getting Started](getting_started.md) - Initial setup guide
- [API Reference](api_reference.md) - HTTP API documentation
- [Worker System](../dev/workers.md) - Worker architecture
- [Architecture](../dev/architecture.md) - System design

---

## Production Checklist

**Before going live:**

- [ ] GPU verified with `nvidia-smi` in container
- [ ] SSL certificate obtained and auto-renewal configured
- [ ] Strong session secret and API key set
- [ ] CORS origins restricted to your domain
- [ ] Firewall configured (only SSH, HTTP, HTTPS)
- [ ] Reverse proxy configured with security headers
- [ ] Automated backups scheduled (daily)
- [ ] Log rotation configured
- [ ] Health monitoring configured
- [ ] Worker count tuned for your GPU
- [ ] Database optimization scheduled (monthly)
- [ ] Container running as non-root user
- [ ] Memory limits set in docker-compose.yml
- [ ] Update procedure tested
- [ ] Rollback procedure tested

**Post-deployment:**

- [ ] Monitor logs for errors (first 24 hours)
- [ ] Verify GPU usage with `nvidia-smi`
- [ ] Check processing rate meets expectations
- [ ] Test health check endpoint
- [ ] Verify backup script works
- [ ] Test SSL configuration (SSL Labs)
- [ ] Monitor disk space usage
- [ ] Document any custom configuration
