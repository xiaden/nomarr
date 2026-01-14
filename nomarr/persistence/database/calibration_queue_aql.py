"""Calibration queue operations for ArangoDB."""

from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase

from nomarr.helpers.time_helper import now_ms


class CalibrationQueueOperations:
    """Operations for the calibration_queue collection."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("calibration_queue")

    def enqueue(self, run_id: str, model_key: str, priority: int = 0) -> str:
        """Add a calibration job to the queue.

        Args:
            run_id: Calibration run ID
            model_key: Model key to calibrate
            priority: Job priority (higher = more urgent)

        Returns:
            Job _id
        """
        ts = now_ms()
        result = cast(
            dict[str, Any],
            self.collection.insert(
                {
                    "run_id": run_id,
                    "model_key": model_key,
                    "priority": priority,
                    "status": "pending",
                    "created_at": ts,
                    "started_at": None,
                    "finished_at": None,
                    "error_message": None,
                }
            ),
        )
        return str(result["_id"])

    def update_job(self, job_id: str, status: str, error_message: str | None = None) -> None:
        """Update job status.

        Args:
            job_id: Job _id
            status: New status ('pending', 'running', 'done', 'error')
            error_message: Error message if status is 'error'
        """
        ts = now_ms()
        update_fields: dict[str, Any] = {"status": status}

        if status == "running":
            update_fields["started_at"] = ts
        elif status in ("done", "error"):
            update_fields["finished_at"] = ts
            update_fields["error_message"] = error_message

        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@job_id).key WITH @fields IN calibration_queue
            """,
            bind_vars={"job_id": job_id, "fields": update_fields},
        )

    def get_pending_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get highest priority pending jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job dicts
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN calibration_queue
                FILTER job.status == "pending"
                SORT job.priority DESC, job.created_at ASC
                LIMIT @limit
                RETURN job
            """,
                bind_vars=cast(dict[str, Any], {"limit": limit}),
            ),
        )
        return list(cursor)

    def queue_depth(self) -> int:
        """Get count of pending + running jobs."""
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN calibration_queue
                FILTER job.status IN ['pending', 'running']
                COLLECT WITH COUNT INTO total
                RETURN total
            """
            ),
        )
        return next(cursor, 0)

    def clear_queue(self) -> int:
        """Delete all jobs.

        Returns:
            Number of jobs deleted
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN calibration_queue
                REMOVE job IN calibration_queue
                RETURN 1
            """
            ),
        )
        return len(list(cursor))

    def get_next_calibration_job(self) -> dict[str, Any] | None:
        """Get next pending calibration job."""
        jobs = self.get_pending_jobs(limit=1)
        return jobs[0] if jobs else None

    def queue_stats(self) -> dict[str, int]:
        """Get queue statistics.

        Returns:
            Dict with pending, running, done, error counts
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN calibration_queue
                COLLECT status = job.status WITH COUNT INTO count
                RETURN {status: status, count: count}
            """
            ),
        )

        stats = {"pending": 0, "running": 0, "done": 0, "error": 0}
        for row in cursor:
            stats[row["status"]] = row["count"]
        return stats

    def get_active_jobs(self) -> list[dict[str, Any]]:
        """Get all active (running) calibration jobs."""
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR job IN calibration_queue
                FILTER job.status == 'running'
                SORT job.started_at DESC
                RETURN job
            """
            ),
        )
        return list(cursor)

    def enqueue_calibration(self, run_id: str, model_key: str, priority: int = 0) -> str:
        """Alias for enqueue() for backward compatibility."""
        return self.enqueue(run_id=run_id, model_key=model_key, priority=priority)

    def complete_calibration_job(self, job_id: str) -> None:
        """Mark calibration job as done."""
        self.update_job(job_id=job_id, status="done")

    def fail_calibration_job(self, job_id: str, error: str) -> None:
        """Mark calibration job as error."""
        self.update_job(job_id=job_id, status="error", error_message=error)

    def clear_calibration_queue(self) -> int:
        """Alias for clear_queue() for backward compatibility."""
        return self.clear_queue()
