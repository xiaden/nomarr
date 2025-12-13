"""Calibration queue operations for the calibration_queue table."""

from __future__ import annotations

import sqlite3
from typing import Any

from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms


class CalibrationQueueOperations:
    """Operations for the calibration_queue table (calibration job queue)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def enqueue_calibration(self, path: LibraryPath) -> int:
        """
        Add file to calibration queue.

        Args:
            path: LibraryPath with validated file path (must have status == "valid")

        Returns:
            Calibration job ID

        Raises:
            ValueError: If path status is not "valid"
        """
        if not path.is_valid():
            raise ValueError(f"Cannot enqueue invalid path ({path.status}): {path.reason}")

        cur = self.conn.cursor()
        ts = now_ms()
        # Store absolute path for now (TODO: store relative + library_id)
        cur.execute(
            "INSERT INTO calibration_queue(path, status, created_at, started_at) VALUES(?, 'pending', ?, NULL)",
            (str(path.absolute), ts),
        )
        self.conn.commit()
        job_id = cur.lastrowid
        if job_id is None:
            raise RuntimeError("Failed to enqueue calibration - no row ID returned")
        return job_id

    def get_next_calibration_job(self) -> tuple[int, str] | None:
        """
        Get next pending calibration job and atomically mark it running.

        Returns:
            (job_id, path) or None if no jobs pending
        """
        # Atomic claim: UPDATE...RETURNING prevents race conditions
        cur = self.conn.execute(
            """
            UPDATE calibration_queue
            SET status='running'
            WHERE id = (
                SELECT id FROM calibration_queue
                WHERE status='pending'
                ORDER BY id
                LIMIT 1
            )
            RETURNING id, path
            """
        )
        row = cur.fetchone()
        self.conn.commit()
        if not row:
            return None
        return (row[0], row[1])

    def complete_calibration_job(self, job_id: int) -> None:
        """Mark calibration job as completed."""
        self.conn.execute(
            "UPDATE calibration_queue SET status='done', completed_at=? WHERE id=?",
            (now_ms(), job_id),
        )
        self.conn.commit()

    def fail_calibration_job(self, job_id: int, error_message: str) -> None:
        """Mark calibration job as failed."""
        self.conn.execute(
            "UPDATE calibration_queue SET status='error', completed_at=?, error_message=? WHERE id=?",
            (now_ms(), error_message, job_id),
        )
        self.conn.commit()

    def get_calibration_status(self) -> dict[str, int]:
        """
        Get calibration queue status counts.

        Returns:
            {"pending": count, "running": count, "done": count, "error": count}
        """
        cursor = self.conn.execute("SELECT status, COUNT(*) FROM calibration_queue GROUP BY status")
        counts = {"pending": 0, "running": 0, "done": 0, "error": 0}
        for status, count in cursor.fetchall():
            counts[status] = count
        return counts

    def clear_calibration_queue(self) -> int:
        """Clear all completed/failed calibration jobs. Returns number cleared."""
        cur = self.conn.execute("DELETE FROM calibration_queue WHERE status IN ('done', 'error')")
        self.conn.commit()
        return cur.rowcount

    def queue_stats(self) -> dict[str, int]:
        """
        Get queue statistics (counts by status).

        Returns:
            Dict with keys: 'pending', 'running', 'done', 'error'
        """
        cur = self.conn.execute(
            """
            SELECT status, COUNT(*) as count
            FROM calibration_queue
            GROUP BY status
            """
        )
        stats = {row[0]: row[1] for row in cur.fetchall()}
        # Ensure all statuses are present (default to 0)
        for status in ("pending", "running", "done", "error"):
            stats.setdefault(status, 0)
        return stats

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
            FROM calibration_queue
            WHERE status IN ('pending', 'running')
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        )
        columns = ["id", "path", "status", "started_at"]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]
