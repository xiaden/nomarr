"""Calibration queue operations for the calibration_queue table."""

from __future__ import annotations

import sqlite3


def now_ms() -> int:
    """Return current timestamp in milliseconds."""
    from time import time_ns

    return time_ns() // 1_000_000


class CalibrationQueueOperations:
    """Operations for the calibration_queue table (calibration job queue)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def enqueue_calibration(self, path: str) -> int:
        """Add file to calibration queue. Returns calibration job ID."""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO calibration_queue(path, status, started_at) VALUES(?, 'pending', ?)",
            (path, now_ms()),
        )
        self.conn.commit()
        job_id = cur.lastrowid
        if job_id is None:
            raise RuntimeError("Failed to enqueue calibration - no row ID returned")
        return job_id

    def get_next_calibration_job(self) -> tuple[int, str] | None:
        """
        Get next pending calibration job and mark it running.

        Returns:
            (job_id, path) or None if no jobs pending
        """
        cur = self.conn.execute("SELECT id, path FROM calibration_queue WHERE status='pending' ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None

        job_id, path = row
        self.conn.execute(
            "UPDATE calibration_queue SET status='running' WHERE id=?",
            (job_id,),
        )
        self.conn.commit()
        return (job_id, path)

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
