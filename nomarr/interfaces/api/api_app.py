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
from nomarr.helpers.exceptions import FilesystemError
from nomarr.interfaces.api import web
from nomarr.interfaces.api.v1 import navidrome_v1_if, public_if

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app_instance: FastAPI):
    """FastAPI lifespan context manager.

    Note: Application.start() is called by start.py BEFORE uvicorn runs.
    This lifespan is minimal - just handles cleanup on API shutdown.
    """
    from nomarr.app import application

    logger.info("[API] Serving at http://%s:%d/", application.api_host, application.api_port)
    try:
        yield
    finally:
        logger.info("[API] FastAPI shutting down...")
        application.stop()
        logger.info("[API] Shutdown complete")


api_app = FastAPI(title="Nomarr", version="1.2", lifespan=lifespan)


@api_app.exception_handler(Exception)
async def exception_handler(_request, exc: Exception):
    logger.error(f"[API] Exception: {exc}", exc_info=exc)
    return JSONResponse(status_code=500, content={"error": str(exc)})


# D-B10: fail-closed kind -> HTTP status. Unknown kinds fall through to 500.
_FILESYSTEM_ERROR_STATUS: dict[str, int] = {
    "resource_missing": 404,
    "unconfirmed_missing": 503,
    "permission_denied": 403,
    "storage_unavailable": 503,
    "transient_io": 503,
    "storage_full": 507,
    "read_only_fs": 403,
    "invalid_path": 400,
    "wrong_resource_type": 400,
    "unknown": 500,
}

_FILESYSTEM_ERROR_MESSAGES: dict[str, str] = {
    "resource_missing": "The requested resource could not be found.",
    "unconfirmed_missing": "The resource is temporarily unavailable. Please try again.",
    "permission_denied": "You do not have permission to access this resource.",
    "storage_unavailable": "The storage backing this resource is unavailable. Please try again.",
    "transient_io": "A temporary filesystem error occurred. Please try again.",
    "storage_full": "The storage is full and cannot accept the operation.",
    "read_only_fs": "The file system is read-only and cannot accept the operation.",
    "invalid_path": "The supplied path is invalid.",
    "wrong_resource_type": "The resource is not the expected type.",
    "unknown": "An unexpected filesystem error occurred.",
}


@api_app.exception_handler(FilesystemError)
async def filesystem_error_handler(_request, exc: FilesystemError):
    """Map a typed filesystem failure to a safe status and generic client message (D-B10).

    The client never sees ``str(exc)``, the path, or the raw ``errno``; those are
    logged server-side only. Unrecognised kinds fail closed to 500.
    """
    fact = exc.fact
    kind = fact.kind or "unknown"
    logger.error(
        "[API] Filesystem error: presence=%s kind=%s errno=%s detail=%s",
        fact.presence,
        fact.kind,
        fact.errno,
        fact.detail,
    )
    status_code = _FILESYSTEM_ERROR_STATUS.get(kind, 500)
    message = _FILESYSTEM_ERROR_MESSAGES.get(kind, _FILESYSTEM_ERROR_MESSAGES["unknown"])
    return JSONResponse(status_code=status_code, content={"error": message})


integration_router = APIRouter(prefix="/api")
integration_router.include_router(public_if.router, tags=["Integration: Public"])
integration_router.include_router(navidrome_v1_if.router, tags=["Integration: Navidrome"])


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
