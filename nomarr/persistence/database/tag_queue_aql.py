"""Tag queue operations for ArangoDB.

CRITICAL: All mutations by _id must use PARSE_IDENTIFIER(@id).key
to extract the document key for UPDATE/REMOVE operations.
"""

import json
from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase

from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms


class QueueOperations:
    """Operations for the tag_queue collection (ML tagging job queue)."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("tag_queue")

    def enqueue(self, path: LibraryPath, force: bool = False) -> str:
        """Add a file to the tagging queue.

        Args:
            path: LibraryPath with validated file path (must have status == "valid")
            force: If True, requeue even if already processed

        Returns:
            Job _id (e.g., "tag_queue/12345")

        Raises:
            ValueError: If path status is not "valid"
        """
        if not path.is_valid():
            raise ValueError(f"Cannot enqueue invalid path ({path.status}): {path.reason}")

        ts = now_ms()
        result = cast(
            dict[str, Any],
            self.collection.insert(
                {
                    "path": str(path.absolute),
                    "status": "pending",
                    "created_at": ts,
                    "force": force,
                    "started_at": None,
                    "finished_at": None,
                    "error_message": None,
                    "results_json": None,
                }
            ),
        )

        return str(result["_id"])

    def update_job(
        self, job_id: str, status: str, error_message: str | None = None, results: dict[str, Any] | None = None
    ) -> None:
        """Update job status and metadata.

        Args:
            job_id: Job _id (e.g., "tag_queue/12345")
            status: New status ('pending', 'running', 'done', 'error')
            error_message: Error message if status is 'error'
            results: Results dict to store as JSON
        """
        ts = now_ms()
        results_json = json.dumps(results) if results else None

        update_fields: dict[str, Any] = {"status": status}

        if status == "running":
            update_fields["started_at"] = ts
        elif status in ("done", "error"):
            update_fields["finished_at"] = ts
            update_fields["error_message"] = error_message
            update_fields["results_json"] = results_json

        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@job_id).key WITH @fields IN tag_queue
            """,
            bind_vars={"job_id": job_id, "fields": update_fields},
        )

    def job_status(self, job_id: str) -> dict[str, Any] | None:
        """Get full job information by _id.

        Args:
            job_id: Job _id (e.g., "tag_queue/12345")

        Returns:
            Job dict or None if not found
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            RETURN DOCUMENT(@job_id)
            """,
                bind_vars={"job_id": job_id},
            ),
        )
        return next(cursor, None)

    def queue_depth(self) -> int:
        """Get count of pending + running jobs."""
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN tag_queue
                FILTER job.status IN ['pending', 'running']
                COLLECT WITH COUNT INTO total
                RETURN total
            """
            ),
        )
        return next(cursor, 0)

    def queue_stats(self) -> dict[str, int]:
        """Get job counts by status.

        Returns:
            Dict with status -> count
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN tag_queue
                COLLECT status = job.status WITH COUNT INTO count
                RETURN { status, count }
            """
            ),
        )

        stats = {"pending": 0, "running": 0, "done": 0, "error": 0}
        for item in cursor:
            stats[item["status"]] = item["count"]

        return stats

    def get_pending_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get oldest pending jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job dicts
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN tag_queue
                FILTER job.status == 'pending'
                SORT job.created_at ASC
                LIMIT @limit
                RETURN job
            """,
                bind_vars=cast(dict[str, Any], {"limit": limit}),
            ),
        )
        return list(cursor)

    def claim_job(self, job_id: str) -> bool:
        """Atomically claim a pending job.

        Args:
            job_id: Job _id to claim

        Returns:
            True if claimed successfully, False if already claimed/gone
        """
        ts = now_ms()
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN tag_queue
                FILTER job._id == @job_id AND job.status == 'pending'
                UPDATE job WITH { status: 'running', started_at: @ts } IN tag_queue
                RETURN NEW
            """,
                bind_vars=cast(dict[str, Any], {"job_id": job_id, "ts": ts}),
            ),
        )
        result = list(cursor)
        return len(result) > 0

    def clear_queue(self) -> int:
        """Delete all jobs.

        Returns:
            Number of jobs deleted
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN tag_queue
                REMOVE job IN tag_queue
                RETURN 1
            """
            ),
        )
        return len(list(cursor))

    def reset_stale_jobs(self, timeout_ms: int = 300000) -> int:
        """Reset jobs stuck in 'running' state.

        Args:
            timeout_ms: Timeout in milliseconds (default 5 minutes)

        Returns:
            Number of jobs reset
        """
        now = now_ms()
        cutoff = now - timeout_ms

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN tag_queue
                FILTER job.status == 'running' AND job.started_at < @cutoff
                UPDATE job WITH { status: 'pending', started_at: null } IN tag_queue
                RETURN 1
            """,
                bind_vars=cast(dict[str, Any], {"cutoff": cutoff}),
            ),
        )
        return len(list(cursor))

    def get_next_pending_job(self) -> dict[str, Any] | None:
        """Get next pending job (highest priority, oldest first)."""
        jobs = self.get_pending_jobs(limit=1)
        return jobs[0] if jobs else None

    def list_jobs(self, status: str | None = None, limit: int = 100) -> tuple[list[dict[str, Any]], int]:
        """List jobs with optional status filter.

        Returns:
            Tuple of (jobs list, total count)
        """
        filter_clause = "FILTER job.status == @status" if status else ""

        # Get total count
        count_cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR job IN tag_queue
                {filter_clause}
                COLLECT WITH COUNT INTO total
                RETURN total
            """,
                bind_vars=cast(dict[str, Any], {"status": status} if status else {}),
            ),
        )
        total = next(count_cursor, 0)

        # Get jobs
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR job IN tag_queue
                {filter_clause}
                SORT job.priority DESC, job.created_at ASC
                LIMIT @limit
                RETURN job
            """,
                bind_vars=cast(dict[str, Any], {"limit": limit, "status": status} if status else {"limit": limit}),
            ),
        )
        return list(cursor), total

    def get_active_jobs(self) -> list[dict[str, Any]]:
        """Get all active (running) jobs."""
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN tag_queue
                FILTER job.status == 'running'
                SORT job.started_at DESC
                RETURN job
            """
            ),
        )
        return list(cursor)

    def delete_job(self, job_id: str) -> int:
        """Delete a single job by ID.

        Returns:
            1 if deleted, 0 if not found
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            REMOVE PARSE_IDENTIFIER(@job_id).key IN tag_queue
            RETURN 1
            """,
                bind_vars=cast(dict[str, Any], {"job_id": job_id}),
            ),
        )
        return len(list(cursor))

    def delete_jobs_by_status(self, status: str) -> int:
        """Delete all jobs with given status.

        Returns:
            Number of jobs deleted
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN tag_queue
                FILTER job.status == @status
                REMOVE job IN tag_queue
                RETURN 1
            """,
                bind_vars=cast(dict[str, Any], {"status": status}),
            ),
        )
        return len(list(cursor))

    def reset_error_jobs(self) -> int:
        """Reset all error jobs to pending.

        Returns:
            Number of jobs reset
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN tag_queue
                FILTER job.status == 'error'
                UPDATE job WITH {status: 'pending', error_message: null} IN tag_queue
                RETURN 1
            """
            ),
        )
        return len(list(cursor))

    def clear_completed_jobs(self, max_age_days: int | None = None) -> int:
        """Clear completed jobs older than max_age_days.

        Returns:
            Number of jobs cleared
        """
        if max_age_days:
            cutoff = now_ms() - (max_age_days * 24 * 60 * 60 * 1000)
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR job IN tag_queue
                    FILTER job.status == 'completed' AND job.finished_at < @cutoff
                    REMOVE job IN tag_queue
                    RETURN 1
                """,
                    bind_vars=cast(dict[str, Any], {"cutoff": cutoff}),
                ),
            )
        else:
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR job IN tag_queue
                    FILTER job.status == 'completed'
                    REMOVE job IN tag_queue
                    RETURN 1
                """
                ),
            )
        return len(list(cursor))
