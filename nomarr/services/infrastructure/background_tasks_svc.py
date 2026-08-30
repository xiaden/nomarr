"""Background task service for managing long-running operations without workers."""

import logging
import threading
from typing import Any

from nomarr.helpers import ManagedTask
from nomarr.helpers.exceptions import TaskCancelledError

logger = logging.getLogger(__name__)

# Maximum number of task results to keep in memory
MAX_TASK_RESULTS = 100


class BackgroundTaskService:
    """Manages background tasks using threading with same DB connection.

    This service is designed for fast, reliable operations (like library scanning)
    that don't need the isolation of separate worker processes.

    Note: DB is WAL mode, thread uses same connection/writer. This is acceptable
    for alpha. Future refactor will address proper connection pooling.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, tuple[threading.Thread, ManagedTask]] = {}
        self._task_results: dict[str, dict[str, Any]] = {}
        self._task_order: list[str] = []  # Track insertion order for eviction
        self._lock = threading.Lock()

    def _evict_old_results(self) -> None:
        """Remove oldest completed/cancelled/errored results when over limit. Must hold lock."""
        evicted = 0
        while len(self._task_results) > MAX_TASK_RESULTS and self._task_order:
            oldest_id = self._task_order[0]
            result = self._task_results.get(oldest_id)
            # Only evict terminal tasks, never running ones
            if result and result["status"] in ("complete", "cancelled", "error"):
                self._task_order.pop(0)
                del self._task_results[oldest_id]
                if oldest_id in self._tasks:
                    del self._tasks[oldest_id]
                evicted += 1
            else:
                # Running task - move to end of queue and continue checking
                self._task_order.pop(0)
                self._task_order.append(oldest_id)
                # If we've cycled through all tasks without evicting, they're all running
                if evicted == 0 and len(self._task_order) > MAX_TASK_RESULTS:
                    running_count = sum(1 for r in self._task_results.values() if r["status"] == "running")
                    logger.warning(f"Task overload: {running_count} tasks running, exceeds limit of {MAX_TASK_RESULTS}")
                    break

    def start_task(self, task: ManagedTask) -> str:
        """Start a background task and return task_id.

        Args:
            task: Managed task configuration

        Returns:
            Task ID for status checking

        Raises:
            ValueError: If a task with the given task_id is already running.
            Exception: Re-raises task exceptions to crash container (loud failure).

        """
        task_id = task.task_id

        def wrapper() -> None:
            try:
                result = task.fn()
            except TaskCancelledError as cancelled:
                logger.info("Task %s cancelled: %s", task_id, cancelled)
                with self._lock:
                    self._task_results[task_id] = {
                        "status": "cancelled",
                        "result": cancelled.result,
                        "error": None,
                    }
                return
            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}", exc_info=True)
                with self._lock:
                    self._task_results[task_id] = {
                        "status": "error",
                        "result": None,
                        "error": str(e),
                    }
                # Re-raise to crash container (loud failure for alpha)
                raise

            # A task is only "complete" once its required completion callback
            # has succeeded. Running the callback first means a failure cannot
            # publish a false "complete" terminal state.
            if task.on_complete is not None:
                try:
                    task.on_complete()
                except Exception as e:
                    logger.error("Task %s completion callback failed: %s", task_id, e, exc_info=True)
                    with self._lock:
                        self._task_results[task_id] = {
                            "status": "error",
                            "result": result,
                            "error": f"on_complete failed: {e}",
                        }
                    return

            with self._lock:
                self._task_results[task_id] = {
                    "status": "complete",
                    "result": result,
                    "error": None,
                }

        thread = threading.Thread(target=wrapper)
        thread.daemon = task.daemon

        with self._lock:
            existing = self._tasks.get(task_id)
            if existing is not None and existing[0].is_alive():
                raise ValueError(f"Task {task_id!r} is already running")

            self._tasks[task_id] = (thread, task)
            self._task_results[task_id] = {
                "status": "running",
                "result": None,
                "error": None,
            }
            if task_id in self._task_order:
                self._task_order.remove(task_id)
            self._task_order.append(task_id)
            self._evict_old_results()

        thread.start()

        return task_id

    def cancel_task(self, task_id: str) -> bool:
        """Signal a running task to stop cooperatively.

        Args:
            task_id: Task identifier

        Returns:
            True if the task was running and was signaled
            False if the task was missing or not running

        """
        with self._lock:
            entry = self._tasks.get(task_id)
            if entry is None:
                return False

            thread, managed_task = entry
            if not thread.is_alive():
                return False

            managed_task.stop_event.set()
            return True

    def cancel_and_join(self, task_id: str, timeout: float | None = None) -> bool:
        """Signal a running task to stop and wait for it to finish.

        Cooperatively sets the task's ``stop_event`` and joins its thread so
        callers can guarantee the task — including its ``on_complete`` callback —
        has fully finished before continuing (e.g. before deleting the resource
        the task operates on).

        Args:
            task_id: Task identifier.
            timeout: Maximum seconds to wait for the task to finish. ``None``
                waits indefinitely.

        Returns:
            True when the task is no longer running (it was never started,
            already finished, or finished within ``timeout`` after being
            signalled). False when the task is still running after ``timeout``
            elapsed.

        """
        with self._lock:
            entry = self._tasks.get(task_id)
            if entry is None:
                return True
            thread, managed_task = entry
            if not thread.is_alive():
                return True
            managed_task.stop_event.set()
        thread.join(timeout)
        return not thread.is_alive()

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """Get task status (running, complete, cancelled, error).

        Args:
            task_id: Task identifier

        Returns:
            Status dict with keys: status, result, error
            None if task not found

        """
        with self._lock:
            return self._task_results.get(task_id)

    def list_tasks(self) -> list[str]:
        """List all task IDs in order (oldest first).

        Returns:
            List of task identifiers

        """
        with self._lock:
            return list(self._task_order)

    def cleanup_completed_tasks(self, max_count: int = 10) -> int:
        """Remove oldest completed/cancelled/errored tasks.

        Args:
            max_count: Maximum number of tasks to remove per call

        Returns:
            Number of tasks cleaned up

        """
        with self._lock:
            removed = 0
            rotated_without_removal = 0
            while removed < max_count and self._task_order:
                oldest_id = self._task_order[0]
                result = self._task_results.get(oldest_id)
                if result and result["status"] in ("complete", "cancelled", "error"):
                    self._task_order.pop(0)
                    del self._task_results[oldest_id]
                    if oldest_id in self._tasks:
                        del self._tasks[oldest_id]
                    removed += 1
                    rotated_without_removal = 0
                else:
                    # Running task - move to end and continue.
                    self._task_order.pop(0)
                    self._task_order.append(oldest_id)
                    rotated_without_removal += 1
                    # Avoid infinite loop if we have cycled through the remaining
                    # queue without finding a removable task.
                    if rotated_without_removal >= len(self._task_order):
                        break
            return removed
