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
    from nomarr.services.domain.analytics_svc import AnalyticsService
    from nomarr.services.domain.calibration_svc import CalibrationService
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.domain.metadata_svc import MetadataService
    from nomarr.services.domain.navidrome_svc import NavidromeService
    from nomarr.services.infrastructure.config_svc import ConfigService
    from nomarr.services.infrastructure.queue_svc import QueueService
    from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService


def get_config() -> dict[str, Any]:
    """Get configuration dict from ConfigService."""
    from nomarr.app import application

    config_service = application.get_service("config")
    result = config_service.get_config()
    return result.config  # type: ignore[no-any-return]


def get_queue_service() -> QueueService:
    """Get QueueService instance."""
    from nomarr.app import application

    service = application.services.get("queue")
    if not service:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="Queue service not available")
    return service  # type: ignore[no-any-return]


def get_workers_coordinator() -> WorkerSystemService:
    """Get WorkerSystemService instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("workers")
    if not service:
        raise HTTPException(status_code=503, detail="Worker system not available")
    return service  # type: ignore[no-any-return]


def get_event_broker() -> Any | None:
    """Get EventBroker instance (may be None)."""
    from nomarr.app import application

    return application.event_broker


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


def get_tagging_service() -> Any:
    """Get tagging service instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("tagging")
    if not service:
        raise HTTPException(status_code=503, detail="Tagging service not available")
    return service


def get_info_service() -> Any:
    """Get info service instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("info")
    if not service:
        raise HTTPException(status_code=503, detail="Info service not available")
    return service


def get_events_service():
    """Get EventsService instance (may return None if not available)."""
    from nomarr.app import application
    from nomarr.services.infrastructure.events_svc import EventsService

    # EventsService wraps the event_broker
    return EventsService(application.event_broker)


def get_metadata_service() -> MetadataService:
    """Get MetadataService instance."""
    from fastapi import HTTPException

    from nomarr.app import application

    service = application.services.get("metadata")
    if not service:
        raise HTTPException(status_code=503, detail="Metadata service not available")
    return service  # type: ignore[no-any-return]
