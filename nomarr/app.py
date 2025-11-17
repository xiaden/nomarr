"""
Application composition root and dependency injection container.

This module defines the Application class, which serves as the strict DI container
and lifecycle manager for the Nomarr application. All services, workers, and infrastructure
are owned and initialized by the Application instance.

Architecture:
- Application owns: config, db, queue, services, workers, coordinator, event broker, health monitor
- All configuration values are instance attributes (no module-level config globals)
- Services are registered via register_service() during start()
- Access services via: application.get_service("name") or application.services["name"]
- Do NOT construct services directly outside of this class

The singleton instance is available as `application` at module level.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.ml.cache import warmup_predictor_cache

if TYPE_CHECKING:
    from nomarr.interfaces.api.event_broker import StateBroker
from nomarr.persistence.db import Database
from nomarr.services.config import ConfigService
from nomarr.services.coordinator import ProcessingCoordinator
from nomarr.services.health_monitor import HealthMonitor
from nomarr.services.keys import KeyManagementService
from nomarr.services.library import LibraryService
from nomarr.services.processing import ProcessingService
from nomarr.services.queue import ProcessingQueue, QueueService
from nomarr.services.recalibration import RecalibrationService
from nomarr.services.worker import WorkerService
from nomarr.services.workers.recalibration import RecalibrationWorker
from nomarr.services.workers.scanner import LibraryScanWorker


# ----------------------------------------------------------------------
#  Application Class - Composition Root & DI Container
# ----------------------------------------------------------------------
class Application:
    """
    Application composition root and dependency injection container.

    This class is the single source of truth for all application dependencies:
    - Configuration values (extracted from ConfigService)
    - Database and queue instances
    - All services (keys, queue, worker, library, processing, recalibration, etc.)
    - Workers and infrastructure (coordinator, health monitor, event broker)
    - Lifecycle management (start/stop)

    Architecture:
    - Application owns all dependencies as instance attributes
    - All config-derived values are computed in __init__
    - Services are registered via register_service() during start()
    - Access services via: application.get_service("name") or application.services["name"]
    - Do NOT construct services directly outside of this class

    Configuration Access:
    - Raw config is PRIVATE (_config) and used only internally in Application
    - External modules MUST NOT access application._config directly
    - To access config outside app.py, use: application.get_service("config").get_config()
    - Prefer using specific instance attributes (api_host, worker_count, etc.) over raw config

    The singleton instance is available as `application` at module level.
    """

    def __init__(self):
        """
        Initialize application with core dependencies.

        Loads configuration and creates database and queue immediately.
        Services are initialized later during start().
        """
        # Load configuration (private - external access via ConfigService)
        config_service = ConfigService()
        self._config = config_service.get_config()

        # Import internal constants
        from nomarr.services.config import (
            INTERNAL_BLOCKING_MODE,
            INTERNAL_BLOCKING_TIMEOUT,
            INTERNAL_HOST,
            INTERNAL_LIBRARY_SCAN_POLL_INTERVAL,
            INTERNAL_NAMESPACE,
            INTERNAL_POLL_INTERVAL,
            INTERNAL_PORT,
            INTERNAL_WORKER_ENABLED,
        )

        # Extract config-derived values as instance attributes
        # User-configurable settings
        self.db_path: str = str(self._config["db_path"])
        self.library_path: str | None = self._config.get("library_path")
        self.models_dir: str = str(self._config.get("models_dir", "/app/models"))
        self.cache_idle_timeout: int = int(self._config.get("cache_idle_timeout", 300))
        self.calibrate_heads: bool = bool(self._config.get("calibrate_heads", False))
        self.library_auto_tag: bool = bool(self._config.get("library_auto_tag", False))
        self.library_ignore_patterns: str = str(self._config.get("library_ignore_patterns", ""))
        self.admin_password_config: str | None = self._config.get("admin_password")
        self.worker_count: int = max(1, min(8, int(self._config.get("worker_count", 1))))

        # Internal constants (not user-configurable)
        self.api_host: str = INTERNAL_HOST
        self.api_port: int = INTERNAL_PORT
        self.worker_enabled_default: bool = INTERNAL_WORKER_ENABLED
        self.blocking_mode: bool = INTERNAL_BLOCKING_MODE
        self.blocking_timeout: int = INTERNAL_BLOCKING_TIMEOUT
        self.worker_poll_interval: int = INTERNAL_POLL_INTERVAL
        self.library_scan_poll_interval: int = INTERNAL_LIBRARY_SCAN_POLL_INTERVAL
        self.namespace: str = INTERNAL_NAMESPACE

        # Admin password
        self.admin_password_config: str | None = self._config.get("admin_password")

        # Core dependencies (owned by Application)
        self.db = Database(self.db_path)
        self.queue = ProcessingQueue(self.db)

        # Config service for registration
        self._config_service = config_service

        # Services container (DI registry)
        self.services: dict[str, Any] = {}

        # Workers and processing
        self.coordinator: ProcessingCoordinator | None = None
        self.workers: list = [Any]
        self.library_scan_worker: LibraryScanWorker | None = None
        self.recalibration_worker: RecalibrationWorker | None = None

        # Infrastructure
        self.event_broker: StateBroker | None = None
        self.health_monitor: HealthMonitor | None = None

        # Auth/keys
        self.api_key: str | None = None
        self.admin_password: str | None = None

        # State tracking
        self._running = False

    def register_service(self, name: str, service: Any) -> None:
        """
        Register a service in the DI container.

        Args:
            name: Service name for lookup
            service: Service instance
        """
        self.services[name] = service

    def get_service(self, name: str) -> Any:
        """
        Get a service from the DI container.

        Args:
            name: Service name

        Returns:
            Service instance

        Raises:
            KeyError: If service not found
        """
        if name not in self.services:
            raise KeyError(f"Service '{name}' not found. Available services: {list(self.services.keys())}")
        return self.services[name]

    def start(self):
        """
        Start the application - initialize all services, workers, and background tasks.

        This method:
        1. Cleans up orphaned jobs and stuck scans from previous sessions
        2. Initializes authentication (API keys, passwords, sessions)
        3. Registers all services in self.services (DI container)
        4. Starts workers, coordinator, health monitor, and event broker
        5. Performs ML cache warmup

        All dependencies are injected via constructors using instance attributes.
        Services are registered via register_service() for access by interfaces.
        """
        if self._running:
            logging.warning("[Application] Already running, ignoring start() call")
            return

        logging.info("[Application] Starting...")

        # Cleanup orphaned jobs from previous sessions
        logging.info("[Application] Checking for orphaned jobs...")
        reset_count = self.queue.reset_stuck_jobs()
        if reset_count > 0:
            logging.info(f"[Application] Reset {reset_count} orphaned job(s) from 'running' to 'pending'")

        # Reset stuck library scans
        logging.info("[Application] Checking for stuck library scans...")
        scan_reset_count = self.db.library.reset_running_library_scans()
        if scan_reset_count > 0:
            logging.info(f"[Application] Reset {scan_reset_count} stuck library scan(s)")

        # Initialize keys and authentication (DI: inject db)
        logging.info("[Application] Initializing authentication...")
        key_service = KeyManagementService(self.db)
        self.api_key = key_service.get_or_create_api_key()
        self.admin_password = key_service.get_or_create_admin_password(self.admin_password_config)
        key_service.load_sessions_from_db()
        self.register_service("keys", key_service)
        self.register_service("config", self._config_service)

        # Initialize event broker (lazy import to avoid circular dependency)
        logging.info("[Application] Initializing event broker...")
        from nomarr.interfaces.api.event_broker import StateBroker

        self.event_broker = StateBroker()

        # Start processing coordinator (DI: inject worker count and event broker)
        logging.info(f"[Application] Starting ProcessingCoordinator with {self.worker_count} workers...")
        self.coordinator = ProcessingCoordinator(worker_count=self.worker_count, event_broker=self.event_broker)
        self.coordinator.start()

        # Initialize services (DI: inject dependencies)
        logging.info("[Application] Initializing services...")
        self.register_service("processing", ProcessingService(coordinator=self.coordinator))
        self.register_service("queue", QueueService(self.queue))

        worker_service = WorkerService(
            db=self.db,
            queue=self.queue,
            processor_coord=self.coordinator,
            default_enabled=self.worker_enabled_default,
            worker_count=self.worker_count,
            poll_interval=self.worker_poll_interval,
        )
        self.register_service("worker", worker_service)

        # Warm up predictor cache
        logging.info("[Application] Warming up predictor cache...")
        try:
            warmup_predictor_cache(
                models_dir=self.models_dir,
                cache_idle_timeout=self.cache_idle_timeout,
            )
            logging.info("[Application] Predictor cache warmed successfully")
        except Exception as e:
            logging.error(f"[Application] Failed to warm predictor cache: {e}")

        # Start workers if enabled
        if worker_service.is_enabled():
            self.workers = worker_service.start_workers(event_broker=self.event_broker)
        else:
            logging.info("[Application] Workers not started (worker_enabled=false)")

        # Start library scan worker if configured (DI: inject db and config)
        if self.library_path:
            logging.info(f"[Application] Starting LibraryScanWorker with library_path={self.library_path}")
            self.library_scan_worker = LibraryScanWorker(
                db=self.db,
                library_path=self.library_path,
                namespace=self.namespace,
                poll_interval=self.library_scan_poll_interval,
                auto_tag=self.library_auto_tag,
                ignore_patterns=self.library_ignore_patterns,
            )
            self.library_scan_worker.start()

            self.register_service(
                "library",
                LibraryService(
                    db=self.db,
                    library_path=self.library_path,
                    worker=self.library_scan_worker,
                ),
            )
        else:
            logging.info("[Application] LibraryScanWorker not started (no library_path)")

        # Start recalibration worker (DI: inject db and config)
        logging.info("[Application] Starting RecalibrationWorker...")
        self.recalibration_worker = RecalibrationWorker(
            db=self.db,
            models_dir=self.models_dir,
            namespace=self.namespace,
            poll_interval=2,
            calibrate_heads=self.calibrate_heads,
        )
        self.recalibration_worker.start()

        self.register_service(
            "recalibration",
            RecalibrationService(
                database=self.db,
                worker=self.recalibration_worker,
            ),
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

    def warmup_cache(self) -> None:
        """
        Warmup the ML predictor cache.

        Interfaces should call this method rather than importing ml.cache directly.
        Uses instance config attributes.
        """
        warmup_predictor_cache(
            models_dir=self.models_dir,
            cache_idle_timeout=self.cache_idle_timeout,
        )


# ----------------------------------------------------------------------
#  Global application instance
# ----------------------------------------------------------------------
application = Application()
