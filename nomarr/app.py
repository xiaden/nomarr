"""Application composition root and dependency injection container.

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
from typing import Any

from nomarr.persistence.db import Database
from nomarr.services.domain.analytics_svc import AnalyticsService
from nomarr.services.domain.calibration_svc import CalibrationService
from nomarr.services.domain.library_svc import LibraryService, LibraryServiceConfig
from nomarr.services.domain.navidrome_svc import NavidromeService
from nomarr.services.domain.playlist_import_svc import PlaylistImportConfig, PlaylistImportService
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig
from nomarr.services.infrastructure.config_svc import ConfigService
from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorService
from nomarr.services.infrastructure.keys_svc import KeyManagementService
from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

logger = logging.getLogger(__name__)


def validate_environment() -> None:
    """Validate required environment variables at startup.

    Prevents workers from each spamming "missing ARANGO_HOST" errors.
    Fails fast with clear message if config is incomplete.

    Note: ARANGO_ROOT_PASSWORD is only needed on first run (provisioning).
    After first run, credentials are read from config file.
    """
    required_vars = ["ARANGO_HOST"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        sys.exit(1)


class Application:
    """Application composition root and dependency injection container.

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

    def __init__(self) -> None:
        """Initialize application with core dependencies.

        Loads configuration and creates database and queue immediately.
        Services are initialized later during start().
        """
        validate_environment()
        config_service = ConfigService()
        self._config = config_service.get_config().config
        from nomarr.services.infrastructure.config_svc import (
            INTERNAL_HOST,
            INTERNAL_LIBRARY_SCAN_POLL_INTERVAL,
            INTERNAL_NAMESPACE,
            INTERNAL_POLL_INTERVAL,
            INTERNAL_PORT,
            INTERNAL_VERSION_TAG,
            INTERNAL_WORKER_ENABLED,
        )

        self.db_path: str = str(self._config["db_path"])
        self.library_root: str | None = self._config.get("library_root")
        self.models_dir: str = str(self._config.get("models_dir", "/app/models"))
        self.cache_idle_timeout: int = int(self._config.get("cache_idle_timeout", 300))
        self.calibrate_heads: bool = bool(self._config.get("calibrate_heads", False))
        self.library_auto_tag: bool = bool(self._config.get("library_auto_tag", False))
        self.library_ignore_patterns: str = str(self._config.get("library_ignore_patterns", ""))
        self.admin_password_config: str | None = self._config.get("admin_password")
        self.api_host: str = INTERNAL_HOST
        self.api_port: int = INTERNAL_PORT
        self.worker_enabled_default: bool = INTERNAL_WORKER_ENABLED
        self.worker_poll_interval: int = INTERNAL_POLL_INTERVAL
        self.library_scan_poll_interval: int = INTERNAL_LIBRARY_SCAN_POLL_INTERVAL
        self.namespace: str = INTERNAL_NAMESPACE
        self.version_tag_key: str = INTERNAL_VERSION_TAG
        from nomarr.components.ml.ml_discovery_comp import compute_model_suite_hash

        self.tagger_version: str = compute_model_suite_hash(self.models_dir)
        logger.info(f"[Application] Model suite hash (tagger_version): {self.tagger_version}")
        self._ensure_database_provisioned()
        self.db = Database()
        from nomarr.components.platform.arango_bootstrap_comp import ensure_schema

        ensure_schema(self.db.db)
        self.db.ensure_schema_version()
        self._config_service = config_service
        self.services: dict[str, Any] = {}
        self.worker_system: WorkerSystemService | None = None
        self.health_monitor: HealthMonitorService | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self.api_key: str | None = None
        self.admin_password: str | None = None
        self._running = False

    def register_service(self, name: str, service: Any) -> None:
        """Register a service in the DI container.

        Args:
            name: Service name for lookup
            service: Service instance

        """
        self.services[name] = service

    def get_service(self, name: str) -> Any:
        """Get a service from the DI container.

        Args:
            name: Service name

        Returns:
            Service instance

        Raises:
            KeyError: If service not found

        """
        if name not in self.services:
            msg = f"Service '{name}' not found. Available services: {list(self.services.keys())}"
            raise KeyError(msg)
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
            _wait_for_arango,
            get_root_password_from_env,
            is_first_run,
            provision_database_and_user,
            write_db_config,
        )

        config_path = Path("/app/config/nomarr.yaml")
        if not config_path.exists():
            config_path = Path.cwd() / "config" / "nomarr.yaml"
        hosts = os.getenv("ARANGO_HOST", "http://nomarr-arangodb:8529")
        if not _wait_for_arango(hosts):
            msg = f"Cannot connect to ArangoDB at {hosts} after 60 seconds"
            raise RuntimeError(msg)
        if not is_first_run(config_path, hosts=hosts):
            logger.debug("Database already provisioned, skipping first-run setup")
            return
        logger.info("First run detected - provisioning database...")
        root_password = get_root_password_from_env()
        app_password = provision_database_and_user(hosts=hosts, root_password=root_password)
        write_db_config(config_path=config_path, password=app_password)
        logger.info("Database provisioned successfully")

    def _start_app_heartbeat(self) -> None:
        """Start background thread to write app heartbeat (Phase 3: DB-based IPC)."""
        from nomarr.persistence.db import Database

        def heartbeat_loop() -> None:
            heartbeat_db = Database()
            while self._running:
                try:
                    heartbeat_db.health.update_heartbeat(component_id="app", status="healthy")
                except Exception as e:
                    logger.exception(f"[Application] Heartbeat error: {e}")
                time.sleep(5)
            heartbeat_db.close()

        self._heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True, name="AppHeartbeat")
        self._heartbeat_thread.start()
        logger.info("[Application] App heartbeat started")

    def start(self) -> None:
        """Start the application - initialize all services, workers, and background tasks.

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
            logger.warning("[Application] Already running, ignoring start() call")
            return
        logger.info("[Application] Starting...")
        logger.info("[Application] Cleaning ephemeral runtime state...")
        self.db.health.clean_all()
        self.db.health.mark_starting(component_id="app", component_type="app")
        logger.info("[Application] Initializing authentication...")
        key_service = KeyManagementService(self.db)
        self.api_key = key_service.get_or_create_api_key()
        self.admin_password = key_service.get_or_create_admin_password(self.admin_password_config)
        key_service.load_sessions_from_db()
        self.register_service("keys", key_service)
        self.register_service("config", self._config_service)
        logger.info("[Application] Initializing services...")
        from nomarr.services.infrastructure.ml_svc import MLConfig, MLService

        ml_cfg = MLConfig(models_dir=str(self.models_dir), cache_idle_timeout=self.cache_idle_timeout)
        ml_service = MLService(cfg=ml_cfg)
        self.register_service("ml", ml_service)
        from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorConfig

        health_cfg = HealthMonitorConfig()
        self.health_monitor = HealthMonitorService(cfg=health_cfg, db=self.db)
        self.health_monitor.start()
        self.register_service("health_monitor", self.health_monitor)
        logger.info("[Application] HealthMonitorService started")
        logger.info("[Application] Initializing AnalyticsService...")
        from nomarr.services.domain.analytics_svc import AnalyticsConfig

        analytics_cfg = AnalyticsConfig(namespace=self.namespace)
        analytics_service = AnalyticsService(db=self.db, cfg=analytics_cfg)
        self.register_service("analytics", analytics_service)
        logger.info("[Application] Initializing CalibrationService...")
        from nomarr.services.domain.calibration_svc import CalibrationConfig

        calibration_cfg = CalibrationConfig(models_dir=str(self.models_dir), namespace=self.namespace)
        calibration_service = CalibrationService(db=self.db, cfg=calibration_cfg)
        self.register_service("calibration", calibration_service)
        logger.info("[Application] Initializing NavidromeService...")
        from nomarr.services.domain.navidrome_svc import NavidromeConfig

        navidrome_cfg = NavidromeConfig(namespace=self.namespace)
        navidrome_service = NavidromeService(db=self.db, cfg=navidrome_cfg)
        self.register_service("navidrome", navidrome_service)
        logger.info("[Application] Initializing PlaylistImportService...")
        playlist_import_cfg = PlaylistImportConfig(
            spotify_client_id=self._config.get("spotify_client_id"),
            spotify_client_secret=self._config.get("spotify_client_secret"),
        )
        playlist_import_service = PlaylistImportService(db=self.db, cfg=playlist_import_cfg)
        self.register_service("playlist_import", playlist_import_service)
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
        info_service = InfoService(cfg=info_cfg, workers_coordinator=self.worker_system, ml_service=ml_service)
        self.register_service("info", info_service)
        from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService

        background_tasks = BackgroundTaskService()
        self.register_service("background_tasks", background_tasks)
        if self.library_root:
            logger.info(f"[Application] Registering LibraryService with namespace={self.namespace}")
            library_cfg = LibraryServiceConfig(
                models_dir=str(self.models_dir),
                namespace=self.namespace,
                tagger_version=self.tagger_version,
                library_root=self.library_root,
            )
            library_service = LibraryService(cfg=library_cfg, db=self.db, background_tasks=background_tasks)
            self.register_service("library", library_service)
            logger.info("[Application] Initializing FileWatcherService...")
            from nomarr.services.infrastructure.file_watcher_svc import FileWatcherService

            file_watcher = FileWatcherService(db=self.db, library_service=library_service, debounce_seconds=2.0)
            self.register_service("file_watcher", file_watcher)

            # Sync watchers in background - observer.start() traverses the entire
            # directory tree to register inotify watches, which blocks for large libraries.
            # Nothing downstream depends on watchers being active at startup.
            import threading

            def _sync_watchers_bg() -> None:
                try:
                    file_watcher.sync_watchers()
                    logger.info("[Application] File watchers synced with library collection")
                except Exception:
                    logger.exception("[Application] Failed to sync file watchers")

            threading.Thread(target=_sync_watchers_bg, name="file-watcher-sync", daemon=True).start()
        else:
            logger.info("[Application] No library root configured, library service not started")
        from nomarr.services.domain.metadata_svc import MetadataService

        metadata_service = MetadataService(db=self.db)
        self.register_service("metadata", metadata_service)
        self.register_service("tagging", TaggingService(
            database=self.db,
            cfg=TaggingServiceConfig(
                models_dir=self.models_dir,
                namespace=self.namespace,
                version_tag_key=self.version_tag_key,
                calibrate_heads=self.calibrate_heads,
            ),
            library_service=self.services.get("library"),
        ))
        logger.info("[Application] Initializing discovery-based worker system...")
        processor_config = self._config_service.make_processor_config()
        worker_count = self._config_service.get_worker_count("tagger")
        self.worker_system = WorkerSystemService(
            db=self.db,
            processor_config=processor_config,
            health_monitor=self.health_monitor,
            worker_count=worker_count,
            default_enabled=self.worker_enabled_default,
        )
        self.register_service("worker_system", self.worker_system)
        if self.worker_system.is_worker_system_enabled():
            logger.info("[Application] Starting discovery workers...")
            self.worker_system.start_all_workers()
        else:
            logger.info("[Application] Worker system disabled, not starting workers")
        logger.info("[Application] Starting InfoService (GPU monitor)...")
        info_service.start()
        self._running = True
        self._start_app_heartbeat()
        self.db.health.mark_healthy(component_id="app")
        logger.info("[Application] Started successfully")

    def stop(self) -> None:
        """Stop the application - clean shutdown of all services and workers.

        This replaces the shutdown logic that was in api_app.py:lifespan().
        """
        if not self._running:
            return
        logger.info("[Application] Shutting down...")
        if "file_watcher" in self.services:
            logger.info("[Application] Stopping file watchers...")
            file_watcher = self.services["file_watcher"]
            file_watcher.stop_all()
            logger.info("[Application] File watchers stopped")
        if self.worker_system:
            logger.info("[Application] Stopping worker processes...")
            self.worker_system.stop_all_workers()
            logger.info("[Application] Worker processes stopped")
        if "info" in self.services:
            logger.info("[Application] Stopping InfoService (GPU monitor)...")
            self.services["info"].stop()
            logger.info("[Application] InfoService stopped")
        if hasattr(self, "health_monitor") and self.health_monitor:
            logger.info("[Application] Stopping health monitor...")
            self.health_monitor.stop()
        try:
            self.db.health.mark_stopping(component_id="app", exit_code=0)
            logger.info("[Application] Cleaning ephemeral runtime state...")
            self.db.health.clean_all()
        except Exception as e:
            logger.warning(f"[Application] DB unavailable during shutdown (expected if containers stopping): {e}")
        self._running = False
        logger.info("[Application] Shutdown complete - all workers stopped")

    def is_running(self) -> bool:
        """Check if application is running."""
        return self._running

    def warmup_cache(self) -> None:
        """Warmup the ML predictor cache.

        Interfaces should call this method rather than importing ml.cache directly.
        Uses instance config attributes.
        """
        ml_service = self.services.get("ml")
        if ml_service is None:
            msg = "ML service not initialized"
            raise RuntimeError(msg)
        ml_service.warmup_cache()


# Module-level singleton, initialized at import time (except during tests)
# Type is Application at runtime, None only during pytest
application: Application
if os.environ.get("PYTEST_CURRENT_TEST") is None:
    application = Application()
else:
    application = None  # type: ignore[assignment]  # Tests don't use the singleton
