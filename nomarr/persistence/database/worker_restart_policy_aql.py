"""Worker restart policy operations for ArangoDB.

This collection stores restart policy state (restart counts, failure reasons) to
survive app restarts. This is separate from health telemetry to prevent the
"DB-as-authority" antipattern.

Architecture:
- Restart decisions are triggered ONLY by HealthMonitor callbacks (in-memory authority)
- This persistence exists ONLY to preserve restart counters across app restarts
- No staleness/health computation from these fields (that's HealthMonitor's job)
- Separate from health collection to enforce separation of concerns
"""

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor


class WorkerRestartPolicyOperations:
    """Operations for the worker_restart_policy collection (restart state persistence)."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("worker_restart_policy")

    def get_restart_state(self, component_id: str) -> tuple[int, int | None]:
        """Get restart state for a component.

        Args:
            component_id: Component identifier (e.g., "worker:tag:0")

        Returns:
            Tuple of (restart_count, last_restart_wall_ms)
            Returns (0, None) if no record exists

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR doc IN worker_restart_policy
                    FILTER doc.component_id == @component_id
                    LIMIT 1
                    RETURN {
                        restart_count: doc.restart_count,
                        last_restart_wall_ms: doc.last_restart_wall_ms
                    }
                """,
                bind_vars={"component_id": component_id},
            ),
        )
        result = next(cursor, None)
        if result is None:
            return (0, None)
        return (result.get("restart_count", 0), result.get("last_restart_wall_ms"))

    def increment_restart_count(self, component_id: str) -> None:
        """Increment restart count and update timestamp.

        Uses UPSERT to create document if missing (first restart).

        Args:
            component_id: Component identifier (e.g., "worker:tag:0")

        """
        ts = now_ms().value
        self.db.aql.execute(
            """
            UPSERT { component_id: @component_id }
            INSERT {
                component_id: @component_id,
                _key: @key,
                restart_count: 1,
                last_restart_wall_ms: @timestamp,
                failed_at_wall_ms: null,
                failure_reason: null,
                updated_at_wall_ms: @timestamp
            }
            UPDATE {
                restart_count: OLD.restart_count + 1,
                last_restart_wall_ms: @timestamp,
                updated_at_wall_ms: @timestamp
            }
            IN worker_restart_policy
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "component_id": component_id,
                    "key": component_id,  # Use component_id as document key
                    "timestamp": ts,
                },
            ),
        )

    def reset_restart_count(self, component_id: str) -> None:
        """Reset restart count to 0 (manual admin reset).

        Args:
            component_id: Component identifier (e.g., "worker:tag:0")

        """
        ts = now_ms().value
        self.db.aql.execute(
            """
            FOR doc IN worker_restart_policy
                FILTER doc.component_id == @component_id
                UPDATE doc WITH {
                    restart_count: 0,
                    last_restart_wall_ms: null,
                    updated_at_wall_ms: @timestamp
                } IN worker_restart_policy
            """,
            bind_vars=cast("dict[str, Any]", {"component_id": component_id, "timestamp": ts}),
        )

    def mark_failed_permanent(self, component_id: str, failure_reason: str) -> None:
        """Mark component as permanently failed with reason.

        Does NOT modify restart_count (preserves history).

        Args:
            component_id: Component identifier (e.g., "worker:tag:0")
            failure_reason: Human-readable failure explanation

        """
        ts = now_ms().value
        self.db.aql.execute(
            """
            UPSERT { component_id: @component_id }
            INSERT {
                component_id: @component_id,
                _key: @key,
                restart_count: 0,
                last_restart_wall_ms: null,
                failed_at_wall_ms: @timestamp,
                failure_reason: @failure_reason,
                updated_at_wall_ms: @timestamp
            }
            UPDATE {
                failed_at_wall_ms: @timestamp,
                failure_reason: @failure_reason,
                updated_at_wall_ms: @timestamp
            }
            IN worker_restart_policy
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "component_id": component_id,
                    "key": component_id,
                    "timestamp": ts,
                    "failure_reason": failure_reason,
                },
            ),
        )
