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
import os
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.components.events.event_broker_comp import StateBroker
from nomarr.persistence.db import Database


def validate_environment() -> None:
    """Validate required environment variables at startup.

    Prevents workers from each spamming "missing ARANGO_HOST" errors.
    Fails fast with clear message if config is incomplete.
    """
    required_vars = [
        "ARANGO_HOST",
        "ARANGO_PASSWORD",
    ]

    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        print("\nRequired for ArangoDB connection:", file=sys.stderr)
        print("  ARANGO_HOST - Database server URL (e.g., http://nomarr-arangodb:8529)", file=sys.stderr)
        print("  ARANGO_PASSWORD - App user password (NOT root password)", file=sys.stderr)
        print("\nOptional (have defaults):", file=sys.stderr)
        print("  ARANGO_USERNAME - Database username (default: nomarr)", file=sys.stderr)
        print("  ARANGO_DBNAME - Database name (default: nomarr)", file=sys.stderr)
        sys.exit(1)


from nomarr.services.domain.analytics_svc import AnalyticsService
from nomarr.services.domain.calibration_svc import CalibrationService
from nomarr.services.domain.library_svc import LibraryRootConfig, LibraryService
from nomarr.services.domain.navidrome_svc import NavidromeService
from nomarr.services.domain.recalibration_svc import RecalibrationService
from nomarr.services.infrastructure.config_svc import ConfigService

# DELETED: from nomarr.services.coordinator_svc import CoordinatorService
from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorService
from nomarr.services.infrastructure.keys_svc import KeyManagementService
from nomarr.services.infrastructure.queue_svc import QueueService
from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

