"""Worker crash handling component - restart decision logic.

Pure decision functions for determining when to restart vs mark failed.
Contains no state, only logic based on inputs (restart counts, timestamps, config).

Architecture:
- No imports from services layer
- Uses only stdlib, typing, and helpers
- All functions are pure (no side effects except logging)
- WorkerSystemService delegates restart decisions to this component
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

# Restart policy constants
MAX_RESTARTS_IN_WINDOW = 5  # Rapid restart limit (short window)
RESTART_WINDOW_MS = 5 * 60 * 1000  # 5 minutes in milliseconds
MAX_LIFETIME_RESTARTS = 20  # Total restart limit (long window, catches slow thrashing)
MAX_BACKOFF_SECONDS = 60  # Maximum exponential backoff delay

# Restart decision result type
RestartAction = Literal["restart", "mark_failed"]


@dataclass(frozen=True)
class RestartDecision:
    """Result of restart decision logic.

    Attributes:
        action: What to do - "restart" or "mark_failed"
        reason: Human-readable explanation of decision
        backoff_seconds: If action=restart, how long to wait before restarting
        failure_reason: If action=mark_failed, detailed failure explanation for metadata

    """

    action: RestartAction
    reason: str
    backoff_seconds: int = 0
    failure_reason: str | None = None


def should_restart_worker(
    restart_count: int,
    last_restart_ms: int | None,
    *,
    max_short_window: int = MAX_RESTARTS_IN_WINDOW,
    short_window_ms: int = RESTART_WINDOW_MS,
    max_lifetime: int = MAX_LIFETIME_RESTARTS,
    max_backoff: int = MAX_BACKOFF_SECONDS,
) -> RestartDecision:
    """Decide whether to restart a worker or mark it as permanently failed.

    Implements two-tier restart limiting:
    1. Short window: Prevent restart loops (e.g., 5 restarts in 5 minutes)
    2. Long window: Catch slow thrashing (e.g., 20 lifetime restarts)

    This catches both rapid crashes (OOM, invalid config) and slow resource
    pressure (worker killed every 10 minutes due to memory/GPU saturation).

    Args:
        restart_count: Current restart counter for this worker
        last_restart_ms: Timestamp (ms) of most recent restart, or None if never restarted
        max_short_window: Max restarts allowed in short window (default: 5)
        short_window_ms: Short window duration in milliseconds (default: 5 minutes)
        max_lifetime: Max total restarts before marking failed (default: 20)
        max_backoff: Maximum backoff delay in seconds (default: 60)

    Returns:
        RestartDecision with action, reason, and backoff/failure details

    Examples:
        # First crash - restart immediately
        >>> should_restart_worker(restart_count=0, last_restart_ms=None)
        RestartDecision(action='restart', reason='...', backoff_seconds=1)

        # 5 rapid restarts in 2 minutes - mark failed
        >>> now = int(time.time() * 1000)
        >>> should_restart_worker(restart_count=5, last_restart_ms=now - 120_000)
        RestartDecision(action='mark_failed', reason='...', failure_reason='...')

        # 20 total restarts over 2 hours - mark failed (slow thrashing)
        >>> should_restart_worker(restart_count=20, last_restart_ms=now - 7200_000)
        RestartDecision(action='mark_failed', reason='...', failure_reason='...')

    """
    now_ms = int(time.time() * 1000)

    # Check long-window limit first (catches slow resource pressure)
    if restart_count >= max_lifetime:
        failure_msg = (
            f"Worker exceeded lifetime restart limit ({restart_count} >= {max_lifetime} total restarts). "
            f"This indicates persistent resource pressure or configuration issues. "
            f"Check logs for OOM kills, GPU memory issues, or repeated crashes."
        )
        logger.warning(
            f"Worker restart limit reached: {restart_count} >= {max_lifetime} lifetime restarts. Marking as failed.",
        )
        return RestartDecision(
            action="mark_failed",
            reason=f"Exceeded {max_lifetime} lifetime restarts",
            failure_reason=failure_msg,
        )

    # Check short-window limit (catches rapid restart loops)
    if last_restart_ms is not None:
        time_since_last_restart_ms = now_ms - last_restart_ms
        is_in_short_window = time_since_last_restart_ms < short_window_ms

        if restart_count >= max_short_window and is_in_short_window:
            window_minutes = short_window_ms / 1000 / 60
            failure_msg = (
                f"Worker exceeded rapid restart limit ({restart_count} restarts in {window_minutes:.1f} minutes). "
                f"This indicates a crash loop. Check worker logs for errors."
            )
            logger.warning(
                f"Worker rapid restart limit reached: {restart_count} restarts in "
                f"{time_since_last_restart_ms / 1000:.1f}s. Marking as failed.",
            )
            return RestartDecision(
                action="mark_failed",
                reason=f"Exceeded {max_short_window} restarts in {window_minutes:.0f} minutes",
                failure_reason=failure_msg,
            )

    # Worker is below both thresholds - restart with exponential backoff
    backoff = calculate_backoff(restart_count, max_backoff=max_backoff)

    logger.info(
        f"Worker restart allowed (count={restart_count}, backoff={backoff}s, "
        f"lifetime_limit={max_lifetime}, short_window_limit={max_short_window})",
    )

    return RestartDecision(
        action="restart",
        reason=f"Restart #{restart_count + 1} with {backoff}s backoff",
        backoff_seconds=backoff,
    )


def calculate_backoff(restart_count: int, max_backoff: int = MAX_BACKOFF_SECONDS) -> int:
    """Calculate exponential backoff delay for worker restart.

    Backoff sequence: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max), 60s, ...

    Args:
        restart_count: Number of times worker has restarted
        max_backoff: Maximum backoff delay in seconds (default: 60)

    Returns:
        Backoff delay in seconds (always >= 1, capped at max_backoff)

    Examples:
        >>> calculate_backoff(0)
        1
        >>> calculate_backoff(3)
        8
        >>> calculate_backoff(10)
        60

    """
    # Ensure minimum 1 second backoff, then exponential up to max
    return int(max(1, min(2**restart_count, max_backoff)))
