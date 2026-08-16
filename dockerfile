# ----------------------------------------------------------------------
#  Nomarr - Audio auto-tagging (GPU-enabled)
#  Fast build using pre-built base image
# ----------------------------------------------------------------------
# Use pre-built base image with all heavy dependencies
# Build base with: docker build -f dockerfile.base -t ghcr.io/xiaden/nomarr-base:latest .
ARG BASE_TAG=latest

# ----------------------------------------------------------------------
#  Frontend builder stage (Node 24)
#  Reproducible: npm ci from the committed lockfile, then a production
#  build. The bundle is emitted to frontend/dist (see vite.config.ts) and
#  copied into the runtime image below, so the generated frontend tree is
#  never committed to git. Mirrors the frontend-checks.yml CI gate.
# ----------------------------------------------------------------------
FROM node:24 AS frontend-builder

WORKDIR /build/frontend

# Install from the lockfile first (layer-cached unless the lockfile changes)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy the remaining frontend source needed for `npm run build`
# (tsc -b && vite build). Do NOT copy node_modules.
COPY frontend/index.html ./
COPY frontend/public ./public
COPY frontend/src ./src
COPY frontend/tsconfig.json frontend/tsconfig.app.json frontend/tsconfig.node.json ./
COPY frontend/vite.config.ts ./vite.config.ts

RUN npm run build

# ----------------------------------------------------------------------
#  Runtime stage (pre-built base image)
# ----------------------------------------------------------------------
FROM ghcr.io/xiaden/nomarr-base:${BASE_TAG}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ----------------------------------------------------------------------
#  User and working directory
# ----------------------------------------------------------------------
# Ubuntu 24.04 CUDA images already have a user at UID 1000 ('ubuntu'),
# so reuse it or create appuser only if UID is free
RUN if id -nu 1000 >/dev/null 2>&1; then \
        OLD_USER=$(id -nu 1000) && \
        usermod -l appuser -d /home/appuser -m "$OLD_USER" && \
        OLD_GROUP=$(id -gn 1000) && \
        groupmod -n appuser "$OLD_GROUP"; \
    else \
        useradd -m -u 1000 appuser; \
    fi
WORKDIR /app

# ----------------------------------------------------------------------
#  Copy in project files (fast - no pip installs!)
# ----------------------------------------------------------------------
# Copy directories preserving structure
COPY nomarr/ /app/nomarr/
COPY build_resources/models/ /app/models/
COPY build_resources/config/ /app/config/
COPY build_resources/scripts/ /app/scripts/
COPY docs/ /app/docs/
COPY tests/ /app/tests/
# Copy individual files in one layer
COPY readme.md pyproject.toml /app/
COPY build_resources/scripts/*.sh /app/docker/
RUN cp /app/docker/cleanup-cron.sh /app/ && \
    cp /app/docker/nom-cli.sh /usr/local/bin/nom

# The tracked frontend bundle under nomarr/public_html/ was removed (P1-S9)
# and is gitignored (P1-S8). The runtime image's /app/nomarr/public_html/ is
# produced here from the frontend-builder stage, not from the checked-out
# nomarr/ tree.
COPY --from=frontend-builder /build/frontend/dist/ /app/nomarr/public_html/

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
    NOMARR_DB=/app/config/db/nomarr.db \
    NOMARR_CONFIG=/app/config/config.yaml \
    PYTHONPATH=/app:/usr/local/lib/python3/dist-packages \
    PORT=8356 \
    ORT_DISABLE_TELEMETRY=1

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