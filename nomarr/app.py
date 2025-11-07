"""
Global state management for the application.
Centralized singleton instances for configuration, database, and services.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.config import compose
from nomarr.data.db import Database
from nomarr.data.queue import JobQueue

if TYPE_CHECKING:
    from nomarr.interfaces.api.coordinator import ProcessingCoordinator
    from nomarr.services.keys import KeyManagementService
    from nomarr.services.library import LibraryService
    from nomarr.services.processing import ProcessingService
    from nomarr.services.queue import QueueService
    from nomarr.services.worker import WorkerService

# ----------------------------------------------------------------------
#  Configuration
# ----------------------------------------------------------------------
cfg = compose({})

API_HOST: str = str(cfg["host"])
API_PORT: int = int(cfg["port"])
DB_PATH: str = str(cfg["db_path"])
WORKER_ENABLED_DEFAULT: bool = bool(cfg["worker_enabled"])

# Blocking / timeout
api_cfg = cfg.get("api", {})
worker_cfg = cfg.get("worker", {})

BLOCKING_MODE: bool = bool(api_cfg.get("blocking_mode", True))
if "blocking_timeout" in api_cfg:
    BLOCKING_TIMEOUT: int = int(api_cfg.get("blocking_timeout"))
else:
    BLOCKING_TIMEOUT: int = int(worker_cfg.get("blocking_timeout", 3600))

# Poll interval
if "poll_interval" in worker_cfg:
    WORKER_POLL_INTERVAL: int = int(worker_cfg.get("poll_interval", 2))
elif "worker_poll_interval" in api_cfg:
    WORKER_POLL_INTERVAL: int = int(api_cfg.get("worker_poll_interval", 2))
else:
    WORKER_POLL_INTERVAL: int = 2

# Worker count
WORKER_COUNT: int = max(1, min(8, int(cfg.get("worker_count", 1))))

# Library scanner
LIBRARY_PATH: str | None = cfg.get("library_path")
LIBRARY_SCAN_POLL_INTERVAL: int = int(cfg.get("library_scan_poll_interval", 2))

# ----------------------------------------------------------------------
#  Global state instances
# ----------------------------------------------------------------------
db = Database(DB_PATH)
queue = JobQueue(db)

# Services (initialized at API startup)
queue_service: QueueService | None = None
library_service: LibraryService | None = None
worker_service: WorkerService | None = None
key_service: KeyManagementService | None = None  # Manages API keys, passwords, sessions

# API keys (initialized at API startup)
API_KEY: str | None = None
INTERNAL_KEY: str | None = None
ADMIN_PASSWORD_PLAINTEXT: str | None = None

# Processing coordinator and worker pool (initialized at API startup)
processor_coord: ProcessingCoordinator | None = None
processing_service: ProcessingService | None = None
worker_pool: list = []

# Library scan worker (initialized at API startup if library_path configured)
library_scan_worker = None  # type: ignore

# SSE event broker (initialized at API startup)
event_broker = None  # type: ignore

# Worker health monitor (initialized at API startup)
health_monitor = None  # type: ignore
