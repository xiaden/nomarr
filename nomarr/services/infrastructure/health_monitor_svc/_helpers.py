"""Shared dataclasses for the health monitor service subpackage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nomarr.helpers.time_helper import InternalSeconds, internal_s

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from nomarr.helpers.dto.health_dto import (
        ComponentLifecycleHandler,
        ComponentPolicy,
        ComponentStatus,
    )


@dataclass
class HealthMonitorConfig:
    """Configuration for HealthMonitorService."""

    monitor_poll_timeout_s: float = 1.0  # Timeout for pipe polling
    history_snapshot_interval_s: int = 30  # Seconds between DB history writes


@dataclass
class _ComponentState:
    """Internal state tracking for a monitored component."""

    handler: ComponentLifecycleHandler
    pipe_conn: Connection
    policy: ComponentPolicy
    status: ComponentStatus = "pending"
    last_frame_time: InternalSeconds = field(default_factory=internal_s)
    consecutive_misses: int = 0
    startup_deadline: InternalSeconds | None = None
    recovery_deadline: InternalSeconds | None = None
    reported_recover_for_s: float | None = None
