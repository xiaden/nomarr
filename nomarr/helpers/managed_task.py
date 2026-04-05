"""Managed background task definition."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ManagedTask:
    """Configuration for a managed background task."""

    task_id: str
    fn: Callable[[], Any]
    stop_event: threading.Event = field(default_factory=threading.Event)
    on_complete: Callable[[], None] | None = None
    daemon: bool = True
