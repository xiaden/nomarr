"""Web UI API router aggregator."""

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

# Create main web router with /web prefix
router = APIRouter(prefix="/web", tags=["Web UI"])

# Include all sub-routers
router.include_router(auth.router)  # /web/auth/*
router.include_router(processing.router)  # /web/api/process, batch-process, list
router.include_router(queue.router)  # /web/api/status, queue-depth, admin/*
router.include_router(worker.router)  # /web/api/admin/worker/*, admin/restart
router.include_router(tags.router)  # /web/api/show-tags
router.include_router(info.router)  # /web/api/info, health
router.include_router(analytics.router)  # /web/api/analytics/*
router.include_router(library.router)  # /web/api/library/*
router.include_router(calibration.router)  # /web/api/calibration/*
router.include_router(config.router)  # /web/api/config
router.include_router(navidrome.router)  # /web/api/navidrome/*
router.include_router(sse.router)  # /web/events/status

__all__ = ["router"]
