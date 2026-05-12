"""Health monitoring components."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.api.application import AppDb
    from nomarr.persistence.db import Database


class HealthComp:
    """Component for health monitoring operations."""

    def __init__(self, db: Database) -> None:
        self.app: AppDb = db.app

    def get_all_workers(self) -> list[dict[str, Any]]:
        """Get all registered workers from health monitoring.

        Returns:
            List of worker health records

        """
        return self.app.list_worker_health()

    def get_component(self, component: str) -> dict[str, Any] | None:
        """Get health status for a specific component.

        Args:
            component: Component name (e.g., "worker:library:scan")

        Returns:
            Health record or None if not found

        """
        return self.app.get_health(component)
