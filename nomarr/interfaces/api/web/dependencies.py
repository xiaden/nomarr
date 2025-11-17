"""
FastAPI dependency injection helpers for web endpoints.

These functions provide clean dependency injection for services and infrastructure,
replacing the old get_state() service locator pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.coordinator import ProcessingCoordinator
    from nomarr.services.queue import QueueService


def get_database() -> Database:
    """Get Database instance."""
    from nomarr.app import application

    return application.db


def get_queue() -> Any:
    """Get ProcessingQueue instance."""
    from nomarr.app import application

    return application.queue


def get_config() -> dict[str, Any]:
    """Get configuration dict."""
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


def get_worker_service() -> Any | None:
    """Get WorkerService instance (may be None)."""
    from nomarr.app import application

    return application.services.get("worker")


def get_processor_coordinator() -> ProcessingCoordinator | None:
    """Get ProcessingCoordinator instance (may be None)."""
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
