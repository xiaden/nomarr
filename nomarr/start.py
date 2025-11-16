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

logging.basicConfig(level=logging.INFO)


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
    logging.info("Starting Nomarr Application...")
    application.start()

    # Start the API server (blocking)
    logging.info(f"Starting API server on {application.api_host}:{application.api_port}...")
    logging.info("  - Public endpoints: /api/v1/tag, /api/v1/list, /api/v1/status/*, etc.")
    logging.info(f"  - Web UI: http://{application.api_host}:{application.api_port}/ (login with admin password)")

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
