"""
Health table operations for worker/app heartbeat monitoring.

SCHEMA AND INVARIANTS
=====================

The health table is ephemeral and tracks liveness of the application and workers.
It is cleaned on app startup/shutdown and rebuilt dynamically at runtime.

Table structure (see db.py for CREATE TABLE):
- component: TEXT PRIMARY KEY (unique per component, e.g., "app", "worker:tag:0")
- last_heartbeat: INTEGER NOT NULL (timestamp_ms, updated on every heartbeat)
- status: TEXT NOT NULL (lifecycle status, see below)
- restart_count: INTEGER DEFAULT 0 (incremented on each restart)
- last_restart: INTEGER (timestamp_ms of last restart, NULL if never restarted)
- pid: INTEGER (process ID, NULL if process not running)
- current_job: INTEGER (job ID being processed, workers only, NULL if idle)
- exit_code: INTEGER (exit code if stopped/crashed, NULL if running)
- metadata: TEXT (JSON string with extra info, NULL if no metadata)

INVARIANT: Each component owns exactly ONE row (enforced by PRIMARY KEY).

STATUS LIFECYCLE
================

Allowed status values and their meanings:

- "starting": Component is starting up, not yet ready to process work
  - Used when process first spawns, before main loop begins
  - App: Written once on startup, then transitions to "healthy"
  - Workers: Written in BaseWorker.run() before entering main loop

- "healthy": Component is running normally and heartbeat is current
  - Used during normal operation (periodic heartbeat updates)
  - Should be accompanied by recent last_heartbeat (< max_age_ms)

- "stopping": Component is shutting down gracefully
  - Used when stop() is called and component is cleaning up
  - Workers: Written in BaseWorker.run() finally block
  - App: Written in Application.stop()

- "failed": Component failed and will not auto-restart
  - Used when restart limit exceeded or manual failure marking
  - Includes metadata with failure reason
  - Requires manual intervention (reset_restart_count) to recover

- "crashed": Component crashed unexpectedly (non-zero exit_code)
  - Used by WorkerSystemService when detecting process death
  - Includes exit_code and metadata with error details
  - Will be restarted if restart limit not exceeded

OWNERSHIP AND USAGE
===================

Application (app.py):
- Calls clean_all() on startup/shutdown to reset ephemeral state
- Writes own heartbeat: mark_starting("app", pid) on startup
- Periodic: update_heartbeat("app") every 5s with status="healthy"
- On shutdown: mark_stopping("app") before cleanup

WorkerSystemService (worker_system_svc.py):
- Monitors worker health via is_healthy() checks
- Marks workers as crashed: mark_crashed(component, exit_code, error_msg)
- Increments restart counts: increment_restart_count(component)
- Marks workers as failed: mark_failed(component, "restart limit exceeded")
- Reads restart_count/last_restart to implement exponential backoff

BaseWorker (workers/base.py):
- Marks self as starting: mark_starting(component_id, pid) in run()
- Periodic: update_heartbeat(component_id, current_job=job_id) every 5s
- On shutdown: mark_stopping(component_id) in finally block

StateBroker and domain services:
- Read-only: get_all_workers() for status reporting
- Use is_healthy(component, max_age_ms) for liveness checks

CONCURRENCY
===========

This module is safe for concurrent use from multiple processes:
- SQLite in WAL mode with short transactions
- All writes use INSERT ... ON CONFLICT or UPDATE with explicit WHERE clauses
- No shared state or module-level globals
- Callers handle exceptions and logging (no logging in persistence layer)

ERROR HANDLING
==============

All methods raise on database errors (no silent failures).
Callers are responsible for exception handling and logging.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


class HealthOperations:
    """
    Operations for health monitoring table.

    Provides a focused set of helpers for managing component health records.
    All methods use proper UPSERT semantics to maintain one row per component.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------------------------- Write Helpers ----------------------------

    def upsert_component(
        self,
        component: str,
        status: str,
        *,
        pid: int | None = None,
        current_job: int | None = None,
        exit_code: int | None = None,
        metadata: str | None = None,
        restart_count: int | None = None,
        last_restart: int | None = None,
    ) -> None:
        """
        Upsert a component health record with explicit control over all fields.

        This is the low-level primitive used by higher-level helpers.
        Updates last_heartbeat to current timestamp automatically.

        Args:
            component: Component ID (e.g., "app", "worker:tag:0")
            status: Status value ("starting", "healthy", "stopping", "crashed", "failed")
            pid: Process ID (None to leave unchanged)
            current_job: Current job ID for workers (None to leave unchanged)
            exit_code: Exit code if stopped/crashed (None to leave unchanged)
            metadata: JSON string with extra info (None to leave unchanged)
            restart_count: Restart counter (None to leave unchanged)
            last_restart: Timestamp_ms of last restart (None to leave unchanged)

        Raises:
            sqlite3.Error: On database errors
        """
        now_ms = int(time.time() * 1000)

        # Build UPDATE clause for ON CONFLICT - only update specified fields
        update_clauses = ["last_heartbeat=excluded.last_heartbeat", "status=excluded.status"]
        if pid is not None:
            update_clauses.append("pid=excluded.pid")
        if current_job is not None:
            update_clauses.append("current_job=excluded.current_job")
        if exit_code is not None:
            update_clauses.append("exit_code=excluded.exit_code")
        if metadata is not None:
            update_clauses.append("metadata=excluded.metadata")
        if restart_count is not None:
            update_clauses.append("restart_count=excluded.restart_count")
        if last_restart is not None:
            update_clauses.append("last_restart=excluded.last_restart")

        update_clause = ", ".join(update_clauses)

        self.conn.execute(
            f"""
            INSERT INTO health (component, last_heartbeat, status, pid, current_job, exit_code, metadata, restart_count, last_restart)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(component) DO UPDATE SET {update_clause}
            """,
            (
                component,
                now_ms,
                status,
                pid,
                current_job,
                exit_code,
                metadata,
                restart_count if restart_count is not None else 0,
                last_restart,
            ),
        )
        self.conn.commit()

    def update_heartbeat(
        self,
        component: str,
        status: str = "healthy",
        current_job: int | None = None,
    ) -> None:
        """
        Update heartbeat timestamp for a component (typical periodic update).

        Only updates last_heartbeat, status, and optionally current_job.
        Does NOT touch pid, exit_code, metadata, or restart counters.

        Args:
            component: Component ID
            status: Status value (default: "healthy")
            current_job: Current job ID for workers (None to leave unchanged)

        Raises:
            sqlite3.Error: On database errors
        """
        now_ms = int(time.time() * 1000)

        if current_job is not None:
            self.conn.execute(
                """
                UPDATE health
                SET last_heartbeat = ?,
                    status = ?,
                    current_job = ?
                WHERE component = ?
                """,
                (now_ms, status, current_job, component),
            )
        else:
            self.conn.execute(
                """
                UPDATE health
                SET last_heartbeat = ?,
                    status = ?
                WHERE component = ?
                """,
                (now_ms, status, component),
            )

        self.conn.commit()

    def mark_starting(self, component: str, pid: int) -> None:
        """
        Mark a component as starting.

        Used when a process first spawns, before entering main loop.
        Creates or updates the health record with status="starting".

        Args:
            component: Component ID
            pid: Process ID

        Raises:
            sqlite3.Error: On database errors
        """
        self.upsert_component(
            component=component,
            status="starting",
            pid=pid,
            current_job=None,
            exit_code=None,
            metadata=None,
        )

    def mark_healthy(self, component: str, pid: int | None = None) -> None:
        """
        Mark a component as healthy.

        Used when transitioning from "starting" to "healthy" after initialization,
        or for periodic heartbeat updates.

        Args:
            component: Component ID
            pid: Process ID (optional, use if updating PID)

        Raises:
            sqlite3.Error: On database errors
        """
        if pid is not None:
            self.upsert_component(component=component, status="healthy", pid=pid)
        else:
            self.update_heartbeat(component=component, status="healthy")

    def mark_stopping(self, component: str, exit_code: int = 0) -> None:
        """
        Mark a component as gracefully stopping.

        Used when stop() is called and component is cleaning up.

        Args:
            component: Component ID
            exit_code: Exit code (default: 0 for clean shutdown)

        Raises:
            sqlite3.Error: On database errors
        """
        now_ms = int(time.time() * 1000)
        self.conn.execute(
            """
            UPDATE health
            SET last_heartbeat = ?,
                status = ?,
                exit_code = ?
            WHERE component = ?
            """,
            (now_ms, "stopping", exit_code, component),
        )
        self.conn.commit()

    def mark_crashed(self, component: str, exit_code: int, metadata: str | None = None) -> None:
        """
        Mark a component as crashed with exit code.

        Used by WorkerSystemService when detecting unexpected process termination.

        Args:
            component: Component ID
            exit_code: Non-zero exit code
            metadata: Optional error message or JSON details

        Raises:
            sqlite3.Error: On database errors
        """
        now_ms = int(time.time() * 1000)
        self.conn.execute(
            """
            UPDATE health
            SET last_heartbeat = ?,
                status = ?,
                exit_code = ?,
                metadata = ?
            WHERE component = ?
            """,
            (now_ms, "crashed", exit_code, metadata, component),
        )
        self.conn.commit()

    def mark_failed(self, component: str, metadata: str) -> None:
        """
        Mark a component as permanently failed (will not auto-restart).

        Used when restart limit exceeded or manual failure marking.
        Requires manual intervention (reset_restart_count) to recover.

        Uses retry logic to ensure critical failure state is persisted even
        if database is temporarily locked.

        Args:
            component: Component ID
            metadata: Failure reason (e.g., "restart limit exceeded")

        Raises:
            sqlite3.Error: On database errors (after retries)
        """
        from nomarr.persistence.database.shared_sql import retry_on_locked

        def _mark_failed_internal():
            now_ms = int(time.time() * 1000)
            self.conn.execute(
                """
                UPDATE health
                SET last_heartbeat = ?,
                    status = ?,
                    metadata = ?
                WHERE component = ?
                """,
                (now_ms, "failed", metadata, component),
            )
            self.conn.commit()

        retry_on_locked(
            _mark_failed_internal,
            max_retries=5,
            backoff_seconds=1.0,
            operation_name=f"mark_failed({component})",
        )

    def increment_restart_count(self, component: str) -> dict[str, int]:
        """
        Increment restart counter for a component.

        Used by WorkerSystemService when restarting a worker.
        Returns updated restart_count and last_restart for exponential backoff logic.

        Args:
            component: Component ID

        Returns:
            Dict with "restart_count" (int) and "last_restart" (int timestamp_ms)

        Raises:
            sqlite3.Error: On database errors
        """
        now_ms = int(time.time() * 1000)
        self.conn.execute(
            """
            UPDATE health
            SET restart_count = restart_count + 1,
                last_restart = ?
            WHERE component = ?
            """,
            (now_ms, component),
        )
        self.conn.commit()

        # Return updated values
        health = self.get_component(component)
        if health:
            restart_count = health["restart_count"]
            last_restart = health["last_restart"]
            return {
                "restart_count": restart_count if isinstance(restart_count, int) else 0,
                "last_restart": last_restart if isinstance(last_restart, int) else now_ms,
            }
        return {"restart_count": 1, "last_restart": now_ms}

    def reset_restart_count(self, component: str) -> None:
        """
        Reset restart counter for a component (admin operation).

        Used to manually recover a worker marked as permanently failed.

        Args:
            component: Component ID

        Raises:
            sqlite3.Error: On database errors
        """
        self.conn.execute(
            """
            UPDATE health
            SET restart_count = 0,
                last_restart = NULL,
                status = 'stopped',
                exit_code = NULL,
                metadata = NULL
            WHERE component = ?
            """,
            (component,),
        )
        self.conn.commit()

    # ---------------------------- Read Helpers ----------------------------

    def get_component(self, component: str) -> dict[str, str | int | None] | None:
        """
        Get health record for a specific component.

        Args:
            component: Component ID

        Returns:
            Dict with all health fields, or None if component not found

        Raises:
            sqlite3.Error: On database errors
        """
        cursor = self.conn.execute(
            """
            SELECT component, last_heartbeat, status, restart_count, last_restart,
                   pid, current_job, exit_code, metadata
            FROM health
            WHERE component = ?
            """,
            (component,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "component": row[0],
            "last_heartbeat": row[1],
            "status": row[2],
            "restart_count": row[3],
            "last_restart": row[4],
            "pid": row[5],
            "current_job": row[6],
            "exit_code": row[7],
            "metadata": row[8],
        }

    def get_all_workers(self) -> list[dict[str, str | int | None]]:
        """
        Get health records for all workers (excludes app).

        Returns:
            List of health dicts, sorted by component name

        Raises:
            sqlite3.Error: On database errors
        """
        cursor = self.conn.execute(
            """
            SELECT component, last_heartbeat, status, restart_count, last_restart,
                   pid, current_job, exit_code, metadata
            FROM health
            WHERE component LIKE 'worker:%'
            ORDER BY component
            """
        )

        workers = []
        for row in cursor.fetchall():
            workers.append(
                {
                    "component": row[0],
                    "last_heartbeat": row[1],
                    "status": row[2],
                    "restart_count": row[3],
                    "last_restart": row[4],
                    "pid": row[5],
                    "current_job": row[6],
                    "exit_code": row[7],
                    "metadata": row[8],
                }
            )
        return workers

    def get_app_health(self) -> dict[str, str | int | None] | None:
        """
        Get health record for the application.

        Returns:
            Health dict for "app" component, or None if not found

        Raises:
            sqlite3.Error: On database errors
        """
        return self.get_component("app")

    def is_healthy(self, component: str, max_age_ms: int = 30000) -> bool:
        """
        Check if a component is healthy based on status and heartbeat age.

        A component is considered healthy if:
        1. Health record exists
        2. Status is "starting" or "healthy"
        3. last_heartbeat is an integer timestamp
        4. Heartbeat age is less than max_age_ms

        Args:
            component: Component ID to check
            max_age_ms: Maximum age of last heartbeat in milliseconds (default: 30s)

        Returns:
            True if component is healthy, False otherwise

        Raises:
            sqlite3.Error: On database errors
        """
        health = self.get_component(component)
        if not health:
            return False

        # Check status is healthy-ish
        status = health["status"]
        if not isinstance(status, str) or status not in ("healthy", "starting"):
            return False

        # Check heartbeat is recent
        last_heartbeat = health["last_heartbeat"]
        if not isinstance(last_heartbeat, int):
            return False

        now_ms = int(time.time() * 1000)
        age_ms = now_ms - last_heartbeat

        return age_ms < max_age_ms

    # ---------------------------- Cleanup Helpers ----------------------------

    def clean_all(self) -> None:
        """
        Delete all health records (used on app startup/shutdown).

        Only the app should call this method, not workers.

        Raises:
            sqlite3.Error: On database errors
        """
        self.conn.execute("DELETE FROM health")
        self.conn.commit()

    def clean_worker_state(self) -> None:
        """
        Delete all worker-related health records.

        Used for emergency cleanup or testing.

        Raises:
            sqlite3.Error: On database errors
        """
        self.conn.execute("DELETE FROM health WHERE component LIKE 'worker:%'")
        self.conn.commit()
