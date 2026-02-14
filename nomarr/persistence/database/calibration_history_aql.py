"""Calibration history operations for ArangoDB.

calibration_history collection stores append-only snapshots for tracking
calibration drift over time.
"""

from typing import Any, cast

from nomarr.persistence.arango_client import DatabaseLike


class CalibrationHistoryOperations:
    """Operations for the calibration_history collection (drift tracking)."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("calibration_history")

    def create_snapshot(
        self,
        calibration_key: str,
        p5: float,
        p95: float,
        sample_count: int,
        underflow_count: int,
        overflow_count: int,
        p5_delta: float | None = None,
        p95_delta: float | None = None,
        n_delta: int | None = None,
    ) -> str:
        """Create a new calibration snapshot for drift tracking.

        Args:
            calibration_key: Reference to calibration_state._key (e.g., "effnet:mood_happy")
            p5: 5th percentile
            p95: 95th percentile
            n: Total sample count
            underflow_count: Count of values < lo
            overflow_count: Count of values > hi
            p5_delta: Change from previous snapshot
            p95_delta: Change from previous snapshot
            n_delta: Change in sample count from previous snapshot

        Returns:
            Document _id of created snapshot

        """
        now_ms = int(__import__("time").time() * 1000)

        doc = {
            "calibration_key": calibration_key,
            "snapshot_at": now_ms,
            "p5": p5,
            "p95": p95,
            "n": sample_count,
            "underflow_count": underflow_count,
            "overflow_count": overflow_count,
            "p5_delta": p5_delta,
            "p95_delta": p95_delta,
            "n_delta": n_delta,
        }

        result = self.collection.insert(doc)
        return result["_id"]  # type: ignore

    def get_history(
        self,
        calibration_key: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get calibration history for a specific head.

        Args:
            calibration_key: Reference to calibration_state._key
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshot documents, sorted by snapshot_at descending

        """
        cursor = self.db.aql.execute(
            """
            FOR h IN calibration_history
                FILTER h.calibration_key == @calibration_key
                SORT h.snapshot_at DESC
                LIMIT @limit
                RETURN h
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "calibration_key": calibration_key,
                    "limit": limit,
                },
            ),
        )
        return list(cursor)  # type: ignore

    def get_latest_snapshot(
        self,
        calibration_key: str,
    ) -> dict[str, Any] | None:
        """Get the most recent calibration snapshot for a head.

        Args:
            calibration_key: Reference to calibration_state._key

        Returns:
            Latest snapshot document or None if no history exists

        """
        cursor = self.db.aql.execute(
            """
            FOR h IN calibration_history
                FILTER h.calibration_key == @calibration_key
                SORT h.snapshot_at DESC
                LIMIT 1
                RETURN h
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"calibration_key": calibration_key},
            ),
        )
        results = list(cursor)  # type: ignore
        return results[0] if results else None  # type: ignore

    def get_all_recent_snapshots(
        self,
        since_ms: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get recent calibration snapshots across all heads.

        Args:
            since_ms: Only return snapshots after this timestamp (optional)
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshot documents, sorted by snapshot_at descending

        """
        if since_ms:
            cursor = self.db.aql.execute(
                """
                FOR h IN calibration_history
                    FILTER h.snapshot_at >= @since_ms
                    SORT h.snapshot_at DESC
                    LIMIT @limit
                    RETURN h
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "since_ms": since_ms,
                        "limit": limit,
                    },
                ),
            )
        else:
            cursor = self.db.aql.execute(
                """
                FOR h IN calibration_history
                    SORT h.snapshot_at DESC
                    LIMIT @limit
                    RETURN h
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"limit": limit},
                ),
            )
        return list(cursor)  # type: ignore

    def delete_old_snapshots(
        self,
        calibration_key: str,
        keep_count: int = 100,
    ) -> int:
        """Delete old snapshots, keeping only the most recent N.

        Args:
            calibration_key: Reference to calibration_state._key
            keep_count: Number of snapshots to keep

        Returns:
            Number of snapshots deleted

        """
        cursor = self.db.aql.execute(
            """
            LET to_delete = (
                FOR h IN calibration_history
                    FILTER h.calibration_key == @calibration_key
                    SORT h.snapshot_at DESC
                    LIMIT @keep_count, 99999999
                    RETURN h._key
            )
            FOR key IN to_delete
                REMOVE key IN calibration_history
            RETURN 1
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "calibration_key": calibration_key,
                    "keep_count": keep_count,
                },
            ),
        )
        results = list(cursor)  # type: ignore
        return len(results)


    def truncate(self) -> None:
        """Remove all documents from the calibration_history collection."""
        self.collection.truncate()
