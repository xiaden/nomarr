"""Tag queue operations for ML tagging jobs."""

import json
import sqlite3
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    pass


class QueueOperations:
    """Operations for the tag_queue table (ML tagging job queue)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def enqueue(self, path: LibraryPath, force: bool = False) -> int:
        """
        Add a file to the tagging queue.

        Args:
            path: LibraryPath with validated file path (must have status == "valid")
            force: If True, requeue even if already processed

        Returns:
            Job ID

        Raises:
            ValueError: If path status is not "valid"
        """
        if not path.is_valid():
            raise ValueError(f"Cannot enqueue invalid path ({path.status}): {path.reason}")

        cur = self.conn.cursor()
        ts = now_ms()
        # Store absolute path for now (TODO: store relative + library_id)
        cur.execute(
            "INSERT INTO tag_queue(path, status, created_at, force) VALUES(?,?,?,?)",
            (str(path.absolute), "pending", ts, int(force)),
        )
        self.conn.commit()

        # Validate successful insert and return type
        job_id = cur.lastrowid
        if job_id is None:
            raise RuntimeError("Failed to insert job into tag_queue - no row ID returned")
        return job_id

    def update_job(
        self, job_id: int, status: str, error_message: str | None = None, results: dict[str, Any] | None = None
    ) -> None:
        """
        Update job status and metadata.

        Args:
            job_id: Job ID to update
            status: New status ('pending', 'running', 'done', 'error')
            error_message: Error message if status is 'error'
            results: Results dict to store as JSON
        """
        ts = now_ms()
        results_json = json.dumps(results) if results else None

        if status == "running":
            self.conn.execute("UPDATE tag_queue SET status=?, started_at=? WHERE id=?", (status, ts, job_id))
        elif status in ("done", "error"):
            self.conn.execute(
                "UPDATE tag_queue SET status=?, finished_at=?, error_message=?, results_json=? WHERE id=?",
                (status, ts, error_message, results_json, job_id),
            )
        else:
            self.conn.execute("UPDATE tag_queue SET status=? WHERE id=?", (status, job_id))
        self.conn.commit()

    def job_status(self, job_id: int) -> dict[str, Any] | None:
        """
        Get full job information by ID.

        Args:
            job_id: Job ID to look up

        Returns:
            Job dict or None if not found
        """
        cur = self.conn.execute("SELECT * FROM tag_queue WHERE id=?", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def queue_depth(self) -> int:
        """Get count of pending + running jobs."""
        cur = self.conn.execute("SELECT COUNT(*) FROM tag_queue WHERE status IN ('pending', 'running')")
        return int(cur.fetchone()[0])

    def queue_stats(self) -> dict[str, int]:
        """
        Get counts of jobs by status.

        Returns:
            Dict with keys: 'pending', 'running', 'done', 'error'
        """
        cur = self.conn.execute(
            """
            SELECT status, COUNT(*) as count
            FROM tag_queue
            GROUP BY status
            """
        )
        stats = {row[0]: row[1] for row in cur.fetchall()}
        # Ensure all statuses are present (default to 0)
        for status in ("pending", "running", "done", "error"):
            stats.setdefault(status, 0)
        return stats

    def clear_old_jobs(self, max_age_hours: int = 168) -> None:
        """
        Delete completed jobs older than specified age.

        Args:
            max_age_hours: Maximum age in hours (default: 7 days)
        """
        cutoff = now_ms() - max_age_hours * 3600 * 1000
        self.conn.execute("DELETE FROM tag_queue WHERE finished_at IS NOT NULL AND finished_at < ?", (cutoff,))
        self.conn.commit()

    def reset_running_to_pending(self) -> int:
        """
        Reset any jobs in 'running' state back to 'pending'.
        Used during startup to recover orphaned jobs from crashes/restarts.

        Returns:
            Number of jobs reset
        """
        # Count first, then update (rowcount doesn't work reliably with SQLite)
        count_cursor = self.conn.execute("SELECT COUNT(*) FROM tag_queue WHERE status = 'running'")
        row = count_cursor.fetchone()
        count = row[0] if row else 0
        self.conn.execute(
            "UPDATE tag_queue SET status = 'pending', started_at = NULL, error_message = NULL, finished_at = NULL WHERE status = 'running'"
        )
        self.conn.commit()
        return count

    def get_running_job_ids(self) -> list[int]:
        """
        Get all job IDs currently in 'running' state.

        Returns:
            List of job IDs
        """
        cur = self.conn.execute("SELECT id FROM tag_queue WHERE status='running'")
        return [row[0] for row in cur.fetchall()]

    def get_next_pending_job(self) -> dict[str, Any] | None:
        """
        Get the next pending job (oldest first) and atomically mark it running.

        Returns:
            Job dict with id, path, force or None if no pending jobs
        """
        # Atomic claim: UPDATE...RETURNING prevents race conditions
        cur = self.conn.execute(
            """
            UPDATE tag_queue
            SET status='running', started_at=?
            WHERE id = (
                SELECT id FROM tag_queue
                WHERE status='pending'
                ORDER BY id ASC
                LIMIT 1
            )
            RETURNING id, path, force
            """,
            (now_ms(),),
        )
        row = cur.fetchone()
        self.conn.commit()
        if not row:
            return None
        return {"id": row[0], "path": row[1], "force": bool(row[2])}

    def get_recent_done_jobs_timing(self, limit: int = 5) -> list[tuple[int, int]]:
        """
        Get timing data for recently completed jobs.

        Args:
            limit: Number of recent jobs to fetch

        Returns:
            List of (finished_at, started_at) tuples in milliseconds
        """
        cur = self.conn.execute(
            """
            SELECT finished_at, started_at
            FROM tag_queue
            WHERE status='done' AND finished_at IS NOT NULL AND started_at IS NOT NULL
            ORDER BY finished_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]

    def get_active_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Get currently active (pending or running) jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job dicts with id, path, status, started_at
        """
        cur = self.conn.execute(
            """
            SELECT id, path, status, started_at
            FROM tag_queue
            WHERE status IN ('pending', 'running')
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        )
        columns = ["id", "path", "status", "started_at"]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

    def delete_job(self, job_id: int) -> int:
        """
        Delete a job by ID.

        Args:
            job_id: Job ID to delete

        Returns:
            Number of jobs deleted (1 if found, 0 if not found)
        """
        cursor = self.conn.execute("DELETE FROM tag_queue WHERE id=?", (job_id,))
        self.conn.commit()
        return cursor.rowcount

    def list_jobs(
        self, limit: int = 25, offset: int = 0, status: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List jobs with pagination and optional status filter.

        Args:
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip (for pagination)
            status: Filter by status (pending/running/done/error), or None for all

        Returns:
            Tuple of (list of job dicts, total count matching filter)
        """
        # Build query with optional status filter
        if status:
            query = "SELECT * FROM tag_queue WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?"
            count_query = "SELECT COUNT(*) FROM tag_queue WHERE status = ?"
            params: tuple[str, int, int] = (status, limit, offset)
            count_params: tuple[str] = (status,)
        else:
            query = "SELECT * FROM tag_queue ORDER BY id DESC LIMIT ? OFFSET ?"
            count_query = "SELECT COUNT(*) FROM tag_queue"
            params = (limit, offset)  # type: ignore[assignment]
            count_params = ()  # type: ignore[assignment]

        # Get total count
        cur = self.conn.execute(count_query, count_params)
        total = cur.fetchone()[0]

        # Get jobs
        cur = self.conn.execute(query, params)
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        jobs = [dict(zip(columns, r, strict=False)) for r in rows]

        return jobs, total

    def delete_jobs_by_status(self, statuses: list[str]) -> int:
        """
        Delete jobs by status.

        Args:
            statuses: List of statuses to delete

        Returns:
            Number of jobs deleted
        """
        placeholders = ",".join("?" * len(statuses))
        query = f"DELETE FROM tag_queue WHERE status IN ({placeholders})"
        cursor = self.conn.execute(query, tuple(statuses))
        count = cursor.rowcount
        self.conn.commit()
        return count

    def reset_stuck_jobs(self) -> int:
        """
        Reset jobs stuck in 'running' state back to 'pending'.

        Clears all state fields (started_at, error_message, finished_at).

        Returns:
            Number of jobs reset
        """
        cursor = self.conn.execute(
            """UPDATE tag_queue
               SET status='pending', started_at=NULL, error_message=NULL, finished_at=NULL
               WHERE status='running'"""
        )
        count = cursor.rowcount
        self.conn.commit()
        return count

    def reset_error_jobs(self) -> int:
        """
        Reset jobs in 'error' state back to 'pending'.

        Clears error state fields (error_message, finished_at).

        Returns:
            Number of jobs reset
        """
        cursor = self.conn.execute(
            """UPDATE tag_queue
               SET status='pending', error_message=NULL, finished_at=NULL
               WHERE status='error'"""
        )
        count = cursor.rowcount
        self.conn.commit()
        return count
