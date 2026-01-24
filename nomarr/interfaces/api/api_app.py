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

import nomarr
from nomarr.interfaces.api import web
from nomarr.interfaces.api.v1 import admin_if, public_if


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
integration_router.include_router(public_if.router, tags=["Integration: Public"])
integration_router.include_router(admin_if.router, tags=["Integration: Admin"])

# Web UI APIs (session auth) - /api/web prefix
# Web router already has /api/web prefix configured in web/router.py
api_app.include_router(integration_router)
api_app.include_router(web.router)

# ----------------------------------------------------------------------
#  Static files (Web UI)
# ----------------------------------------------------------------------
# Use package-relative import to find public_html directory
# This file is at: nomarr/interfaces/api/api_app.py
# We want: nomarr/public_html/

public_html_dir = Path(nomarr.__file__).parent / "public_html"


# Health check endpoint (for Docker/monitoring)
@api_app.get("/info")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "service": "nomarr", "version": nomarr.__version__}


# Serve static assets (JS, CSS, images) from /assets/
@api_app.get("/")
async def serve_dashboard():
    """Serve the web dashboard SPA."""
    index_path = public_html_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"error": f"Web UI not found at {index_path}"}, status_code=404)


# Mount static assets directory
assets_dir = public_html_dir / "assets"
if assets_dir.exists():
    api_app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


# Catch-all route for SPA - serve index.html for all non-API routes
# This must be last so it doesn't catch API routes
@api_app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """
    Catch-all route for SPA routing.

    Serves index.html for all paths that aren't API endpoints or static assets.
    This allows client-side React Router to handle routing.
    """
    # Don't catch API routes (already handled above)
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    index_path = public_html_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"error": f"Web UI not found at {index_path}"}, status_code=404)
