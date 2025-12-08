#!/usr/bin/env python3
"""
Nomarr Application Starter
Initializes the Application (workers, services, etc.) then starts the API server.
"""

import logging
import signal
import sys

import uvicorn

from nomarr.app import application

# Configure logging once for the whole process
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def shutdown_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logging.info(f"Received signal {signum}, shutting down...")
    application.stop()
    sys.exit(0)


if __name__ == "__main__":
    # Log effective configuration
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

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # Start the Application (workers, services, coordinator, etc.)
    logging.info("[Application] Starting Nomarr Application...")
    application.start()

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
