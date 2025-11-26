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

if TYPE_CHECKING:
    from nomarr.components.events.event_broker_comp import StateBroker
from nomarr.persistence.db import Database
from nomarr.services.analytics_svc import AnalyticsService
from nomarr.services.calibration_svc import CalibrationService
from nomarr.services.config_svc import ConfigService
from nomarr.services.coordinator_svc import CoordinatorService
from nomarr.services.health_monitor_svc import HealthMonitorService
from nomarr.services.keys_svc import KeyManagementService
from nomarr.services.library_svc import LibraryRootConfig, LibraryService
from nomarr.services.navidrome_svc import NavidromeService
from nomarr.services.processing_svc import ProcessingService
from nomarr.services.queue_svc import ProcessingQueue, QueueService, RecalibrationQueue
from nomarr.services.recalibration_svc import RecalibrationService
from nomarr.services.worker_svc import WorkerService
from nomarr.services.workers.base import BaseWorker
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
        self._config = config_service.get_config().config

        # Import internal constants
        from nomarr.services.config_svc import (
            INTERNAL_HOST,
            INTERNAL_LIBRARY_SCAN_POLL_INTERVAL,
            INTERNAL_NAMESPACE,
            INTERNAL_POLL_INTERVAL,
            INTERNAL_PORT,
            INTERNAL_VERSION_TAG,
            INTERNAL_WORKER_ENABLED,
        )

        # Extract config-derived values as instance attributes
        # User-configurable settings
        self.db_path: str = str(self._config["db_path"])
        self.library_root: str | None = self._config.get("library_root")
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
        self.worker_poll_interval: int = INTERNAL_POLL_INTERVAL
        self.library_scan_poll_interval: int = INTERNAL_LIBRARY_SCAN_POLL_INTERVAL
        self.namespace: str = INTERNAL_NAMESPACE
        self.version_tag_key: str = INTERNAL_VERSION_TAG

        # Core dependencies (owned by Application)
        self.db = Database(self.db_path)
        self.queue = ProcessingQueue(self.db)

        # Config service for registration
        self._config_service = config_service

        # Services container (DI registry)
        self.services: dict[str, Any] = {}

        # Workers and processing
        self.coordinator: CoordinatorService | None = None
        self.workers: list = [Any]
        self.library_scan_worker: LibraryScanWorker | None = None
        self.recalibration_worker: BaseWorker | None = None

        # Infrastructure
        self.event_broker: StateBroker | None = None
        self.health_monitor: HealthMonitorService | None = None

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
        scan_reset_count = self.db.library_queue.reset_running_library_scans()
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
        from nomarr.components.events.event_broker_comp import StateBroker

        self.event_broker = StateBroker()

        # Start processing coordinator (DI: inject worker count and event broker)
        logging.info(f"[Application] Starting CoordinatorService with {self.worker_count} workers...")
        from nomarr.services.coordinator_svc import CoordinatorConfig

        coordinator_cfg = CoordinatorConfig(
            worker_count=self.worker_count,
            event_broker=self.event_broker,
        )
        self.coordinator = CoordinatorService(cfg=coordinator_cfg)
        self.coordinator.start()

        # Initialize services (DI: inject dependencies)
        logging.info("[Application] Initializing services...")
        self.register_service("processing", ProcessingService(coordinator=self.coordinator))
        self.register_service("queue", QueueService(self.queue))

        from nomarr.services.worker_svc import WorkerConfig

        worker_cfg = WorkerConfig(
            default_enabled=self.worker_enabled_default,
            worker_count=self.worker_count,
            poll_interval=self.worker_poll_interval,
        )
        worker_service = WorkerService(
            db=self.db,
            queue=self.queue,
            cfg=worker_cfg,
            processor_coord=self.coordinator,
        )
        self.register_service("worker", worker_service)

        # Register ML service
        from nomarr.services.ml_svc import MLConfig, MLService

        ml_cfg = MLConfig(
            models_dir=str(self.models_dir),
            cache_idle_timeout=self.cache_idle_timeout,
        )
        ml_service = MLService(cfg=ml_cfg)
        self.register_service("ml", ml_service)

        # Warm up predictor cache
        logging.info("[Application] Warming up predictor cache...")
        try:
            ml_service.warmup_cache()
            logging.info("[Application] Predictor cache warmed successfully")
        except Exception as e:
            logging.error(f"[Application] Failed to warm predictor cache: {e}")

        # Register Analytics service (DI: inject db, namespace)
        logging.info("[Application] Initializing AnalyticsService...")
        from nomarr.services.analytics_svc import AnalyticsConfig

        analytics_cfg = AnalyticsConfig(namespace=self.namespace)
        analytics_service = AnalyticsService(db=self.db, cfg=analytics_cfg)
        self.register_service("analytics", analytics_service)

        # Register Calibration service (DI: inject db, models_dir, namespace)
        logging.info("[Application] Initializing CalibrationService...")
        from nomarr.services.calibration_svc import CalibrationConfig

        calibration_cfg = CalibrationConfig(
            models_dir=str(self.models_dir),
            namespace=self.namespace,
        )
        calibration_service = CalibrationService(db=self.db, cfg=calibration_cfg)
        self.register_service("calibration", calibration_service)

        # Register Navidrome service (DI: inject db, namespace)
        logging.info("[Application] Initializing NavidromeService...")
        from nomarr.services.navidrome_svc import NavidromeConfig

        navidrome_cfg = NavidromeConfig(namespace=self.namespace)
        navidrome_service = NavidromeService(db=self.db, cfg=navidrome_cfg)
        self.register_service("navidrome", navidrome_service)

        # Start workers if enabled
        if worker_service.is_enabled():
            self.workers = worker_service.start_workers(event_broker=self.event_broker)
        else:
            logging.info("[Application] Workers not started (worker_enabled=false)")

        # Start library scan worker if configured (DI: inject db and config)
        if self.library_root:
            logging.info(f"[Application] Starting LibraryScanWorker with namespace={self.namespace}")
            self.library_scan_worker = LibraryScanWorker(
                db=self.db,
                event_broker=self.event_broker,
                namespace=self.namespace,
                interval=self.library_scan_poll_interval,
                auto_tag=self.library_auto_tag,
                ignore_patterns=self.library_ignore_patterns,
            )
            self.library_scan_worker.start()

            library_cfg = LibraryRootConfig(
                namespace=self.namespace,
                library_root=self.library_root,
            )
            library_service = LibraryService(
                db=self.db,
                cfg=library_cfg,
                worker=self.library_scan_worker,
            )
            # Ensure at least one library exists (migrate from single library_root config)
            library_service.ensure_default_library_exists()
            self.register_service("library", library_service)
        else:
            logging.info("[Application] LibraryScanWorker not started (no library_root)")

        # Start recalibration worker (DI: inject db, queue, and config)
        logging.info("[Application] Starting RecalibrationWorker...")
        recalibration_queue = RecalibrationQueue(self.db)
        self.recalibration_worker = RecalibrationWorker(
            db=self.db,
            queue=recalibration_queue,
            event_broker=self.event_broker,
            models_dir=self.models_dir,
            namespace=self.namespace,
            version_tag_key=self.version_tag_key,
            interval=2,
            worker_id=0,
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
        from nomarr.services.health_monitor_svc import HealthMonitorConfig

        health_monitor_cfg = HealthMonitorConfig(check_interval=10)
        self.health_monitor = HealthMonitorService(cfg=health_monitor_cfg)

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
        ml_service = self.services.get("ml")
        if ml_service is None:
            raise RuntimeError("ML service not initialized")
        ml_service.warmup_cache()


# ----------------------------------------------------------------------
#  Global application instance
# ----------------------------------------------------------------------
application = Application()
