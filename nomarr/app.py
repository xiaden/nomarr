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
    pass

from nomarr.persistence.db import Database
from nomarr.services.domain.analytics_svc import AnalyticsService
from nomarr.services.domain.calibration_svc import CalibrationService
from nomarr.services.domain.library_svc import LibraryService, LibraryServiceConfig
from nomarr.services.domain.navidrome_svc import NavidromeService
from nomarr.services.domain.tagging_svc import TaggingService
from nomarr.services.infrastructure.config_svc import ConfigService
from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorService
from nomarr.services.infrastructure.keys_svc import KeyManagementService


def validate_environment() -> None:
    """Validate required environment variables at startup.

    Prevents workers from each spamming "missing ARANGO_HOST" errors.
    Fails fast with clear message if config is incomplete.

    Note: ARANGO_ROOT_PASSWORD is only needed on first run (provisioning).
    After first run, credentials are read from config file.
    """
    required_vars = [
        "ARANGO_HOST",
    ]

    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        print("\nRequired for ArangoDB connection:", file=sys.stderr)
        print("  ARANGO_HOST - Database server URL (e.g., http://nomarr-arangodb:8529)", file=sys.stderr)
        print("\nFirst-run only:", file=sys.stderr)
        print("  ARANGO_ROOT_PASSWORD - Root password for initial provisioning", file=sys.stderr)
        sys.exit(1)


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

        # Compute tagger_version dynamically from installed ML models
        # This hash changes when models are updated, triggering re-tagging
        from nomarr.components.ml.ml_discovery_comp import compute_model_suite_hash

        self.tagger_version: str = compute_model_suite_hash(self.models_dir)
        logging.info(f"[Application] Model suite hash (tagger_version): {self.tagger_version}")

        # First-run provisioning (creates DB user and writes credentials)
        self._ensure_database_provisioned()

        # Core dependencies (owned by Application)
        self.db = Database()

        # Ensure schema exists (idempotent - safe on every startup)
        from nomarr.components.platform.arango_bootstrap_comp import ensure_schema

        ensure_schema(self.db.db)
        self.db.ensure_schema_version()

        # Config service for registration
        self._config_service = config_service

        # Services container (DI registry)
        self.services: dict[str, Any] = {}

        # Workers and processing (Phase 2: discovery-based workers)
        # TODO: Implement discovery workers per DISCOVERY_WORKER_REFACTOR.md
        self.worker_system = None  # Placeholder - will be WorkerSystemService

        # Infrastructure
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

    def _ensure_database_provisioned(self) -> None:
        """Ensure database is provisioned before creating Database connection.

        On first run:
        1. Uses ARANGO_ROOT_PASSWORD to connect as root
        2. Creates 'nomarr' database and user with random password
        3. Writes generated password to config file

        After first run:
        - Config file already has credentials, this is a no-op
        """
        from nomarr.components.platform.arango_first_run_comp import (
            get_root_password_from_env,
            is_first_run,
            provision_database_and_user,
            write_db_config,
        )

        config_path = Path("/app/config/nomarr.yaml")
        # Also check local dev path
        if not config_path.exists():
            config_path = Path.cwd() / "config" / "nomarr.yaml"

        hosts = os.getenv("ARANGO_HOST", "http://nomarr-arangodb:8529")

        if not is_first_run(config_path, hosts=hosts):
            logging.debug("Database already provisioned, skipping first-run setup")
            return

        logging.info("First run detected - provisioning database...")

        # Get root password from environment
        root_password = get_root_password_from_env()

        # Provision database and user, get generated app password
        app_password = provision_database_and_user(hosts=hosts, root_password=root_password)

        # Write password to config (uses /app/config/nomarr.yaml in Docker)
        # Note: Host comes from ARANGO_HOST env var, not written to config
        write_db_config(
            config_path=Path("/app/config/nomarr.yaml"),
            password=app_password,
        )

        logging.info("Database provisioned successfully")

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

        # NomarrLogFilter is installed in start.py before handlers are configured

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

        # Initialize services (DI: inject dependencies)
        logging.info("[Application] Initializing services...")

        # Register ML service
        from nomarr.services.infrastructure.ml_svc import MLConfig, MLService

        ml_cfg = MLConfig(
            models_dir=str(self.models_dir),
            cache_idle_timeout=self.cache_idle_timeout,
        )
        ml_service = MLService(cfg=ml_cfg)
        self.register_service("ml", ml_service)

        # Initialize HealthMonitorService for component liveness tracking
        from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorConfig

        health_cfg = HealthMonitorConfig()
        self.health_monitor = HealthMonitorService(cfg=health_cfg, db=self.db)
        self.health_monitor.start()
        self.register_service("health_monitor", self.health_monitor)
        logging.info("[Application] HealthMonitorService started")

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

        # Register Info service (owns GPUHealthMonitor lifecycle)
        from nomarr.services.infrastructure.info_svc import InfoConfig, InfoService

        info_cfg = InfoConfig(
            version="1.2",
            namespace=self.namespace,
            models_dir=str(self.models_dir),
            db=self.db,
            health_monitor=self.health_monitor,
            db_path=self.db_path,
            api_host=self.api_host,
            api_port=self.api_port,
            worker_enabled_default=self.worker_enabled_default,
            tagger_worker_count=self._config_service.get_worker_count("tagger"),
            poll_interval=float(self.worker_poll_interval),
        )
        info_service = InfoService(
            cfg=info_cfg,
            workers_coordinator=self.worker_system,  # Discovery workers (Phase 2)
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
            library_cfg = LibraryServiceConfig(
                namespace=self.namespace,
                tagger_version=self.tagger_version,
                library_root=self.library_root,
            )
            library_service = LibraryService(
                db=self.db,
                cfg=library_cfg,
                background_tasks=background_tasks,
            )
            library_service.ensure_default_library_exists()
            self.register_service("library", library_service)

            # Initialize FileWatcherService for automatic incremental scanning
            # Only start if library service is enabled (requires library_root)
            logging.info("[Application] Initializing FileWatcherService...")
            from nomarr.services.infrastructure.file_watcher_svc import FileWatcherService

            file_watcher = FileWatcherService(
                db=self.db,
                library_service=library_service,
                debounce_seconds=2.0,  # TODO: Make configurable
            )
            self.register_service("file_watcher", file_watcher)

            # Sync watchers with DB (starts watchers for libraries with watch_mode != 'off')
            try:
                file_watcher.sync_watchers()
                logging.info("[Application] File watchers synced with library collection")
            except Exception as e:
                logging.error(f"[Application] Failed to sync file watchers: {e}")
        else:
            logging.info("[Application] No library root configured, library service not started")

        # Register metadata service (entity navigation for hybrid graph)
        from nomarr.services.domain.metadata_svc import MetadataService

        metadata_service = MetadataService(db=self.db)
        self.register_service("metadata", metadata_service)

        # Register tagging service
        self.register_service(
            "tagging",
            TaggingService(
                database=self.db,
                library_service=self.services.get("library"),
            ),
        )

        # Initialize discovery-based WorkerSystemService
        # Per DISCOVERY_WORKER_REFACTOR.md, workers:
        # - Query library_files directly for needs_tagging=1
        # - Claim files atomically via worker_claims collection
        # - Process and update library_files.tagged=1
        logging.info("[Application] Initializing discovery-based worker system...")
        from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

        processor_config = self._config_service.make_processor_config()
        worker_count = self._config_service.get_worker_count("tagger")

        self.worker_system = WorkerSystemService(
            db=self.db,
            processor_config=processor_config,
            worker_count=worker_count,
            default_enabled=self.worker_enabled_default,
        )
        self.register_service("worker_system", self.worker_system)

        # Start workers if enabled
        if self.worker_system.is_worker_system_enabled():
            logging.info("[Application] Starting discovery workers...")
            self.worker_system.start_all_workers()
        else:
            logging.info("[Application] Worker system disabled, not starting workers")

        # Start InfoService (owns GPUHealthMonitor lifecycle)
        logging.info("[Application] Starting InfoService (GPU monitor)...")
        info_service.start()

        # Start app heartbeat thread (Phase 3: DB-based IPC)
        self._running = True
        self._start_app_heartbeat()

        # Mark app as fully healthy after all services/workers started
        self.db.health.mark_healthy(component_id="app")

        logging.info("[Application] Started successfully")

    def stop(self) -> None:
        """
        Stop the application - clean shutdown of all services and workers.

        This replaces the shutdown logic that was in api_app.py:lifespan().
        """
        if not self._running:
            return

        logging.info("[Application] Shutting down...")

        # Stop file watchers first (before stopping services they depend on)
        if "file_watcher" in self.services:
            logging.info("[Application] Stopping file watchers...")
            file_watcher = self.services["file_watcher"]
            file_watcher.stop_all()
            logging.info("[Application] File watchers stopped")

        # Stop worker processes (Phase 2: discovery workers)
        if self.worker_system:
            logging.info("[Application] Stopping worker processes...")
            self.worker_system.stop_all_workers()
            logging.info("[Application] Worker processes stopped")

        # Stop InfoService (owns GPUHealthMonitor)
        if "info" in self.services:
            logging.info("[Application] Stopping InfoService (GPU monitor)...")
            self.services["info"].stop()
            logging.info("[Application] InfoService stopped")

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
