"""
Global state management for the application.
Centralized singleton instances for configuration, database, and services.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.config import compose
from nomarr.persistence.db import Database
from nomarr.persistence.queue import ProcessingQueue

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
    BLOCKING_TIMEOUT = int(api_cfg.get("blocking_timeout"))
else:
    BLOCKING_TIMEOUT = int(worker_cfg.get("blocking_timeout", 3600))

# Poll interval
if "poll_interval" in worker_cfg:
    WORKER_POLL_INTERVAL = int(worker_cfg.get("poll_interval", 2))
elif "worker_poll_interval" in api_cfg:
    WORKER_POLL_INTERVAL = int(api_cfg.get("worker_poll_interval", 2))
else:
    WORKER_POLL_INTERVAL = 2

# Worker count
WORKER_COUNT: int = max(1, min(8, int(cfg.get("worker_count", 1))))

# Library scanner
LIBRARY_PATH: str | None = cfg.get("library_path")
LIBRARY_SCAN_POLL_INTERVAL: int = int(cfg.get("library_scan_poll_interval", 2))

# ----------------------------------------------------------------------
#  Global state instances
# ----------------------------------------------------------------------
db = Database(DB_PATH)
queue = ProcessingQueue(db)

# Legacy module-level references (kept for backward compatibility)
# These are replaced by Application class - use app.application.services instead
queue_service: QueueService | None = None
library_service: LibraryService | None = None
worker_service: WorkerService | None = None
key_service: KeyManagementService | None = None  # Manages API keys, passwords, sessions

# Legacy auth references (kept for backward compatibility)
# Use app.application.api_key and app.application.admin_password instead
API_KEY: str | None = None
ADMIN_PASSWORD_PLAINTEXT: str | None = None

# Legacy infrastructure references (kept for backward compatibility)
# Use app.application.coordinator, app.application.workers, etc. instead
processor_coord: ProcessingCoordinator | None = None
processing_service: ProcessingService | None = None
worker_pool: list = []
library_scan_worker = None  # type: ignore
event_broker = None  # type: ignore
health_monitor = None  # type: ignore


# ----------------------------------------------------------------------
#  Application Class
# ----------------------------------------------------------------------
class Application:
    """
    Main application class - owns workers, services, and lifecycle management.

    Initialized by start.py BEFORE the API server starts (container startup).
    The Application starts first, then starts the API server as one of its interfaces.
    Application lifecycle = container lifecycle (start.py manages the flow).
    """

    def __init__(self):
        """Initialize application with empty state. Call start() to initialize services."""
        # Services (business logic layer)
        self.services: dict[str, Any] = {}

        # Workers and processing
        self.coordinator: ProcessingCoordinator | None = None
        self.workers: list = []
        self.library_scan_worker = None
        self.recalibration_worker = None

        # Infrastructure
        self.event_broker = None
        self.health_monitor = None

        # Auth/keys
        self.api_key: str | None = None
        self.admin_password: str | None = None

        # State tracking
        self._running = False

    def start(self):
        """
        Start the application - initialize all services, workers, and background tasks.

        This replaces the initialization that was previously in api_app.py:lifespan().
        """
        if self._running:
            import logging

            logging.warning("[Application] Already running, ignoring start() call")
            return

        import logging

        from nomarr.interfaces.api.coordinator import ProcessingCoordinator
        from nomarr.interfaces.api.event_broker import StateBroker
        from nomarr.ml.cache import warmup_predictor_cache
        from nomarr.services.health_monitor import HealthMonitor
        from nomarr.services.keys import KeyManagementService
        from nomarr.services.library import LibraryService
        from nomarr.services.processing import ProcessingService
        from nomarr.services.queue import QueueService
        from nomarr.services.worker import WorkerService
        from nomarr.services.workers.scanner import LibraryScanWorker

        logging.info("[Application] Starting...")

        # Cleanup orphaned jobs from previous sessions
        logging.info("[Application] Checking for orphaned jobs...")
        reset_count = queue.reset_stuck_jobs()
        if reset_count > 0:
            logging.info(f"[Application] Reset {reset_count} orphaned job(s) from 'running' to 'pending'")

        # Reset stuck library scans
        logging.info("[Application] Checking for stuck library scans...")
        scan_reset_count = db.reset_running_library_scans()
        if scan_reset_count > 0:
            logging.info(f"[Application] Reset {scan_reset_count} stuck library scan(s)")

        # Initialize keys and authentication
        logging.info("[Application] Initializing authentication...")
        key_service = KeyManagementService(db)
        self.api_key = key_service.get_or_create_api_key()
        self.admin_password = key_service.get_or_create_admin_password(cfg.get("admin_password"))
        key_service.load_sessions_from_db()
        self.services["keys"] = key_service

        # Initialize event broker
        logging.info("[Application] Initializing event broker...")
        self.event_broker = StateBroker()

        # Start processing coordinator
        logging.info(f"[Application] Starting ProcessingCoordinator with {WORKER_COUNT} workers...")
        self.coordinator = ProcessingCoordinator(worker_count=WORKER_COUNT, event_broker=self.event_broker)
        self.coordinator.start()

        # Initialize services
        logging.info("[Application] Initializing services...")
        self.services["processing"] = ProcessingService(coordinator=self.coordinator)
        self.services["queue"] = QueueService(queue)

        worker_service = WorkerService(
            db=db,
            queue=queue,
            processor_coord=self.coordinator,
            default_enabled=WORKER_ENABLED_DEFAULT,
            worker_count=WORKER_COUNT,
            poll_interval=WORKER_POLL_INTERVAL,
        )
        self.services["worker"] = worker_service

        # Warm up predictor cache
        logging.info("[Application] Warming up predictor cache...")
        try:
            warmup_predictor_cache()
            logging.info("[Application] Predictor cache warmed successfully")
        except Exception as e:
            logging.error(f"[Application] Failed to warm predictor cache: {e}")

        # Start workers if enabled
        if worker_service.is_enabled():
            self.workers = worker_service.start_workers(event_broker=self.event_broker)
        else:
            logging.info("[Application] Workers not started (worker_enabled=false)")

        # Start library scan worker if configured
        if LIBRARY_PATH:
            logging.info(f"[Application] Starting LibraryScanWorker with library_path={LIBRARY_PATH}")
            self.library_scan_worker = LibraryScanWorker(
                db=db,
                library_path=LIBRARY_PATH,
                namespace=cfg.get("namespace", "essentia"),
                poll_interval=LIBRARY_SCAN_POLL_INTERVAL,
                auto_tag=cfg.get("library_auto_tag", False),
                ignore_patterns=cfg.get("library_ignore_patterns", ""),
            )
            self.library_scan_worker.start()

            self.services["library"] = LibraryService(
                db=db,
                library_path=LIBRARY_PATH,
                worker=self.library_scan_worker,
            )
        else:
            logging.info("[Application] LibraryScanWorker not started (no library_path)")

        # Start recalibration worker
        logging.info("[Application] Starting RecalibrationWorker...")
        from nomarr.services.recalibration import RecalibrationService
        from nomarr.services.workers.recalibration import RecalibrationWorker

        self.recalibration_worker = RecalibrationWorker(
            db=db,
            models_dir=cfg.get("models_dir", "/app/models"),
            namespace=cfg.get("namespace", "essentia"),
            poll_interval=2,
            calibrate_heads=cfg.get("calibrate_heads", False),
        )
        self.recalibration_worker.start()

        self.services["recalibration"] = RecalibrationService(
            database=db,
            worker=self.recalibration_worker,
        )

        # Start health monitor
        logging.info("[Application] Starting health monitor...")
        self.health_monitor = HealthMonitor(check_interval=10)

        # Register tagger workers
        def cleanup_orphaned_jobs():
            if "worker" in self.services:
                self.services["worker"].cleanup_orphaned_jobs()

        for worker in self.workers:
            self.health_monitor.register_worker(worker, on_death=cleanup_orphaned_jobs)

        # Register library scan worker
        if self.library_scan_worker:
            self.health_monitor.register_worker(self.library_scan_worker, name="LibraryScanWorker")

        # Register recalibration worker
        if self.recalibration_worker:
            self.health_monitor.register_worker(self.recalibration_worker, name="RecalibrationWorker")

        self.health_monitor.start()

        self._running = True
        logging.info("[Application] Started successfully")

    def stop(self):
        """
        Stop the application - clean shutdown of all services and workers.

        This replaces the shutdown logic that was in api_app.py:lifespan().
        """
        if not self._running:
            return

        import logging

        logging.info("[Application] Shutting down...")

        # Stop health monitor
        if self.health_monitor:
            logging.info("[Application] Stopping health monitor...")
            self.health_monitor.stop()

        # Stop library scan worker
        if self.library_scan_worker:
            logging.info("[Application] Stopping library scan worker...")
            self.library_scan_worker.stop()

        # Stop recalibration worker
        if self.recalibration_worker:
            logging.info("[Application] Stopping recalibration worker...")
            self.recalibration_worker.stop()

        # Stop tagger workers
        if "worker" in self.services:
            logging.info("[Application] Stopping tagger workers...")
            self.services["worker"].stop_all_workers()

        # Stop coordinator
        if self.coordinator:
            logging.info("[Application] Stopping processing coordinator...")
            self.coordinator.stop()

        self._running = False
        logging.info("[Application] Shutdown complete")

    def is_running(self) -> bool:
        """Check if application is running."""
        return self._running


# ----------------------------------------------------------------------
#  Global application instance
# ----------------------------------------------------------------------
application = Application()
