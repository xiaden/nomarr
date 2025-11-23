"""
Combined router for all web UI endpoints.

This module aggregates all web UI routers (auth, analytics, queue, worker, etc.)
into a single router that can be included in the main FastAPI app.
"""

from fastapi import APIRouter

from nomarr.interfaces.api.web import (
    analytics,
    auth,
    calibration,
    config,
    info,
    library,
    navidrome,
    processing,
    queue,
    sse,
    tags,
    worker,
)

# Create combined router
router = APIRouter()

# Include all web UI routers
router.include_router(auth.router)
router.include_router(analytics.router)
router.include_router(calibration.router)
router.include_router(config.router)
router.include_router(info.router)
router.include_router(library.router)
router.include_router(navidrome.router)
router.include_router(processing.router)
router.include_router(queue.router)
router.include_router(sse.router)
router.include_router(tags.router)
router.include_router(worker.router)
