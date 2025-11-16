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

from nomarr.app import application
from nomarr.interfaces.api.endpoints import admin, library, public, web

# ----------------------------------------------------------------------
#  Configuration (imported from state module)
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Startup informational log
logging.info(
    "Effective config: models_dir=%s db_path=%s api=%s:%s blocking_mode=%s "
    "blocking_timeout=%s worker_poll_interval=%s worker_count=%s",
    application.models_dir,
    application.db_path,
    application.api_host,
    application.api_port,
    application.blocking_mode,
    application.blocking_timeout,
    application.worker_poll_interval,
    application.worker_count,
)


# ----------------------------------------------------------------------
#  App lifecycle
# ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app_instance: FastAPI):
    """
    FastAPI lifespan context manager.

    Note: Application.start() is called by start.py BEFORE uvicorn runs.
    This lifespan is minimal - just handles cleanup on API shutdown.
    """
    # Application already started by start.py
    logging.info("[API] FastAPI starting (Application already initialized)")

    yield

    # Shutdown: Stop the application
    logging.info("[API] FastAPI shutting down...")
    application.stop()
    logging.info("[API] Shutdown complete")


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

    logging.info(f"[API] Web UI enabled at http://{application.api_host}:{application.api_port}/")
else:
    logging.warning("[API] Web UI directory not found, dashboard disabled")
