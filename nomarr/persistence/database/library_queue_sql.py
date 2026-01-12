"""Library queue operations for the library_queue table."""

import sqlite3
from typing import Any

from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms


class LibraryQueueOperations:
    """Operations for the library_queue table (library scanning jobs)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def enqueue_scan(self, path: LibraryPath, force: bool = False) -> int:
        """
        Enqueue a file for library scanning.

        Args:
            path: LibraryPath with validated file path (must have status == "valid")
            force: Whether to force rescan even if file hasn't changed

        Returns:
            Job ID

        Raises:
            ValueError: If path status is not "valid"
        """
        if not path.is_valid():
            raise ValueError(f"Cannot enqueue invalid path ({path.status}): {path.reason}")

        cur = self.conn.cursor()
        ts = now_ms()
        cur.execute(
            "INSERT INTO library_queue(path, status, force, created_at, started_at) VALUES(?, 'pending', ?, ?, NULL)",
            (str(path.absolute), 1 if force else 0, ts),
        )
        self.conn.commit()
        job_id = cur.lastrowid
        if job_id is None:
            raise RuntimeError("Failed to enqueue scan job - no row ID returned")
        return job_id

    def dequeue_scan(self) -> tuple[int, str, bool] | None:
        """
        Get next pending scan job and atomically mark it as running.

        Returns:
            Tuple of (job_id, path, force) or None if no pending jobs
        """
        # Atomic claim: UPDATE...RETURNING prevents race conditions
        cur = self.conn.execute(
            """
            UPDATE library_queue
            SET status='running', started_at=?
            WHERE id = (
                SELECT id FROM library_queue
                WHERE status='pending'
                ORDER BY id
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

        return (row[0], row[1], bool(row[2]))

    def mark_scan_complete(self, job_id: int) -> None:
        """
        Mark a scan job as complete.

        Args:
            job_id: Job ID to mark complete
        """
        self.conn.execute(
            "UPDATE library_queue SET status='done', completed_at=? WHERE id=?",
            (now_ms(), job_id),
        )
        self.conn.commit()

    def mark_scan_error(self, job_id: int, error: str) -> None:
        """
        Mark a scan job as failed.

        Args:
            job_id: Job ID to mark as failed
            error: Error message
        """
        self.conn.execute(
            "UPDATE library_queue SET status='error', completed_at=?, error_message=? WHERE id=?",
            (now_ms(), error, job_id),
        )
        self.conn.commit()

    def list_scan_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        List recent scan jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job dicts
        """
        cur = self.conn.execute(
            "SELECT id, path, status, force, started_at, completed_at, error_message "
            "FROM library_queue ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

    def count_pending_scans(self) -> int:
        """
        Count pending scan jobs.

        Returns:
            Number of pending jobs
        """
        cur = self.conn.execute("SELECT COUNT(*) FROM library_queue WHERE status='pending'")
        row = cur.fetchone()
        return row[0] if row else 0

    def clear_scan_queue(self) -> int:
        """
        Clear all pending scan jobs.

        Returns:
            Number of jobs cleared
        """
        cur = self.conn.execute("DELETE FROM library_queue WHERE status='pending'")
        self.conn.commit()
        return cur.rowcount

    def get_library_scan(self, scan_id: int) -> dict[str, Any] | None:
        """
        Get library scan job by ID.

        Args:
            scan_id: Scan ID to look up

        Returns:
            Scan dict or None if not found
        """
        cur = self.conn.execute("SELECT * FROM library_queue WHERE id=?", (scan_id,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def list_library_scans(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        List recent library scans.

        Args:
            limit: Maximum number of scans to return

        Returns:
            List of scan dicts, ordered by started_at DESC
        """
        cur = self.conn.execute("SELECT * FROM library_queue ORDER BY started_at DESC LIMIT ?", (limit,))
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

    def reset_running_library_scans(self) -> int:
        """
        Reset any library scans stuck in 'running' state back to 'pending'.
        This handles container restarts where a scan was interrupted mid-processing.

        Returns:
            Number of scans reset
        """
        cur = self.conn.execute("UPDATE library_queue SET status='pending' WHERE status='running'")
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
            FROM library_queue
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
            FROM library_queue
            WHERE status IN ('pending', 'running')
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        )
        columns = ["id", "path", "status", "started_at"]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]
