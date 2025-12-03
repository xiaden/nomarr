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
from nomarr.services.recalibration_svc import RecalibrationService
from nomarr.services.worker_pool_svc import WorkerPoolConfig, WorkerPoolService
from nomarr.services.workers.recalibration import RecalibrationWorker
from nomarr.services.workers.scanner import LibraryScanWorker
from nomarr.services.workers.tagger import TaggerWorker


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
        # Queue operations now use components (no queue wrapper needed)

        # Config service for registration
        self._config_service = config_service

        # Services container (DI registry)
        self.services: dict[str, Any] = {}

        # Workers and processing
        self.tagger_coordinator: CoordinatorService | None = None
        self.scanner_coordinator: CoordinatorService | None = None
        self.recalibration_coordinator: CoordinatorService | None = None
        self.workers: list = []
        self.tagger_pool_service: WorkerPoolService | None = None
        self.scanner_pool_service: WorkerPoolService | None = None
        self.recalibration_pool_service: WorkerPoolService | None = None
        self.workers_coordinator: Any = None  # Set during initialization to WorkersCoordinator

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
        from nomarr.components.queue import reset_stuck_jobs

        reset_count = reset_stuck_jobs(self.db, queue_type="tag")
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

        # Create processing backends for all three worker types
        logging.info("[Application] Setting up processing backends...")
        from nomarr.services import processing_backends

        # Create three coordinators with pooled backends
        logging.info(
            f"[Application] Starting three CoordinatorService instances with {self.worker_count} workers each..."
        )
        from nomarr.services.coordinator_svc import CoordinatorConfig, CoordinatorService

        coordinator_cfg = CoordinatorConfig(
            worker_count=self.worker_count,
            event_broker=self.event_broker,
        )

        # Tagger coordinator with pooled tagger backend
        self.tagger_coordinator = CoordinatorService(
            cfg=coordinator_cfg,
            processing_backend=processing_backends.pooled_tagger_backend,
        )
        self.tagger_coordinator.start()

        # Scanner coordinator with pooled scanner backend
        self.scanner_coordinator = CoordinatorService(
            cfg=coordinator_cfg,
            processing_backend=processing_backends.pooled_scanner_backend,
        )
        self.scanner_coordinator.start()

        # Recalibration coordinator with pooled recalibration backend
        self.recalibration_coordinator = CoordinatorService(
            cfg=coordinator_cfg,
            processing_backend=processing_backends.pooled_recalibration_backend,
        )
        self.recalibration_coordinator.start()

        # Wrap coordinators with coordinator backends (for workers)
        tagger_backend = processing_backends.make_coordinator_backend(self.tagger_coordinator)
        scanner_backend = processing_backends.make_coordinator_backend(self.scanner_coordinator)
        recalibration_backend = processing_backends.make_coordinator_backend(self.recalibration_coordinator)

        # Initialize services (DI: inject dependencies)
        logging.info("[Application] Initializing services...")
        # QueueService removed - interfaces now call components/workflows directly

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

        # Register Info service (DI: inject worker, queue, coordinator, ml services + config)
        logging.info("[Application] Initializing InfoService...")
        from nomarr.services.info_svc import InfoConfig, InfoService

        info_cfg = InfoConfig(
            version="1.2",
            namespace=self.namespace,
            models_dir=str(self.models_dir),
            db_path=self.db_path,
            api_host=self.api_host,
            api_port=self.api_port,
            worker_enabled_default=self.worker_enabled_default,
            worker_count=self.worker_count,
            poll_interval=float(self.worker_poll_interval),
        )
        info_service = InfoService(
            cfg=info_cfg,
            workers_coordinator=self.workers_coordinator,
            queue_service=self.services.get("queue"),
            processor_coord=self.tagger_coordinator,
            ml_service=self.services.get("ml"),
        )
        self.register_service("info", info_service)

        # Get per-pool worker counts from ConfigService (with fallback to global worker_count)
        tagger_worker_count = self._config_service.get_worker_count("tagger")
        scanner_worker_count = self._config_service.get_worker_count("scanner")
        recalibration_worker_count = self._config_service.get_worker_count("recalibration")

        logging.info(
            f"[Application] Worker counts: tagger={tagger_worker_count}, "
            f"scanner={scanner_worker_count}, recalibration={recalibration_worker_count}"
        )

        # Create three worker pools using WorkerPoolService
        # TODO: Worker architecture refactor (Phase 3-5 from REFACTORING_PLAN_WORKERS.md)
        # WorkerPoolService is legacy - will be replaced with WorkerSystemService
        # that manages multiple Process-based workers per queue type
        # For now, keep existing worker architecture while queue components are stabilizing
        logging.info("[Application] Setting up three worker pools (tagger, scanner, recalibration)...")

        # Temporary: Create a ProcessingQueue for legacy WorkerPoolService
        # Will be removed when workers are converted to use components directly
        from nomarr.services.queue_svc import BaseQueue, ProcessingQueue, RecalibrationQueue, ScanQueue

        legacy_queue = ProcessingQueue(self.db)

        # 1. Tagger worker pool
        tagger_pool_cfg = WorkerPoolConfig(
            worker_count=tagger_worker_count,
            poll_interval=self.worker_poll_interval,
        )

        def make_tagger_worker(
            db: Database, queue: BaseQueue, backend: Any, broker: Any, interval: int, worker_id: int
        ) -> TaggerWorker:
            return TaggerWorker(db, queue, backend, broker, interval, worker_id)  # type: ignore[arg-type]

        self.tagger_pool_service = WorkerPoolService(
            db=self.db,
            queue=legacy_queue,
            processing_backend=tagger_backend,
            event_broker=self.event_broker,
            cfg=tagger_pool_cfg,
            worker_factory=make_tagger_worker,
            name="TaggerPool",
        )

        # 2. Scanner worker pool (only if library_root is configured)
        self.scanner_pool_service = None
        if self.library_root:
            scan_queue = ScanQueue(self.db)

            scanner_pool_cfg = WorkerPoolConfig(
                worker_count=scanner_worker_count,
                poll_interval=self.worker_poll_interval,
            )

            def make_scanner_worker(
                db: Database, queue: BaseQueue, backend: Any, broker: Any, interval: int, worker_id: int
            ) -> LibraryScanWorker:
                return LibraryScanWorker(db, queue, backend, broker, interval, worker_id)  # type: ignore[arg-type]

            self.scanner_pool_service = WorkerPoolService(
                db=self.db,
                queue=scan_queue,
                processing_backend=scanner_backend,
                event_broker=self.event_broker,
                cfg=scanner_pool_cfg,
                worker_factory=make_scanner_worker,
                name="ScannerPool",
            )

        # 3. Recalibration worker pool
        recalibration_queue = RecalibrationQueue(self.db)

        recalibration_pool_cfg = WorkerPoolConfig(
            worker_count=recalibration_worker_count,
            poll_interval=self.worker_poll_interval,
        )

        def make_recalibration_worker(
            db: Database, queue: BaseQueue, backend: Any, broker: Any, interval: int, worker_id: int
        ) -> RecalibrationWorker:
            return RecalibrationWorker(db, queue, backend, broker, interval, worker_id)  # type: ignore[arg-type]

        self.recalibration_pool_service = WorkerPoolService(
            db=self.db,
            queue=recalibration_queue,
            processing_backend=recalibration_backend,
            event_broker=self.event_broker,
            cfg=recalibration_pool_cfg,
            worker_factory=make_recalibration_worker,
            name="RecalibrationPool",
        )

        # Create WorkersCoordinator to manage all three pools
        logging.info("[Application] Initializing WorkersCoordinator...")
        from nomarr.services.workers_coordinator_svc import WorkersCoordinator

        self.workers_coordinator = WorkersCoordinator(
            db=self.db,
            tagger_pool_service=self.tagger_pool_service,
            scanner_pool_service=self.scanner_pool_service,
            recalibration_pool_service=self.recalibration_pool_service,
            default_enabled=self.worker_enabled_default,
        )
        self.register_service("workers", self.workers_coordinator)

        # Start all worker pools via coordinator
        self.workers_coordinator.start_all_worker_pools()
        self.workers = self.tagger_pool_service.worker_pool  # For backward compat with health monitor

        # Register library service if library_root is configured
        if self.library_root:
            logging.info(f"[Application] Registering LibraryService with namespace={self.namespace}")

            library_cfg = LibraryRootConfig(
                namespace=self.namespace,
                library_root=self.library_root,
            )
            library_service = LibraryService(
                db=self.db,
                cfg=library_cfg,
                worker=None,  # LibraryService will use scanner_pool_service instead
            )
            # Ensure at least one library exists (migrate from single library_root config)
            library_service.ensure_default_library_exists()
            self.register_service("library", library_service)
        else:
            logging.info("[Application] LibraryScanWorker not started (no library_root)")

        # Register recalibration service
        self.register_service(
            "recalibration",
            RecalibrationService(
                database=self.db,
                worker=None,  # RecalibrationService will use recalibration_pool_service instead
                library_service=self.services.get("library"),
            ),
        )

        # Start health monitor
        logging.info("[Application] Starting health monitor...")
        from nomarr.services.health_monitor_svc import HealthMonitorConfig

        health_monitor_cfg = HealthMonitorConfig(check_interval=10)
        self.health_monitor = HealthMonitorService(cfg=health_monitor_cfg)

        # Register tagger workers with health monitor
        for worker in self.workers:
            self.health_monitor.register_worker(worker, name=f"TaggerWorker-{worker.worker_id}")

        # Register scanner workers with health monitor
        if self.scanner_pool_service:
            for worker in self.scanner_pool_service.worker_pool:
                self.health_monitor.register_worker(worker, name=f"ScannerWorker-{worker.worker_id}")

        # Register recalibration workers with health monitor
        for worker in self.recalibration_pool_service.worker_pool:
            self.health_monitor.register_worker(worker, name=f"RecalibrationWorker-{worker.worker_id}")

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

        # Stop all three worker pools
        logging.info("[Application] Stopping all worker pools...")

        if hasattr(self, "tagger_pool_service") and self.tagger_pool_service:
            logging.info("[Application] Stopping tagger worker pool...")
            self.tagger_pool_service.stop_all_workers()

        if hasattr(self, "scanner_pool_service") and self.scanner_pool_service:
            logging.info("[Application] Stopping scanner worker pool...")
            self.scanner_pool_service.stop_all_workers()

        if hasattr(self, "recalibration_pool_service") and self.recalibration_pool_service:
            logging.info("[Application] Stopping recalibration worker pool...")
            self.recalibration_pool_service.stop_all_workers()

        # Stop three coordinators
        if hasattr(self, "tagger_coordinator") and self.tagger_coordinator:
            logging.info("[Application] Stopping tagger coordinator...")
            self.tagger_coordinator.stop()

        if hasattr(self, "scanner_coordinator") and self.scanner_coordinator:
            logging.info("[Application] Stopping scanner coordinator...")
            self.scanner_coordinator.stop()

        if hasattr(self, "recalibration_coordinator") and self.recalibration_coordinator:
            logging.info("[Application] Stopping recalibration coordinator...")
            self.recalibration_coordinator.stop()

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
