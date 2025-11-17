# ----------------------------------------------------------------------
#  Nomarr - Audio auto-tagging for Lidarr (GPU-enabled)
# ----------------------------------------------------------------------
# Use NVIDIA CUDA base image to get CUDA libraries for TensorFlow
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LC_ALL=C.UTF-8 LANG=C.UTF-8

# ----------------------------------------------------------------------
#  Base system packages
# ----------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv cron \
    libsndfile1 ffmpeg sox ca-certificates curl git tini sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------------
#  User and working directory
# ----------------------------------------------------------------------
RUN useradd -m -u 1000 appuser
WORKDIR /app

# ----------------------------------------------------------------------
#  Python dependencies (before copying project files for layer caching)
# ----------------------------------------------------------------------
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install \
    "essentia-tensorflow==2.1b6.dev1389" \
    "numpy==1.26.4" \
    "scipy==1.13.1" \
    "soundfile" \
    "mutagen==1.47.0" \
    "pyyaml==6.0.2" \
    "fastapi==0.115.0" \
    "uvicorn==0.30.6" \
    "rich==13.7.1" \
    "requests==2.32.3" \
    "pytest==8.3.3" \
    "pytest-cov==5.0.0"

# Sanity probe
RUN python3 - <<'PY'
import essentia
from essentia.standard import TensorflowPredict2D
print("Essentia:", essentia.__version__)
PY

# ----------------------------------------------------------------------
#  Copy in project files (after pip install for better layer caching)
# ----------------------------------------------------------------------
COPY nomarr/ /app/nomarr/
COPY models/ /app/models/
COPY config/ /app/config/
COPY scripts/ /app/scripts/
COPY docs/ /app/docs/
COPY tests/ /app/tests/
COPY readme.md /app/readme.md
COPY docker/cleanup-cron.sh /app/cleanup-cron.sh
COPY docker/nom-cli.sh /usr/local/bin/nom

# Copy built React frontend (must run `npm run build` in frontend/ first)
COPY frontend/dist/ /app/nomarr/interfaces/web/2.0

RUN chmod +x /app/cleanup-cron.sh /usr/local/bin/nom
RUN echo "0 3 * * * /app/cleanup-cron.sh" > /etc/cron.d/nomarr-cleanup
RUN chmod 0644 /etc/cron.d/nomarr-cleanup
RUN crontab /etc/cron.d/nomarr-cleanup

RUN mkdir -p /app/config/db && chown -R appuser:appuser /app

# ----------------------------------------------------------------------
#  Environment variables
# ----------------------------------------------------------------------
ENV NOMARR_MODELS=/app/models \
    NOMARR_DB=/app/config/db/essentia.sqlite \
    NOMARR_CONFIG=/app/config/config.yaml \
    PYTHONPATH=/app \
    NOMARR_API_KEY="" \
    PORT=8356 \
    TF_CPP_MIN_LOG_LEVEL=2 \
    TF_FORCE_GPU_ALLOW_GROWTH=true \
    TF_GPU_THREAD_MODE=gpu_private

# ----------------------------------------------------------------------
#  Healthcheck (internal)
# ----------------------------------------------------------------------
EXPOSE 8356

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/info || exit 1

# drop privileges for runtime
USER 1000:1000

# ----------------------------------------------------------------------
#  Entrypoint and graceful shutdown
# ----------------------------------------------------------------------
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "nomarr.start"]