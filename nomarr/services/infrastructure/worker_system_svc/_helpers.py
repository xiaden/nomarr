"""Shared constants for the worker system service subpackage."""

from __future__ import annotations

from nomarr.helpers.dto.health_dto import ComponentPolicy

DEFAULT_HEARTBEAT_TIMEOUT_MS = 30_000
DEFAULT_WORKER_POLICY = ComponentPolicy(
    startup_timeout_s=60.0,
    staleness_interval_s=9.0,
    max_consecutive_misses=3,
    min_recovery_s=5.0,
    max_recovery_s=120.0,
)
WORKER_STAGGER_DELAY_S = 2.0
