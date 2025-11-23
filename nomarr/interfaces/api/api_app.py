"""
FastAPI application setup and configuration.
Main entry point for the Nomarr API service.

Architecture:
- Two API realms:
  - /api/v1 (integration APIs using API key auth)
  - /api/web (web UI APIs using session auth)
- All routes must be under one of these two prefixes
- No bare paths that don't start with /api
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from nomarr.interfaces.api import web  # Web UI router
from nomarr.interfaces.api.endpoints import admin, public


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
    # Import application only when lifespan runs (not at module import time)
    from nomarr.app import application

    logging.info("[API] FastAPI starting (Application already initialized)")

    try:
        yield
    finally:
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
#  API Realms - Two top-level routers
# ----------------------------------------------------------------------

# Integration APIs (API key auth) - /api/v1 prefix
# Public and admin routers define their own sub-paths under /v1
integration_router = APIRouter(prefix="/api")
integration_router.include_router(public.router, tags=["Integration: Public"])
integration_router.include_router(admin.router, tags=["Integration: Admin"])

# Web UI APIs (session auth) - /api/web prefix
# Web router already has /api/web prefix configured in web/router.py
api_app.include_router(integration_router)
api_app.include_router(web.router)

# ----------------------------------------------------------------------
#  Static files (Web UI)
# ----------------------------------------------------------------------
public_html_dir = Path(__file__).parent.parent / "public_html"
if public_html_dir.exists():
    # Serve static assets (JS, CSS, images) from /assets/
    assets_dir = public_html_dir / "assets"
    if assets_dir.exists():
        api_app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @api_app.get("/")
    async def serve_dashboard():
        """Serve the web dashboard SPA."""
        index_path = public_html_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return JSONResponse({"error": "Web UI not found"}, status_code=404)
