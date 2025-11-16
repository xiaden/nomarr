"""Calibration operations for calibration_queue and calibration_runs tables."""

from __future__ import annotations

import sqlite3
from typing import Any


def now_ms() -> int:
    """Return current timestamp in milliseconds."""
    from time import time_ns

    return time_ns() // 1_000_000


class CalibrationOperations:
    """Operations for calibration queue and calibration run tracking."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------------------------- Calibration Queue ----------------------------

    def enqueue_calibration(self, file_path: str) -> int:
        """Add file to calibration queue. Returns calibration job ID."""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO calibration_queue(file_path, status, started_at) VALUES(?, 'pending', ?)",
            (file_path, now_ms()),
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
            (job_id, file_path) or None if no jobs pending
        """
        cur = self.conn.execute(
            "SELECT id, file_path FROM calibration_queue WHERE status='pending' ORDER BY id LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None

        job_id, file_path = row
        self.conn.execute(
            "UPDATE calibration_queue SET status='running' WHERE id=?",
            (job_id,),
        )
        self.conn.commit()
        return (job_id, file_path)

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

    def reset_running_calibration_jobs(self) -> int:
        """Reset stuck 'running' calibration jobs back to 'pending'. Returns count reset."""
        cur = self.conn.execute("UPDATE calibration_queue SET status='pending' WHERE status='running'")
        self.conn.commit()
        return cur.rowcount

    # ---------------------------- Calibration Runs ----------------------------

    def insert_calibration_run(
        self,
        model_name: str,
        head_name: str,
        version: int,
        file_count: int,
        p5: float,
        p95: float,
        range_val: float,
        reference_version: int | None = None,
        apd_p5: float | None = None,
        apd_p95: float | None = None,
        srd: float | None = None,
        jsd: float | None = None,
        median_drift: float | None = None,
        iqr_drift: float | None = None,
        is_stable: bool = False,
    ) -> int:
        """
        Insert a new calibration run record.

        Args:
            model_name: Model identifier (e.g., 'effnet')
            head_name: Head identifier (e.g., 'mood_happy')
            version: Calibration version number
            file_count: Number of files used for calibration
            p5: 5th percentile value
            p95: 95th percentile value
            range_val: P95 - P5 (scale range)
            reference_version: Version this was compared against (None if first)
            apd_p5: Absolute percentile drift for P5
            apd_p95: Absolute percentile drift for P95
            srd: Scale range drift
            jsd: Jensen-Shannon divergence
            median_drift: Median drift
            iqr_drift: IQR drift
            is_stable: Whether this calibration is stable

        Returns:
            Row ID of inserted record
        """
        cur = self.conn.execute(
            """
            INSERT INTO calibration_runs (
                model_name, head_name, version, file_count, timestamp,
                p5, p95, range, reference_version,
                apd_p5, apd_p95, srd, jsd, median_drift, iqr_drift, is_stable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_name,
                head_name,
                version,
                file_count,
                now_ms(),
                p5,
                p95,
                range_val,
                reference_version,
                apd_p5,
                apd_p95,
                srd,
                jsd,
                median_drift,
                iqr_drift,
                1 if is_stable else 0,
            ),
        )
        self.conn.commit()
        row_id = cur.lastrowid
        if row_id is None:
            raise RuntimeError("Failed to insert calibration run - no row ID returned")
        return row_id

    def get_latest_calibration_run(self, model_name: str, head_name: str) -> dict[str, Any] | None:
        """
        Get the most recent calibration run for a model/head.

        Args:
            model_name: Model identifier
            head_name: Head identifier

        Returns:
            Calibration run dict or None if no runs exist
        """
        cur = self.conn.execute(
            """
            SELECT * FROM calibration_runs
            WHERE model_name=? AND head_name=?
            ORDER BY version DESC
            LIMIT 1
            """,
            (model_name, head_name),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def get_reference_calibration_run(self, model_name: str, head_name: str) -> dict[str, Any] | None:
        """
        Get the current reference (stable) calibration run for a model/head.

        The reference is the most recent stable calibration that new runs are compared against.

        Args:
            model_name: Model identifier
            head_name: Head identifier

        Returns:
            Reference calibration run dict or None if no stable runs exist
        """
        cur = self.conn.execute(
            """
            SELECT * FROM calibration_runs
            WHERE model_name=? AND head_name=? AND is_stable=1
            ORDER BY version DESC
            LIMIT 1
            """,
            (model_name, head_name),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def list_calibration_runs(
        self, model_name: str | None = None, head_name: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        List calibration runs with optional filtering.

        Args:
            model_name: Filter by model (optional)
            head_name: Filter by head (optional)
            limit: Maximum number of results

        Returns:
            List of calibration run dicts, ordered by timestamp DESC
        """
        where_clauses = []
        params: list[Any] = []

        if model_name:
            where_clauses.append("model_name=?")
            params.append(model_name)
        if head_name:
            where_clauses.append("head_name=?")
            params.append(head_name)

        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
        params.append(limit)

        cur = self.conn.execute(
            f"SELECT * FROM calibration_runs WHERE {where_clause} ORDER BY timestamp DESC LIMIT ?", params
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]
