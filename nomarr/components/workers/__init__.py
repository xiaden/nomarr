"""Workers package - crash handling, restart logic, and discovery components.

In the discovery model, workers query library_files directly instead of
polling a queue. Files with needs_tagging=1 and no active claim are
available for processing.
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
    claim_file,
    cleanup_stale_claims,
    discover_and_claim_file,
    discover_next_file,
    get_active_claim_count,
    release_claim,
)

__all__ = [
    "MAX_BACKOFF_SECONDS",
    "MAX_LIFETIME_RESTARTS",
    "MAX_RESTARTS_IN_WINDOW",
    "RESTART_WINDOW_MS",
    "RestartDecision",
    "calculate_backoff",
    "claim_file",
    "cleanup_stale_claims",
    "discover_and_claim_file",
    "discover_next_file",
    "get_active_claim_count",
    "release_claim",
    "should_restart_worker",
]
