"""Combined router for all web UI endpoints.

This module aggregates all web UI routers (auth, analytics, worker, etc.)
into a single router that can be included in the main FastAPI app.
"""

from fastapi import APIRouter

from nomarr.interfaces.api.web import analytics_if as analytics
from nomarr.interfaces.api.web import auth_if as auth
from nomarr.interfaces.api.web import calibration_if as calibration
from nomarr.interfaces.api.web import config_if as config
from nomarr.interfaces.api.web import fs_if as fs
from nomarr.interfaces.api.web import info_if as info
from nomarr.interfaces.api.web import library_if as library
from nomarr.interfaces.api.web import metadata_if as metadata
from nomarr.interfaces.api.web import navidrome_if as navidrome
from nomarr.interfaces.api.web import playlist_import_if as playlist_import
from nomarr.interfaces.api.web import processing_if as processing
from nomarr.interfaces.api.web import tags_if as tags
from nomarr.interfaces.api.web import vectors_if as vectors
from nomarr.interfaces.api.web import worker_if as worker

# Create combined router with /api/web prefix for all browser-facing endpoints
router = APIRouter(prefix="/api/web")

# Include all web UI routers
router.include_router(auth.router)
router.include_router(analytics.router)
router.include_router(calibration.router)
router.include_router(config.router)
router.include_router(fs.router)
router.include_router(info.router)
router.include_router(library.router)
router.include_router(metadata.router)
router.include_router(navidrome.router)
router.include_router(playlist_import.router)
router.include_router(processing.router)
router.include_router(tags.router)
router.include_router(vectors.router)
router.include_router(worker.router)
