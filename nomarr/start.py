#!/usr/bin/env python3
"""
Nomarr Application Starter
Initializes the Application (workers, services, etc.) then starts the API server.
"""

import logging
import logging.handlers
import multiprocessing
import signal
import sys
from pathlib import Path

import uvicorn

from nomarr.app import application
from nomarr.helpers.logging_helper import NomarrLogFilter

# CRITICAL: Set multiprocessing start method to 'spawn' before any other imports
# This prevents CUDA context corruption when forking worker processes
# (TensorFlow CUDA context doesn't survive fork() - must spawn fresh processes)
multiprocessing.set_start_method("spawn", force=True)

# Configure logging once for the whole process with rotation
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Nomarr log format: includes auto-derived identity/role tags and optional context
_LOG_FORMAT = "%(asctime)s %(levelname)s %(nomarr_identity_tag)s %(nomarr_role_tag)s%(context_str)s%(message)s"

# Create rotating file handler (10MB per file, keep 5 backup files = 50MB total)
file_handler = logging.handlers.RotatingFileHandler(
    log_dir / "nomarr.log",
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding="utf-8",
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))

# Console handler with same format
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))

# Install NomarrLogFilter on root logger BEFORE configuring handlers
# This ensures all log records have the required attributes
logging.root.addFilter(NomarrLogFilter())

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler],
)


def shutdown_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logging.info(f"Received signal {signum}, shutting down...")
    application.stop()
    sys.exit(0)


if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # Start the Application (workers, services, coordinator, etc.)
    logging.info("[Application] Starting Nomarr Application...")
    application.start()

    # Log effective configuration after services are initialized
    config_service = application.get_service("config")
    logging.info(
        "Effective config: models_dir=%s db_path=%s api=%s:%d worker_poll_interval=%d tagger=%d scanner=%d recal=%d",
        application.models_dir,
        application.db_path,
        application.api_host,
        application.api_port,
        application.worker_poll_interval,
        config_service.get_worker_count("tagger"),
        config_service.get_worker_count("scanner"),
        config_service.get_worker_count("recalibration"),
    )

    # Log Web UI URL
    logging.info("[API] Web UI enabled at http://%s:%d/", application.api_host, application.api_port)

    try:
        uvicorn.run(
            "nomarr.interfaces.api.api_app:api_app",
            host=application.api_host,
            port=application.api_port,
            timeout_keep_alive=90,
            log_level="info",
        )
    finally:
        # Cleanup after uvicorn stops (Ctrl+C, etc.)
        logging.info("API server stopped, cleaning up...")
        application.stop()
