"""Health monitoring components."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.api.application import AppDb
    from nomarr.persistence.db import Database


class HealthComp:
    """Component for health monitoring operations."""

    def __init__(self, db: Database) -> None:
        self.app: AppDb = db.app

    def get_all_workers(self) -> list[dict[str, object]]:
        """Get all registered workers from health monitoring."""
        return self.app.list_worker_health()

    def get_component(self, component: str) -> dict[str, object] | None:
        """Get health status for a specific component."""
        return self.app.get_health(component)
