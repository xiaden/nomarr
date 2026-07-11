"""Health monitoring components."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class HealthComp:
    """Component for health monitoring operations.

    Thin wrapper around db.app for backward compatibility with
    services that import HealthComp directly. Preferred API for new
    callers are the module-level functions get_all_workers() and
    get_component(), following the COMPONENTS.md convention of
    stateless function-oriented components.

    This class exists because db.health was originally accessed
    through a component class pattern. It is retained only for
    compatibility; the functions below are the canonical entry points.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_all_workers(self) -> list[dict[str, Any]]:
        """Get all registered workers from health monitoring.

        Returns:
            List of worker health records

        """
        return self.db.app.list_worker_health()

    def get_component(self, component: str) -> dict[str, Any] | None:
        """Get health status for a specific component.

        Args:
            component: Component name (e.g., "worker:library:scan")

        Returns:
            Health record or None if not found

        """
        return self.db.app.get_health(component)


def get_all_workers(db: Database) -> list[dict[str, Any]]:
    """Get all registered workers from health monitoring.

    Canonical function entry point per COMPONENTS.md conventions.
    """
    return db.app.list_worker_health()


def get_component(db: Database, component: str) -> dict[str, Any] | None:
    """Get health status for a specific component.

    Canonical function entry point per COMPONENTS.md conventions.
    """
    return db.app.get_health(component)
