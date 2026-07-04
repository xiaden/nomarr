"""Health monitor service — component lifecycle monitoring and status tracking.

Provides ``HealthMonitorService`` for tracking component health, lifecycle
states, and status transitions. ``HealthMonitorConfig`` controls polling
intervals and thresholds.
"""

from ._helpers import HealthMonitorConfig, _ComponentState
from .main import HealthMonitorService

__all__ = ["HealthMonitorConfig", "HealthMonitorService", "_ComponentState"]
