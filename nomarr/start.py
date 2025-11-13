#!/usr/bin/env python3
"""
Nomarr Application Starter
Initializes the Application (workers, services, etc.) then starts the API server.
"""

import logging
import signal
import sys

import uvicorn

import nomarr.app as app

logging.basicConfig(level=logging.INFO)


def shutdown_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logging.info(f"Received signal {signum}, shutting down...")
    app.application.stop()
    sys.exit(0)


if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # Start the Application (workers, services, coordinator, etc.)
    logging.info("Starting Nomarr Application...")
    app.application.start()

    # Start the API server (blocking)
    logging.info("Starting API server on 0.0.0.0:8356...")
    logging.info("  - Public endpoints: /api/v1/tag, /api/v1/list, /api/v1/status/*, etc.")
    logging.info("  - Web UI: http://0.0.0.0:8356/ (login with admin password)")

    try:
        uvicorn.run(
            "nomarr.interfaces.api.api_app:api_app",
            host="0.0.0.0",
            port=8356,
            timeout_keep_alive=90,
            log_level="info",
        )
    finally:
        # Cleanup after uvicorn stops (Ctrl+C, etc.)
        logging.info("API server stopped, cleaning up...")
        app.application.stop()
