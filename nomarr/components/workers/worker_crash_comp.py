"""Worker crash handling component - restart decision logic.

Pure decision functions for determining when to restart vs mark failed.
All functions are stateless — no side effects except logging.
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
    """Result of restart decision logic."""

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

    Two-tier limiting: short-window (rapid loops) and long-window (slow thrashing).
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
            "[worker_crash] Worker restart limit reached: %d >= %d lifetime restarts — marking as failed.",
            restart_count,
            max_lifetime,
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
                "[worker_crash] Worker rapid restart limit: %d restarts in %.1fs — marking as failed.",
                restart_count,
                time_since_last_restart_ms / 1000,
            )
            return RestartDecision(
                action="mark_failed",
                reason=f"Exceeded {max_short_window} restarts in {window_minutes:.0f} minutes",
                failure_reason=failure_msg,
            )

    # Worker is below both thresholds - restart with exponential backoff
    backoff = calculate_backoff(restart_count, max_backoff=max_backoff)

    logger.info(
        "[worker_crash] Worker restart allowed (count=%d, backoff=%ds, lifetime_limit=%d, short_window_limit=%d)",
        restart_count,
        backoff,
        max_lifetime,
        max_short_window,
    )

    return RestartDecision(
        action="restart",
        reason=f"Restart #{restart_count + 1} with {backoff}s backoff",
        backoff_seconds=backoff,
    )


def calculate_backoff(restart_count: int, max_backoff: int = MAX_BACKOFF_SECONDS) -> int:
    """Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max), 60s...

    Always >= 1, capped at max_backoff.
    """
    # Ensure minimum 1 second backoff, then exponential up to max
    return int(max(1, min(2**restart_count, max_backoff)))
