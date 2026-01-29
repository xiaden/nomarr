"""Background task service for managing long-running operations without workers."""

import logging
import threading
from collections.abc import Callable
from typing import Any

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
        self._tasks: dict[str, threading.Thread] = {}
        self._task_results: dict[str, dict[str, Any]] = {}
        self._task_order: list[str] = []  # Track insertion order for eviction
        self._lock = threading.Lock()

    def _evict_old_results(self) -> None:
        """Remove oldest completed/errored results when over limit. Must hold lock."""
        evicted = 0
        while len(self._task_results) > MAX_TASK_RESULTS and self._task_order:
            oldest_id = self._task_order[0]
            result = self._task_results.get(oldest_id)
            # Only evict completed/errored tasks, never running ones
            if result and result["status"] in ("complete", "error"):
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

    def start_task(
        self,
        task_id: str,
        task_fn: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Start a background task and return task_id.

        Args:
            task_id: Unique identifier for the task
            task_fn: Function to execute in background
            *args: Positional arguments for task_fn
            **kwargs: Keyword arguments for task_fn

        Returns:
            Task ID for status checking

        Raises:
            Exception: Re-raises task exceptions to crash container (loud failure)

        """

        def wrapper() -> None:
            try:
                result = task_fn(*args, **kwargs)
                with self._lock:
                    self._task_results[task_id] = {
                        "status": "complete",
                        "result": result,
                        "error": None,
                    }
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

        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()

        with self._lock:
            self._tasks[task_id] = thread
            self._task_results[task_id] = {
                "status": "running",
                "result": None,
                "error": None,
            }
            self._task_order.append(task_id)
            self._evict_old_results()

        return task_id

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """Get task status (running, complete, error).

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
        """Remove oldest completed/errored tasks.

        Args:
            max_count: Maximum number of tasks to remove per call

        Returns:
            Number of tasks cleaned up

        """
        with self._lock:
            removed = 0
            while removed < max_count and self._task_order:
                oldest_id = self._task_order[0]
                result = self._task_results.get(oldest_id)
                if result and result["status"] in ("complete", "error"):
                    self._task_order.pop(0)
                    del self._task_results[oldest_id]
                    if oldest_id in self._tasks:
                        del self._tasks[oldest_id]
                    removed += 1
                else:
                    # Running task - move to end and continue
                    self._task_order.pop(0)
                    self._task_order.append(oldest_id)
                    # Avoid infinite loop if all are running
                    if removed == 0 and len(self._task_order) <= max_count:
                        break
            return removed
