"""Health operations for ArangoDB (component health monitoring)."""

from typing import Any, cast

from arango.cursor import Cursor

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike


class HealthOperations:
    """Operations for the health collection (component health monitoring)."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("health")

    def update_health(self, component: str, status: str, message: str | None = None) -> None:
        """Update component health status (upsert).

        Args:
            component: Component name (e.g., 'database', 'ml', 'queue')
            status: Status ('healthy', 'degraded', 'unhealthy')
            message: Optional status message
        """
        ts = now_ms().value
        self.db.aql.execute(
            """
            UPSERT { component: @component }
            INSERT {
                component: @component,
                status: @status,
                message: @message,
                last_checked: @ts,
                created_at: @ts
            }
            UPDATE {
                status: @status,
                message: @message,
                last_checked: @ts
            }
            IN health
            """,
            bind_vars=cast(dict[str, Any], {"component": component, "status": status, "message": message, "ts": ts}),
        )

    def get_health(self, component: str) -> dict[str, Any] | None:
        """Get health status for a component.

        Args:
            component: Component name

        Returns:
            Health dict or None if not found
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR health IN health
                FILTER health.component == @component
                SORT health._key
                LIMIT 1
                RETURN health
            """,
                bind_vars={"component": component},
            ),
        )
        return next(cursor, None)

    def get_all_health(self) -> list[dict[str, Any]]:
        """Get health status for all components.

        Returns:
            List of health dicts
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR health IN health
                SORT health.component ASC
                RETURN health
            """
            ),
        )
        return list(cursor)

    def delete_health(self, component: str) -> None:
        """Delete health record for a component.

        Args:
            component: Component name
        """
        self.db.aql.execute(
            """
            FOR health IN health
                FILTER health.component == @component
                REMOVE health IN health
            """,
            bind_vars={"component": component},
        )

    def get_all_workers(self) -> list[dict[str, Any]]:
        """Get all worker health records."""
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR health IN health
                FILTER health.component_type == 'worker'
                SORT health.last_heartbeat DESC
                RETURN health
            """
            ),
        )
        return list(cursor)

    def upsert_component(self, component_id: str, component_type: str, data: dict[str, Any]) -> None:
        """Upsert component health data.

        Args:
            component_id: Component identifier
            component_type: Type of component (worker, service, etc.)
            data: Dict with component, status, current_job, metadata, pid, etc.
        """
        ts = now_ms().value

        self.db.aql.execute(
            """
            UPSERT {component_id: @component_id}
            INSERT MERGE(@data, {component_id: @component_id, component_type: @component_type, last_heartbeat: @timestamp})
            UPDATE MERGE(@data, {last_heartbeat: @timestamp})
            IN health
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "component_id": component_id,
                    "component_type": component_type,
                    "data": data,
                    "timestamp": ts,
                },
            ),
        )

    def mark_stopping(self, component_id: str, exit_code: int | None = None) -> None:
        """Mark component as stopping."""
        update_data: dict[str, Any] = {"status": "stopping"}
        if exit_code is not None:
            update_data["exit_code"] = exit_code

        self.db.aql.execute(
            """
            FOR health IN health
                FILTER health.component_id == @component_id
                UPDATE health WITH @data IN health
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "component_id": component_id,
                    "data": update_data,
                },
            ),
        )

    def update_heartbeat(self, component_id: str, status: str | None = None, current_job: str | None = None) -> None:
        """Update component heartbeat with optional status and job.

        Uses UPSERT to handle the case where the component doesn't exist yet,
        avoiding write-write conflicts on startup.
        """
        ts = now_ms().value

        update_data: dict[str, Any] = {"last_heartbeat": ts}
        if status:
            update_data["status"] = status
        if current_job is not None:
            update_data["current_job"] = current_job

        self.db.aql.execute(
            """
            UPSERT {component_id: @component_id}
            INSERT MERGE(@data, {component_id: @component_id, component_type: "app"})
            UPDATE @data
            IN health
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "component_id": component_id,
                    "data": update_data,
                },
            ),
        )

    def is_healthy(self, component_id: str | None = None, max_age_ms: int = 60000) -> bool:
        """
        Check if component(s) are healthy.

        Args:
            component_id: Specific component to check (None = check all workers)
            max_age_ms: Maximum staleness in milliseconds (default 60000ms = 60s)

        Returns:
            True if healthy, False otherwise
        """
        cutoff = now_ms().value - max_age_ms

        if component_id is not None:
            # Check specific component
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR health IN health
                    FILTER health.component_id == @component_id
                    FILTER health.status IN ['crashed', 'failed', 'stopping']
                        OR health.last_heartbeat < @cutoff
                    LIMIT 1
                    RETURN 1
                """,
                    bind_vars=cast(
                        dict[str, Any],
                        {
                            "component_id": component_id,
                            "cutoff": cutoff,
                        },
                    ),
                ),
            )
            return len(list(cursor)) == 0
        else:
            # Check all components
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR health IN health
                    FILTER health.status IN ['crashed', 'failed', 'stopping']
                        OR health.last_heartbeat < @cutoff
                    LIMIT 1
                    RETURN 1
                """,
                    bind_vars=cast(
                        dict[str, Any],
                        {
                            "cutoff": cutoff,
                        },
                    ),
                ),
            )
            return len(list(cursor)) == 0

    def get_component(self, component_id: str) -> dict[str, Any] | None:
        """Get component health record."""
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR health IN health
                FILTER health.component_id == @component_id
                RETURN health
            """,
                bind_vars=cast(dict[str, Any], {"component_id": component_id}),
            ),
        )
        results = list(cursor)
        return results[0] if results else None

    def mark_crashed(
        self,
        component_id: str,
        exit_code: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mark component as crashed with full diagnostic context.

        Args:
            component_id: Component identifier
            exit_code: Process exit code (custom codes: -1=unknown, -2=heartbeat_timeout, -3=invalid_heartbeat)
            error: Human-readable error message
            metadata: Structured crash context (e.g., {"crash_type": "oom", "job_id": "123"})
        """
        import json

        update_data: dict[str, Any] = {
            "status": "crashed",
            "last_heartbeat": now_ms().value,
        }

        if exit_code is not None:
            update_data["exit_code"] = exit_code
        if error is not None:
            update_data["error"] = error
        if metadata is not None:
            update_data["metadata"] = json.dumps(metadata)

        self.db.aql.execute(
            """
            FOR health IN health
                FILTER health.component_id == @component_id
                UPDATE health WITH @update_data IN health
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "component_id": component_id,
                    "update_data": update_data,
                },
            ),
        )

    def increment_restart_count(self, component_id: str) -> dict[str, Any]:
        """Increment restart counter for component.

        Returns:
            Dict with updated restart_count and last_restart timestamp
        """
        ts = now_ms().value
        self.db.aql.execute(
            """
            FOR health IN health
                FILTER health.component_id == @component_id
                UPDATE health WITH {
                    restart_count: (health.restart_count || 0) + 1,
                    last_restart: @timestamp
                } IN health
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "component_id": component_id,
                    "timestamp": ts,
                },
            ),
        )
        # Return updated component
        component = self.get_component(component_id)
        return component or {"restart_count": 1, "last_restart": ts}

    def reset_restart_count(self, component_id: str) -> None:
        """Reset restart counter for component."""
        self.db.aql.execute(
            """
            FOR health IN health
                FILTER health.component_id == @component_id
                UPDATE health WITH {restart_count: 0} IN health
            """,
            bind_vars=cast(dict[str, Any], {"component_id": component_id}),
        )

    def mark_failed(self, component_id: str, error: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        """Mark component as permanently failed (will not auto-restart).

        Args:
            component_id: Component identifier
            error: Failure reason (e.g., "restart limit exceeded")
            metadata: Structured failure context
        """
        import json

        update_data: dict[str, Any] = {
            "status": "failed",
            "last_heartbeat": now_ms().value,
        }

        if error is not None:
            update_data["error"] = error
        if metadata is not None:
            update_data["metadata"] = json.dumps(metadata)

        self.db.aql.execute(
            """
            FOR health IN health
                FILTER health.component_id == @component_id
                UPDATE health WITH @update_data IN health
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "component_id": component_id,
                    "update_data": update_data,
                },
            ),
        )

    def mark_starting(self, component_id: str, component_type: str) -> None:
        """Mark component as starting."""
        self.db.aql.execute(
            """
            UPSERT {component_id: @component_id}
            INSERT {
                component_id: @component_id,
                component_type: @component_type,
                status: 'starting',
                last_heartbeat: @timestamp
            }
            UPDATE {
                status: 'starting',
                last_heartbeat: @timestamp
            }
            IN health
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "component_id": component_id,
                    "component_type": component_type,
                    "timestamp": now_ms().value,
                },
            ),
        )

    def mark_healthy(self, component_id: str) -> None:
        """Mark component as healthy."""
        self.db.aql.execute(
            """
            FOR health IN health
                FILTER health.component_id == @component_id
                UPDATE health WITH {
                    status: 'healthy',
                    error: null,
                    last_heartbeat: @timestamp
                } IN health
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "component_id": component_id,
                    "timestamp": now_ms().value,
                },
            ),
        )

    def update_health_snapshot(
        self,
        component_id: str,
        status: str,
        timestamp: int,
    ) -> None:
        """Write a health history snapshot for a component.

        This is used by HealthMonitor to record status for history/diagnostics.
        This is WRITE-ONLY and BEST-EFFORT - not used for liveness decisions.

        Args:
            component_id: Component identifier
            status: Current status (pending, healthy, unhealthy, failed)
            timestamp: Timestamp in milliseconds
        """
        self.db.aql.execute(
            """
            UPSERT {component_id: @component_id}
            INSERT {
                component_id: @component_id,
                status: @status,
                last_snapshot: @timestamp,
                created_at: @timestamp,
                snapshot_type: "history"
            }
            UPDATE {
                status: @status,
                last_snapshot: @timestamp
            }
            IN health
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "component_id": component_id,
                    "status": status,
                    "timestamp": timestamp,
                },
            ),
        )

    def clean_all(self) -> int:
        """Delete all health records.

        Returns:
            Number of records deleted
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR health IN health
                REMOVE health IN health
                RETURN 1
            """
            ),
        )
        return len(list(cursor))
