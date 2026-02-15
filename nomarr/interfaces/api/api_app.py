"""FastAPI application setup and configuration.
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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app_instance: FastAPI):
    """FastAPI lifespan context manager.

    Note: Application.start() is called by start.py BEFORE uvicorn runs.
    This lifespan is minimal - just handles cleanup on API shutdown.
    """
    from nomarr.app import application

    logger.info("[API] FastAPI starting (Application already initialized)")
    try:
        yield
    finally:
        logger.info("[API] FastAPI shutting down...")
        application.stop()
        logger.info("[API] Shutdown complete")


api_app = FastAPI(title="Nomarr", version="1.2", lifespan=lifespan)


@api_app.exception_handler(Exception)
async def exception_handler(request, exc: Exception):
    logger.exception(f"[API] Exception: {exc}")
    return JSONResponse(status_code=500, content={"error": str(exc)})


integration_router = APIRouter(prefix="/api")
integration_router.include_router(public_if.router, tags=["Integration: Public"])
integration_router.include_router(admin_if.router, tags=["Integration: Admin"])


api_app.include_router(integration_router)
api_app.include_router(web.router)
public_html_dir = Path(nomarr.__file__).parent / "public_html"


@api_app.get("/info")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "service": "nomarr", "version": nomarr.__version__}


@api_app.get("/")
async def serve_dashboard():
    """Serve the web dashboard SPA."""
    index_path = public_html_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"error": f"Web UI not found at {index_path}"}, status_code=404)


assets_dir = public_html_dir / "assets"
if assets_dir.exists():
    api_app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@api_app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Catch-all route for SPA routing.

    Serves index.html for all paths that aren't API endpoints or static assets.
    This allows client-side React Router to handle routing.
    """
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    index_path = public_html_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"error": f"Web UI not found at {index_path}"}, status_code=404)
