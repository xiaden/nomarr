"""
FastAPI dependency injection helpers for web endpoints.

These functions provide clean dependency injection for services,
replacing the old get_state() service locator pattern.

ARCHITECTURE:
- Endpoints should ONLY inject services, never Database or raw infrastructure
- Services encapsulate all business logic and data access
- Endpoints are thin presentation layers that call services and format responses
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.services.analytics_service import AnalyticsService
    from nomarr.services.calibration_service import CalibrationService
    from nomarr.services.config_service import ConfigService
    from nomarr.services.coordinator_service import CoordinatorService
    from nomarr.services.library_service import LibraryService
    from nomarr.services.navidrome_service import NavidromeService
    from nomarr.services.queue_service import QueueService
    from nomarr.services.worker_service import WorkerService


def get_config() -> dict[str, Any]:
    """Get configuration dict from ConfigService."""
    from nomarr.app import application

    config_service = application.get_service("config")
    return config_service.get_config()  # type: ignore[no-any-return]


def get_queue_service() -> QueueService:
    """Get QueueService instance."""
    from nomarr.app import application

    service = application.services.get("queue")
    if not service:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="Queue service not available")
    return service  # type: ignore[no-any-return]


def get_worker_service() -> WorkerService:
    """Get WorkerService instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("worker")
    if service is None:
        raise HTTPException(status_code=503, detail="Worker service not available")
    return service  # type: ignore[no-any-return]


def get_processor_coordinator() -> CoordinatorService | None:
    """Get CoordinatorService instance (may be None)."""
    from nomarr.app import application

    return application.coordinator


def get_event_broker() -> Any | None:
    """Get EventBroker instance (may be None)."""
    from nomarr.app import application

    return application.event_broker


def get_worker_pool() -> list[Any]:
    """Get worker pool list."""
    from nomarr.app import application

    return application.workers


def get_library_service() -> LibraryService:
    """Get LibraryService instance."""
    from nomarr.app import application

    service = application.services.get("library")
    if not service:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="Library service not available")
    return service  # type: ignore[no-any-return]


def get_analytics_service() -> AnalyticsService:
    """Get AnalyticsService instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("analytics")
    if not service:
        raise HTTPException(status_code=503, detail="Analytics service not available")
    return service  # type: ignore[no-any-return]


def get_calibration_service() -> CalibrationService:
    """Get CalibrationService instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("calibration")
    if not service:
        raise HTTPException(status_code=503, detail="Calibration service not available")
    return service  # type: ignore[no-any-return]


def get_config_service() -> ConfigService:
    """Get ConfigService instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("config")
    if not service:
        raise HTTPException(status_code=503, detail="Config service not available")
    return service  # type: ignore[no-any-return]


def get_navidrome_service() -> NavidromeService:
    """Get NavidromeService instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("navidrome")
    if not service:
        raise HTTPException(status_code=503, detail="Navidrome service not available")
    return service  # type: ignore[no-any-return]


def get_ml_service() -> Any:
    """Get ML service instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("ml")
    if not service:
        raise HTTPException(status_code=503, detail="ML service not available")
    return service


def get_recalibration_service() -> Any:
    """Get recalibration service instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("recalibration")
    if not service:
        raise HTTPException(status_code=503, detail="Recalibration service not available")
    return service
