"""Health monitoring components."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_all_workers(db: Database) -> list[dict[str, Any]]:
    """
    Get all registered workers from health monitoring.

    Returns:
        List of worker health records
    """
    return db.health.get_all_workers()


def get_component_health(db: Database, component: str) -> dict[str, Any] | None:
    """
    Get health status for a specific component.

    Args:
        db: Database instance
        component: Component name (e.g., "worker:library:scan")

    Returns:
        Health record or None if not found
    """
    return db.health.get_component(component)
