"""Nomarr Application Starter
Initializes the Application (workers, services, etc.) then starts the API server.
"""
import logging
import logging.handlers
import multiprocessing
import signal
import sys
from pathlib import Path

import uvicorn

from nomarr.helpers.logging_helper import NomarrLogFilter

# Configure logging BEFORE importing nomarr.app.
# Application.__init__ runs prepare_database_workflow() (and thus migrations)
# at module import time.  If handlers aren't attached yet, only the fallback
# lastResort handler (WARNING+) fires and all INFO migration logs are lost.
logger = logging.getLogger(__name__)
multiprocessing.set_start_method("spawn", force=True)
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
_LOG_FORMAT = "%(asctime)s %(levelname)s %(nomarr_identity_tag)s %(nomarr_role_tag)s%(context_str)s%(message)s"
file_handler = logging.handlers.RotatingFileHandler(log_dir / "nomarr.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
file_handler.addFilter(NomarrLogFilter())
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
console_handler.addFilter(NomarrLogFilter())
logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])

from nomarr.app import application  # noqa: E402


def shutdown_handler(signum, frame) -> None:
    """Handle shutdown signals gracefully."""
    logger.info("Received signal %s, shutting down...", signum)
    application.stop()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)
    logger.info("[Application] Starting Nomarr Application...")
    application.start()
    config_service = application.get_service("config")
    logger.info("Effective config: models_dir=%s db_path=%s api=%s:%d worker_poll_interval=%d tagger=%d scanner=%d recal=%d", application.models_dir, application.db_path, application.api_host, application.api_port, application.worker_poll_interval, config_service.get_worker_count("tagger"), config_service.get_worker_count("scanner"), config_service.get_worker_count("recalibration"))
    logger.info("[API] Web UI enabled at http://%s:%d/", application.api_host, application.api_port)
    try:
        uvicorn.run("nomarr.interfaces.api.api_app:api_app", host=application.api_host, port=application.api_port, timeout_keep_alive=90, log_level="info", access_log=False)
    finally:
        logger.info("API server stopped, cleaning up...")
        application.stop()
