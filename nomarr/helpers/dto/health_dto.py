"""Health-related DTOs and types used across layers.

This module contains the status contract and callback protocols for health monitoring.

## Health Monitoring Contract

### Status Model

| Status      | Set by        | Meaning                                      |
|-------------|---------------|----------------------------------------------|
| pending     | HealthMonitor | Waiting for first frame after registration   |
| healthy     | HealthMonitor | Receiving healthy frames                     |
| unhealthy   | HealthMonitor | Missed 1+ staleness checks                   |
| recovering  | HealthMonitor | Component requested recovery window          |
| dead        | HealthMonitor | Intervention needed (timeout/misses/EOF)     |
| failed      | Domain        | Permanent, not restarting                    |

### Key Rules

1. A frame with status="healthy" resets consecutive misses and transitions to healthy;
   any other frame does not.

2. Calling set_failed permanently transitions the component to failed; no further
   health checks, callbacks, or state transitions occur.

3. EOF on pipe → dead (from any state except failed).
"""

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

# The six allowed statuses for health monitoring.
ComponentStatus = Literal["pending", "healthy", "unhealthy", "recovering", "dead", "failed"]


@dataclass
class ComponentPolicy:
    """Monitoring policy parameters for a component.

    Provided by domain on registration to configure health monitoring behavior.
    """

    startup_timeout_s: float = 30.0
    """Max time to wait for first frame before marking dead."""

    staleness_interval_s: float = 5.0
    """How often to check for frames (health check interval)."""

    max_consecutive_misses: int = 3
    """Number of consecutive misses before marking dead."""

    min_recovery_s: float = 5.0
    """Floor for recovery window (component cannot request less)."""

    max_recovery_s: float = 60.0
    """Cap for recovery window (component cannot request more)."""


@dataclass
class StatusChangeContext:
    """Context provided with status change callbacks.

    Contains additional information about the status transition.
    """

    consecutive_misses: int = 0
    """Number of consecutive staleness misses (for unhealthy transitions)."""

    recovery_deadline: float | None = None
    """When recovering expires (absolute time), if status is recovering."""

    reported_recover_for_s: float | None = None
    """What component requested for recovery duration (before clamping)."""


@runtime_checkable
class ComponentLifecycleHandler(Protocol):
    """Protocol for handlers that receive lifecycle events from HealthMonitor.

    Domain services implement this to receive callbacks when component status changes.
    HealthMonitor owns status tracking; domain owns restart/backoff/failure decisions.
    """

    def on_status_change(
        self,
        component_id: str,
        old_status: ComponentStatus,
        new_status: ComponentStatus,
        context: StatusChangeContext,
    ) -> None:
        """Called on any status transition.

        Args:
            component_id: Unique component identifier (e.g., "worker:tag:0")
            old_status: Previous status
            new_status: New status
            context: Additional context about the transition

        """
        ...
