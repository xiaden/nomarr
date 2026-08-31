"""Workers package - crash handling, restart logic, and discovery components.

In the discovery model, workers select songs via song-state assignments instead
of polling a queue. Songs in the ``not_processed`` state that have no active claim
are available for processing.
"""

from .worker_crash_comp import (
    MAX_BACKOFF_SECONDS,
    MAX_LIFETIME_RESTARTS,
    MAX_RESTARTS_IN_WINDOW,
    RESTART_WINDOW_MS,
    RestartDecision,
    calculate_backoff,
    should_restart_worker,
)
from .worker_discovery_comp import (
    cleanup_stale_claims,
    discover_and_claim_file,
    discover_next_file,
    get_active_claim_count,
)

__all__ = [
    "MAX_BACKOFF_SECONDS",
    "MAX_LIFETIME_RESTARTS",
    "MAX_RESTARTS_IN_WINDOW",
    "RESTART_WINDOW_MS",
    "RestartDecision",
    "calculate_backoff",
    "cleanup_stale_claims",
    "discover_and_claim_file",
    "discover_next_file",
    "get_active_claim_count",
    "should_restart_worker",
]
