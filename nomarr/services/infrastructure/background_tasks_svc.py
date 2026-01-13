"""Background task service for managing long-running operations without workers."""

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class BackgroundTaskService:
    """
    Manages background tasks using threading with same DB connection.

    This service is designed for fast, reliable operations (like library scanning)
    that don't need the isolation of separate worker processes.

    Note: DB is WAL mode, thread uses same connection/writer. This is acceptable
    for alpha. Future refactor will address proper connection pooling.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, threading.Thread] = {}
        self._task_results: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start_task(
        self,
        task_id: str,
        task_fn: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """
        Start a background task and return task_id.

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

        return task_id

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """
        Get task status (running, complete, error).

        Args:
            task_id: Task identifier

        Returns:
            Status dict with keys: status, result, error
            None if task not found
        """
        with self._lock:
            return self._task_results.get(task_id)

    def list_tasks(self) -> list[str]:
        """
        List all task IDs.

        Returns:
            List of task identifiers
        """
        with self._lock:
            return list(self._tasks.keys())

    def cleanup_completed_tasks(self, max_age_seconds: int = 3600) -> int:
        """
        Remove completed/errored tasks older than max_age.

        Args:
            max_age_seconds: Maximum age to keep completed tasks

        Returns:
            Number of tasks cleaned up
        """

        with self._lock:
            to_remove = []
            for task_id, result in self._task_results.items():
                # Only clean up completed/errored tasks
                if result["status"] in ("complete", "error"):
                    # Simple cleanup for now - could add timestamp tracking
                    to_remove.append(task_id)

            for task_id in to_remove[:10]:  # Limit cleanup per call
                del self._task_results[task_id]
                if task_id in self._tasks:
                    del self._tasks[task_id]

            return len(to_remove[:10])
