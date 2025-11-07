"""
FastAPI application setup and configuration.
Main entry point for the Nomarr API service.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import nomarr.app as app
from nomarr.interfaces.api.endpoints import admin, internal, library, public, web
from nomarr.interfaces.api.event_broker import StateBroker
from nomarr.ml.cache import warmup_predictor_cache
from nomarr.services.workers.scanner import LibraryScanWorker

# ----------------------------------------------------------------------
#  Configuration (imported from state module)
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Startup informational log
logging.info(
    "Effective config: models_dir=%s db_path=%s api=%s:%s blocking_mode=%s "
    "blocking_timeout=%s worker_poll_interval=%s worker_count=%s",
    app.cfg.get("paths", {}).get("models_dir"),
    app.DB_PATH,
    app.API_HOST,
    app.API_PORT,
    app.BLOCKING_MODE,
    app.BLOCKING_TIMEOUT,
    app.WORKER_POLL_INTERVAL,
    app.WORKER_COUNT,
)


# ----------------------------------------------------------------------
#  App lifecycle
# ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    # Startup: cleanup orphaned jobs and start process pool coordinator
    logging.info("[API] Checking for orphaned 'running' jobs from previous sessions...")
    reset_count = app.queue.reset_running_to_pending()
    if reset_count > 0:
        logging.info(f"[API] Reset {reset_count} orphaned job(s) from 'running' to 'pending'")

    # Reset any stuck library scans
    logging.info("[API] Checking for stuck 'running' library scans...")
    scan_reset_count = app.db.reset_running_library_scans()
    if scan_reset_count > 0:
        logging.info(f"[API] Reset {scan_reset_count} stuck library scan(s) from 'running' to 'pending'")

    # Initialize API keys
    logging.info("[API] Initializing API keys and admin password...")
    from nomarr.services.keys import KeyManagementService

    app.key_service = KeyManagementService(app.db)
    app.API_KEY = app.key_service.get_or_create_api_key()
    app.INTERNAL_KEY = app.key_service.get_or_create_internal_key()
    app.ADMIN_PASSWORD_PLAINTEXT = app.key_service.get_or_create_admin_password(app.cfg.get("admin_password"))

    # Load sessions from database into memory cache
    logging.info("[API] Loading sessions from database...")
    app.key_service.load_sessions_from_db()

    # Initialize event broker
    logging.info("[API] Initializing SSE state broker...")
    app.event_broker = StateBroker()

    logging.info(f"[API] Starting ProcessingCoordinator with {app.WORKER_COUNT} workers...")
    app.processor_coord = app.ProcessingCoordinator(num_workers=app.WORKER_COUNT, event_broker=app.event_broker)
    app.processor_coord.start()

    # Initialize ProcessingService with the coordinator
    from nomarr.services.processing import ProcessingService

    app.processing_service = ProcessingService(coordinator=app.processor_coord)
    logging.info("[API] ProcessingService initialized")

    # Initialize WorkerService
    from nomarr.services.worker import WorkerService

    app.worker_service = WorkerService(
        db=app.db,
        queue=app.queue,
        processor_coord=app.processor_coord,
        default_enabled=app.WORKER_ENABLED_DEFAULT,
    )
    logging.info("[API] WorkerService initialized")

    # Warm up predictor cache
    logging.info("[API] Warming up predictor cache...")
    try:
        warmup_predictor_cache()
        logging.info("[API] Predictor cache warmed successfully")
    except Exception as e:
        logging.error(f"[API] Failed to warm predictor cache: {e}")

    # Start workers if enabled via WorkerService
    if app.worker_service and app.worker_service.is_enabled():
        app.worker_pool = app.worker_service.start_workers(event_broker=app.event_broker)
    else:
        logging.info("[Worker] Not started (worker_enabled=false)")

    # Start library scan worker if library_path is configured
    if app.LIBRARY_PATH:
        logging.info(f"[LibraryScanWorker] Starting with library_path={app.LIBRARY_PATH}")
        app.library_scan_worker = LibraryScanWorker(
            db=app.db,
            library_path=app.LIBRARY_PATH,
            namespace=app.cfg.get("namespace", "essentia"),
            poll_interval=app.LIBRARY_SCAN_POLL_INTERVAL,
        )
        app.library_scan_worker.start()

        # Initialize LibraryService with the worker
        from nomarr.services.library import LibraryService

        app.library_service = LibraryService(
            db=app.db,
            library_path=app.LIBRARY_PATH,
            worker=app.library_scan_worker,
        )
        logging.info("[API] LibraryService initialized")
    else:
        logging.info("[LibraryScanWorker] Not started (no library_path configured)")

    # Start health monitor for all workers
    from nomarr.services.health_monitor import HealthMonitor

    app.health_monitor = HealthMonitor(check_interval=10)

    # Register tagger workers with cleanup callback
    def cleanup_orphaned_jobs():
        """Callback to cleanup orphaned jobs when tagger workers die."""
        if app.worker_service:
            app.worker_service.cleanup_orphaned_jobs()

    for worker in app.worker_pool:
        app.health_monitor.register_worker(worker, on_death=cleanup_orphaned_jobs)

    # Register library scan worker (no cleanup needed)
    if app.library_scan_worker:
        app.health_monitor.register_worker(app.library_scan_worker, name="LibraryScanWorker")

    app.health_monitor.start()

    yield

    # Shutdown
    logging.info("[API] Shutting down gracefully...")

    # Stop health monitor
    if app.health_monitor:
        app.health_monitor.stop()

    # Shutdown ProcessingService
    if app.processing_service:
        app.processing_service.shutdown()

    # Stop coordinator
    if app.processor_coord:
        app.processor_coord.stop()

    # Stop library scan worker
    if app.library_scan_worker:
        app.library_scan_worker.stop()

    # Stop all workers
    for worker in app.worker_pool:
        worker.stop()
    for worker in app.worker_pool:
        if worker.is_alive():
            worker.join(timeout=10)

    app.queue.flush()
    app.db.close()


# ----------------------------------------------------------------------
#  FastAPI app
# ----------------------------------------------------------------------
api_app = FastAPI(title="Nomarr", version="1.2", lifespan=lifespan)


# Global exception handler
@api_app.exception_handler(Exception)
async def exception_handler(request, exc: Exception):
    logging.exception(f"[API] Exception: {exc}")
    return JSONResponse(status_code=500, content={"error": str(exc)})


# ----------------------------------------------------------------------
#  Include routers
# ----------------------------------------------------------------------
api_app.include_router(public.router)
api_app.include_router(admin.router)
api_app.include_router(internal.router)
api_app.include_router(web.router)  # Web UI auth + proxy + analytics endpoints
api_app.include_router(library.router)  # Library scan endpoints

# ----------------------------------------------------------------------
#  Static files (Web UI)
# ----------------------------------------------------------------------
web_dir = Path(__file__).parent.parent / "web"
if web_dir.exists():
    api_app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

    @api_app.get("/")
    async def serve_dashboard():
        """Serve the web dashboard."""
        index_path = web_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return JSONResponse({"error": "Web UI not found"}, status_code=404)

    logging.info(f"[API] Web UI enabled at http://{app.API_HOST}:{app.API_PORT}/")
else:
    logging.warning("[API] Web UI directory not found, dashboard disabled")