# DELETED: from nomarr.services.worker_pool_svc import WorkerPoolConfig, WorkerPoolService


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
    - Prefer using specific instance attributes (api_host, models_dir, etc.) over raw config

    The singleton instance is available as `application` at module level.
    """

    def __init__(self):
        """
        Initialize application with core dependencies.

        Loads configuration and creates database and queue immediately.
        Services are initialized later during start().
        """
        # Validate environment variables early
        validate_environment()

        # Load configuration (private - external access via ConfigService)
        config_service = ConfigService()
        self._config = config_service.get_config().config

        # Import internal constants
        from nomarr.services.infrastructure.config_svc import (
            INTERNAL_HOST,
            INTERNAL_LIBRARY_SCAN_POLL_INTERVAL,
            INTERNAL_NAMESPACE,
            INTERNAL_POLL_INTERVAL,
            INTERNAL_PORT,
            INTERNAL_VERSION_TAG,
            INTERNAL_WORKER_ENABLED,
            TAGGER_VERSION,
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

        # Internal constants (not user-configurable)
        self.api_host: str = INTERNAL_HOST
        self.api_port: int = INTERNAL_PORT
        self.worker_enabled_default: bool = INTERNAL_WORKER_ENABLED
        self.worker_poll_interval: int = INTERNAL_POLL_INTERVAL
        self.library_scan_poll_interval: int = INTERNAL_LIBRARY_SCAN_POLL_INTERVAL
        self.namespace: str = INTERNAL_NAMESPACE
        self.version_tag_key: str = INTERNAL_VERSION_TAG
        self.tagger_version: str = TAGGER_VERSION

        # Core dependencies (owned by Application)
        self.db = Database()

        # Config service for registration
        self._config_service = config_service

        # Services container (DI registry)
        self.services: dict[str, Any] = {}

        # Workers and processing (Phase 4: multiprocessing with health monitoring)
        self.worker_system: WorkerSystemService | None = None

        # Infrastructure
        self.event_broker: StateBroker | None = None
        self.health_monitor: HealthMonitorService | None = None
        self._heartbeat_thread: threading.Thread | None = None

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

    def _start_app_heartbeat(self) -> None:
        """Start background thread to write app heartbeat (Phase 3: DB-based IPC)."""
        from nomarr.persistence.db import Database

        def heartbeat_loop():
            # Use dedicated DB connection for this thread to avoid transaction conflicts
            heartbeat_db = Database()

            while self._running:
                try:
                    # Periodic heartbeat update (status="healthy" by default)
                    heartbeat_db.health.update_heartbeat(
                        component_id="app",
                        status="healthy",
                    )
                except Exception as e:
                    logging.error(f"[Application] Heartbeat error: {e}")
                time.sleep(5)

            # Close connection when thread exits
            heartbeat_db.close()

        self._heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True, name="AppHeartbeat")
        self._heartbeat_thread.start()
        logging.info("[Application] App heartbeat started")

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

        # Clean ephemeral state from previous runs (Phase 3: health monitoring)
        logging.info("[Application] Cleaning ephemeral runtime state...")
        self.db.health.clean_all()

        # Mark app as starting
        self.db.health.mark_starting(component_id="app", component_type="app")

        # Library scans now use BackgroundTaskService (no queue cleanup needed)

        # Initialize keys and authentication (DI: inject db)
        logging.info("[Application] Initializing authentication...")
        key_service = KeyManagementService(self.db)
        self.api_key = key_service.get_or_create_api_key()
        self.admin_password = key_service.get_or_create_admin_password(self.admin_password_config)
        key_service.load_sessions_from_db()
        self.register_service("keys", key_service)
        self.register_service("config", self._config_service)

        # Initialize event broker (Phase 3.6: DB polling for multiprocessing IPC)
        logging.info("[Application] Initializing event broker...")
        from nomarr.components.events.event_broker_comp import StateBroker

        self.event_broker = StateBroker(db=self.db, poll_interval=0.5)

        # Initialize services (DI: inject dependencies)
        logging.info("[Application] Initializing services...")

        # QueueService - TODO: Phase 4 - needs new signature
        queue_service = QueueService(self.db, self._config, event_broker=self.event_broker)
        self.register_service("queue", queue_service)

        # Register ML service
        from nomarr.services.infrastructure.ml_svc import MLConfig, MLService

        ml_cfg = MLConfig(
            models_dir=str(self.models_dir),
            cache_idle_timeout=self.cache_idle_timeout,
        )
        ml_service = MLService(cfg=ml_cfg)
        self.register_service("ml", ml_service)

        # Register Analytics service (DI: inject db, namespace)
        logging.info("[Application] Initializing AnalyticsService...")
        from nomarr.services.domain.analytics_svc import AnalyticsConfig

        analytics_cfg = AnalyticsConfig(namespace=self.namespace)
        analytics_service = AnalyticsService(db=self.db, cfg=analytics_cfg)
        self.register_service("analytics", analytics_service)

        # Register Calibration service (DI: inject db, models_dir, namespace)
        logging.info("[Application] Initializing CalibrationService...")
        from nomarr.services.domain.calibration_svc import CalibrationConfig

        calibration_cfg = CalibrationConfig(
            models_dir=str(self.models_dir),
            namespace=self.namespace,
        )
        calibration_service = CalibrationService(db=self.db, cfg=calibration_cfg)
        self.register_service("calibration", calibration_service)

        # Register Navidrome service (DI: inject db, namespace)
        logging.info("[Application] Initializing NavidromeService...")
        from nomarr.services.domain.navidrome_svc import NavidromeConfig

        navidrome_cfg = NavidromeConfig(namespace=self.namespace)
        navidrome_service = NavidromeService(db=self.db, cfg=navidrome_cfg)
        self.register_service("navidrome", navidrome_service)

        # Register Info service - TODO: Phase 4 - needs coordinators
        # Mock minimal version for now
        from nomarr.services.infrastructure.info_svc import InfoConfig, InfoService

        info_cfg = InfoConfig(
            version="1.2",
            namespace=self.namespace,
            models_dir=str(self.models_dir),
            db_path=self.db_path,
            api_host=self.api_host,
            api_port=self.api_port,
            worker_enabled_default=self.worker_enabled_default,
            tagger_worker_count=self._config_service.get_worker_count("tagger"),
            scanner_worker_count=self._config_service.get_worker_count("scanner"),
            recalibration_worker_count=self._config_service.get_worker_count("recalibration"),
            poll_interval=float(self.worker_poll_interval),
        )
        info_service = InfoService(
            cfg=info_cfg,
            workers_coordinator=self.worker_system,  # Phase 4: WorkerSystemService
            queue_service=queue_service,
            ml_service=ml_service,
        )
        self.register_service("info", info_service)

        # Create BackgroundTaskService for direct library scanning
        from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService

        background_tasks = BackgroundTaskService()
        self.register_service("background_tasks", background_tasks)

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
                background_tasks=background_tasks,
            )
            library_service.ensure_default_library_exists()
            self.register_service("library", library_service)
        else:
            logging.info("[Application] No library root configured, library service not started")

        # Register metadata service (entity navigation for hybrid graph)
        from nomarr.services.domain.metadata_svc import MetadataService

        metadata_service = MetadataService(db=self.db)
        self.register_service("metadata", metadata_service)

        # Register recalibration service
        self.register_service(
            "recalibration",
            RecalibrationService(
                database=self.db,
                library_service=self.services.get("library"),
            ),
        )

        # Initialize WorkerSystemService (Phase 4: multiprocessing with health monitoring)
        logging.info("[Application] Initializing worker system...")

        # Create processing backend functions using worker-specific factories
        from nomarr.services.infrastructure.workers.tagger import create_tagger_backend

        tagger_backend = create_tagger_backend(
            models_dir=Path(self.models_dir),
            namespace=self.namespace,
            calibrate_heads=self.calibrate_heads,
            version_tag_key=self.version_tag_key,
            tagger_version=self.tagger_version,
        )

        # Get per-pool worker counts from config
        config_service = self.get_service("config")
        tagger_count = config_service.get_worker_count("tagger")

        # Create WorkerSystemService with backends
        self.worker_system = WorkerSystemService(
            db=self.db,
            tagger_backend=tagger_backend,
            event_broker=self.event_broker,
            tagger_count=tagger_count,
            default_enabled=self.worker_enabled_default,
        )

        # Start all worker processes
        logging.info("[Application] Starting worker processes...")
        self.worker_system.start_all_workers()
        logging.info("[Application] Worker processes started")

        # Start app heartbeat thread (Phase 3: DB-based IPC)
        self._running = True
        self._start_app_heartbeat()

        # Mark app as fully healthy after all services/workers started
        self.db.health.mark_healthy(component_id="app")

        logging.info("[Application] Started successfully - all workers operational")

    def stop(self) -> None:
        """
        Stop the application - clean shutdown of all services and workers.

        This replaces the shutdown logic that was in api_app.py:lifespan().
        """
        if not self._running:
            return

        logging.info("[Application] Shutting down...")

        # Stop worker processes (Phase 4: WorkerSystemService)
        if self.worker_system:
            logging.info("[Application] Stopping worker processes...")
            self.worker_system.stop_all_workers()
            logging.info("[Application] Worker processes stopped")

        # Stop event broker polling thread (Phase 3.6: DB polling)
        if self.event_broker:
            logging.info("[Application] Stopping event broker...")
            self.event_broker.stop()

        # Stop health monitor
        if hasattr(self, "health_monitor") and self.health_monitor:
            logging.info("[Application] Stopping health monitor...")
            self.health_monitor.stop()

        # Mark app as stopping
        self.db.health.mark_stopping(component_id="app", exit_code=0)

        # Clean ephemeral state (Phase 3: health monitoring)
        logging.info("[Application] Cleaning ephemeral runtime state...")
        self.db.health.clean_all()

        self._running = False
        logging.info("[Application] Shutdown complete - all workers stopped")

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
# Don't create singleton during test runs (pytest sets this env var)
if os.environ.get("PYTEST_CURRENT_TEST") is None:
    application = Application()
else:
    # During tests, application will be None - tests should create their own instances
    application = None  # type: ignore[assignment]
