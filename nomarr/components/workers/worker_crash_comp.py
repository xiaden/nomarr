"""Worker crash handling — pure restart-decision logic with no side effects except logging."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

MAX_RESTARTS_IN_WINDOW = 5
RESTART_WINDOW_MS = 5 * 60 * 1000
MAX_LIFETIME_RESTARTS = 20
MAX_BACKOFF_SECONDS = 60

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

    Two-tier limiting: short window for rapid restart loops, long window for slow thrashing.
    Uses exponential backoff on restarts.
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
            "Worker restart limit reached: %d >= %d lifetime restarts. Marking as failed.",
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
                "Worker rapid restart limit reached: %d restarts in %.1fs. Marking as failed.",
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
        "Worker restart allowed (count=%d, backoff=%ds, lifetime_limit=%d, short_window_limit=%d)",
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
    """Calculate exponential backoff delay: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)."""
    return int(max(1, min(2**restart_count, max_backoff)))
