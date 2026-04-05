"""Unit tests for BackgroundTaskService."""

from __future__ import annotations

import threading

import pytest

from nomarr.helpers import ManagedTask
from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService

pytestmark = pytest.mark.unit


@pytest.fixture
def background_task_service() -> BackgroundTaskService:
    """Provide a fresh BackgroundTaskService instance."""
    return BackgroundTaskService()


def _join_thread(thread: threading.Thread, timeout: float = 1.0) -> None:
    """Join a thread and assert it finished."""
    thread.join(timeout=timeout)
    assert not thread.is_alive()


class TestBackgroundTaskService:
    """Tests for BackgroundTaskService behavior."""

    def test_start_task_reports_running_before_thread_finishes(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """Status should remain running while the task is blocked."""
        task_started = threading.Event()
        allow_finish = threading.Event()

        def task_fn() -> str:
            task_started.set()
            allow_finish.wait(timeout=1.0)
            return "done"

        managed_task = ManagedTask(task_id="task-running", fn=task_fn)
        task_id = background_task_service.start_task(managed_task)
        thread = background_task_service._tasks[task_id][0]

        try:
            assert task_started.wait(timeout=1.0)

            status = background_task_service.get_task_status(task_id)
            assert status == {"status": "running", "result": None, "error": None}
        finally:
            allow_finish.set()
            _join_thread(thread)

        status = background_task_service.get_task_status(task_id)
        assert status == {"status": "complete", "result": "done", "error": None}

    def test_start_task_raises_for_duplicate_running_task_id(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """Starting the same running task twice should fail."""
        task_started = threading.Event()
        allow_finish = threading.Event()

        def blocking_task() -> str:
            task_started.set()
            allow_finish.wait(timeout=1.0)
            return "done"

        first_task = ManagedTask(task_id="duplicate-task", fn=blocking_task)
        task_id = background_task_service.start_task(first_task)
        thread = background_task_service._tasks[task_id][0]

        try:
            assert task_started.wait(timeout=1.0)

            with pytest.raises(ValueError, match="already running"):
                background_task_service.start_task(
                    ManagedTask(task_id="duplicate-task", fn=lambda: "again"),
                )
        finally:
            allow_finish.set()
            _join_thread(thread)

    def test_cancel_task_sets_stop_event_for_running_task(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """cancel_task should signal the managed task's stop event."""
        task_started = threading.Event()
        allow_finish = threading.Event()

        def task_fn() -> str:
            task_started.set()
            allow_finish.wait(timeout=1.0)
            return "cancelled"

        managed_task = ManagedTask(task_id="cancel-task", fn=task_fn)
        task_id = background_task_service.start_task(managed_task)
        thread = background_task_service._tasks[task_id][0]

        try:
            assert task_started.wait(timeout=1.0)
            assert not managed_task.stop_event.is_set()

            assert background_task_service.cancel_task(task_id) is True
            assert managed_task.stop_event.is_set()
        finally:
            allow_finish.set()
            _join_thread(thread)

    def test_cancel_task_returns_false_for_non_running_task(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """cancel_task should return False once the task has finished."""
        managed_task = ManagedTask(task_id="finished-task", fn=lambda: "done")
        task_id = background_task_service.start_task(managed_task)
        thread = background_task_service._tasks[task_id][0]

        _join_thread(thread)

        assert background_task_service.cancel_task(task_id) is False

    def test_cancel_task_returns_false_for_unknown_task(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """cancel_task should return False for a task that was never started."""
        assert background_task_service.cancel_task("never-started") is False

    def test_on_complete_fires_after_success_status_is_written(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """on_complete should run after status is marked complete."""
        callback_statuses: list[str] = []
        callback_called = threading.Event()
        task_id = "callback-success"

        def on_complete() -> None:
            status = background_task_service.get_task_status(task_id)
            assert status is not None
            callback_statuses.append(str(status["status"]))
            callback_called.set()

        managed_task = ManagedTask(
            task_id=task_id,
            fn=lambda: "done",
            on_complete=on_complete,
        )
        started_task_id = background_task_service.start_task(managed_task)
        thread = background_task_service._tasks[started_task_id][0]

        _join_thread(thread)

        assert callback_called.is_set()
        assert callback_statuses == ["complete"]

    def test_on_complete_callback_errors_are_swallowed(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """Task should still complete when on_complete raises an exception."""
        task_id = "callback-raises"

        def on_complete() -> None:
            raise RuntimeError("cb_boom")

        managed_task = ManagedTask(
            task_id=task_id,
            fn=lambda: "done",
            on_complete=on_complete,
        )
        started_task_id = background_task_service.start_task(managed_task)
        thread = background_task_service._tasks[started_task_id][0]

        _join_thread(thread)

        status = background_task_service.get_task_status(task_id)
        assert status is not None
        assert status["status"] == "complete"
        assert status["result"] == "done"
        assert status["error"] is None

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_on_complete_does_not_fire_when_task_errors(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """on_complete should not run when the task fails."""
        callback_calls: list[str] = []
        task_id = "callback-error"

        def failing_task() -> None:
            raise RuntimeError("boom")

        managed_task = ManagedTask(
            task_id=task_id,
            fn=failing_task,
            on_complete=lambda: callback_calls.append("called"),
        )

        started_task_id = background_task_service.start_task(managed_task)
        thread = background_task_service._tasks[started_task_id][0]
        _join_thread(thread)

        assert callback_calls == []
        status = background_task_service.get_task_status(task_id)
        assert status == {"status": "error", "result": None, "error": "boom"}

    def test_task_order_keeps_single_entry_after_repeated_start_complete_cycles(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """_task_order should not accumulate duplicate task IDs across cycles."""
        task_id = "repeat-task"

        for cycle in range(3):

            def task_fn(current_cycle: int = cycle) -> int:
                return current_cycle

            managed_task = ManagedTask(task_id=task_id, fn=task_fn)
            started_task_id = background_task_service.start_task(managed_task)
            thread = background_task_service._tasks[started_task_id][0]
            _join_thread(thread)

            assert background_task_service.list_tasks().count(task_id) == 1
            status = background_task_service.get_task_status(task_id)
            assert status == {"status": "complete", "result": cycle, "error": None}

        assert background_task_service._task_order == [task_id]

    def test_start_task_propagates_daemon_flag_to_thread(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """start_task should honor the ManagedTask daemon setting."""
        task_started = threading.Event()
        allow_finish = threading.Event()

        def task_fn() -> str:
            task_started.set()
            allow_finish.wait(timeout=1.0)
            return "done"

        managed_task = ManagedTask(task_id="daemon-task", fn=task_fn, daemon=False)
        task_id = background_task_service.start_task(managed_task)
        thread = background_task_service._tasks[task_id][0]

        try:
            assert task_started.wait(timeout=1.0)
            assert thread.daemon is False
        finally:
            allow_finish.set()
            _join_thread(thread)


class TestCleanupCompletedTasks:
    """Tests for BackgroundTaskService.cleanup_completed_tasks."""

    def test_removes_completed_tasks_up_to_max_count(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """cleanup_completed_tasks should remove only up to max_count tasks."""
        task_ids = [f"cleanup-complete-{index}" for index in range(3)]

        for task_id in task_ids:

            def task_fn(current_id: str = task_id) -> str:
                return current_id

            started_task_id = background_task_service.start_task(
                ManagedTask(task_id=task_id, fn=task_fn),
            )
            thread = background_task_service._tasks[started_task_id][0]
            _join_thread(thread)

        removed = background_task_service.cleanup_completed_tasks(max_count=2)

        assert removed == 2
        assert background_task_service.list_tasks() == [task_ids[-1]]
        assert background_task_service.get_task_status(task_ids[0]) is None
        assert background_task_service.get_task_status(task_ids[1]) is None
        remaining_status = background_task_service.get_task_status(task_ids[2])
        assert remaining_status == {
            "status": "complete",
            "result": task_ids[2],
            "error": None,
        }

    def test_skips_running_tasks_and_cleans_completed_ones(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """cleanup_completed_tasks should keep running tasks while removing completed ones."""
        task_started = threading.Event()
        allow_finish = threading.Event()

        def blocking_task() -> str:
            task_started.set()
            allow_finish.wait(timeout=1.0)
            return "running-done"

        running_task_id = background_task_service.start_task(
            ManagedTask(task_id="cleanup-running", fn=blocking_task),
        )
        running_thread = background_task_service._tasks[running_task_id][0]

        try:
            assert task_started.wait(timeout=1.0)

            completed_task_id = background_task_service.start_task(
                ManagedTask(task_id="cleanup-complete", fn=lambda: "complete-done"),
            )
            completed_thread = background_task_service._tasks[completed_task_id][0]
            _join_thread(completed_thread)

            removed = background_task_service.cleanup_completed_tasks()

            assert removed == 1
            assert background_task_service.list_tasks() == [running_task_id]
            running_status = background_task_service.get_task_status(running_task_id)
            assert running_status == {
                "status": "running",
                "result": None,
                "error": None,
            }
            assert background_task_service.get_task_status(completed_task_id) is None
        finally:
            allow_finish.set()
            _join_thread(running_thread)

    def test_returns_zero_when_nothing_to_clean(
        self,
        background_task_service: BackgroundTaskService,
    ) -> None:
        """cleanup_completed_tasks should return zero when no tasks are registered."""
        assert background_task_service.cleanup_completed_tasks() == 0
