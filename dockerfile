# ----------------------------------------------------------------------
#  Nomarr - Audio auto-tagging for Lidarr (GPU-enabled)
#  Fast build using pre-built base image
# ----------------------------------------------------------------------
# Use pre-built base image with all heavy dependencies
# Build base with: docker build -f dockerfile.base -t ghcr.io/xiaden/nomarr-base:latest .
FROM ghcr.io/xiaden/nomarr-base:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ----------------------------------------------------------------------
#  User and working directory
# ----------------------------------------------------------------------
RUN useradd -m -u 1000 appuser
WORKDIR /app

# ----------------------------------------------------------------------
#  Copy in project files (fast - no pip installs!)
# ----------------------------------------------------------------------
# Single COPY layer for all app files (7 dirs + 2 files = 1 layer instead of 10)
COPY nomarr/ models/ config/ scripts/ docs/ tests/ /app/
COPY pytest.ini readme.md docker/cleanup-cron.sh /app/
COPY docker/nom-cli.sh /usr/local/bin/nom

# Note: Frontend is built separately (npm run build in frontend/)
# Vite builds directly to nomarr/public_html/, which is copied above

# Combine RUN commands to reduce layers (4 commands = 1 layer instead of 4)
RUN chmod +x /app/cleanup-cron.sh /usr/local/bin/nom && \
    echo "0 3 * * * /app/cleanup-cron.sh" > /etc/cron.d/nomarr-cleanup && \
    chmod 0644 /etc/cron.d/nomarr-cleanup && \
    crontab /etc/cron.d/nomarr-cleanup && \
    mkdir -p /app/config/db && \
    chown -R appuser:appuser /app

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