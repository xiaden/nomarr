"""Managed background task definition."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ManagedTask:
    """Configuration for a managed background task.

    Attributes:
        task_id: Identifier used to track the task.
        fn: Callable whose return value becomes the task result.
        stop_event: Cooperative cancellation signal for the task.
        on_complete: Optional callback invoked with the task result after
            successful completion. It is not invoked when the task is cancelled
            before successful completion.
        requested_mode: Optional normalized tag-write mode metadata (``none``,
            ``files``, or ``database``) carried with applicable tasks.
        daemon: Whether the task thread runs as a daemon thread.
    """

    task_id: str
    fn: Callable[[], Any]
    stop_event: threading.Event = field(default_factory=threading.Event)
    on_complete: Callable[[Any], None] | None = None
    requested_mode: str | None = None
    daemon: bool = True
