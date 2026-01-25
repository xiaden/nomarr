"""Time utility helpers with type-safe unit handling.

Provides two time domains:
1. Wall-clock time (now_ms, now_s): Real-world timestamps, affected by system clock changes
2. Monotonic time (internal_ms, internal_s): Interval/duration measurements, immune to clock changes

Use wall-clock time for:
- Database timestamps
- Heartbeats
- User-facing "when did this happen"

Use monotonic time for:
- TTL caching
- Timeouts and deadlines
- Backoff calculations
- Elapsed time comparisons
- Staleness detection

Convention:
- Only this module constructs time wrapper types
- Other code passes them around and unwraps with .value for math
- Ruff bans raw time sources (time.time, datetime.now) outside this file
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

# Duration constants (self-documenting)
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
MS_PER_SECOND = 1000
NS_PER_MS = 1_000_000
NS_PER_SECOND = 1_000_000_000


# =============================================================================
# Time wrapper types (frozen dataclasses for runtime enforcement)
# =============================================================================


@dataclass(frozen=True, slots=True)
class Milliseconds:
    """Wall-clock time in milliseconds since epoch."""

    value: int


@dataclass(frozen=True, slots=True)
class Seconds:
    """Wall-clock time in seconds since epoch."""

    value: int


@dataclass(frozen=True, slots=True)
class InternalMilliseconds:
    """Monotonic time in milliseconds (process-relative)."""

    value: int


@dataclass(frozen=True, slots=True)
class InternalSeconds:
    """Monotonic time in seconds (process-relative)."""

    value: int


# Wall-clock time (real-world timestamps, affected by system clock changes)


def now_ms() -> Milliseconds:
    """
    Get current wall-clock timestamp in milliseconds since epoch.

    Use for: Database timestamps, heartbeats, user-facing "when" information.
    Affected by: NTP adjustments, DST changes, manual clock changes.

    Returns:
        Current wall-clock time as integer milliseconds (type-safe)
    """
    return Milliseconds(time.time_ns() // NS_PER_MS)


def now_s() -> Seconds:
    """
    Get current wall-clock timestamp in seconds since epoch.

    Use for: Database timestamps, heartbeats, user-facing "when" information.
    Affected by: NTP adjustments, DST changes, manual clock changes.

    Returns:
        Current wall-clock time as integer seconds (type-safe)
    """
    return Seconds(time.time_ns() // NS_PER_SECOND)


# Monotonic time (interval measurements, immune to system clock changes)


def internal_ms() -> InternalMilliseconds:
    """
    Get current monotonic time in milliseconds.

    Use for: TTL caching, timeouts, backoff, elapsed time, staleness detection.
    Immune to: NTP adjustments, DST changes, manual clock changes.

    Returns:
        Current monotonic time as integer milliseconds (type-safe, distinct from wall-clock Milliseconds)

    Note:
        Only meaningful for computing intervals (internal_ms() - previous_internal_ms()).
        Absolute value has no meaning and should not be persisted.
        Cannot be mixed with wall-clock Milliseconds (enforced by type system).
    """
    return InternalMilliseconds(time.monotonic_ns() // NS_PER_MS)


def internal_s() -> InternalSeconds:
    """
    Get current monotonic time in seconds.

    Use for: TTL caching, timeouts, backoff, elapsed time, staleness detection.
    Immune to: NTP adjustments, DST changes, manual clock changes.

    Returns:
        Current monotonic time as integer seconds (type-safe, distinct from wall-clock Seconds)

    Note:
        Only meaningful for computing intervals (internal_s() - previous_internal_s()).
        Absolute value has no meaning and should not be persisted.
        Cannot be mixed with wall-clock Seconds (enforced by type system).
    """
    return InternalSeconds(time.monotonic_ns() // NS_PER_SECOND)


# =============================================================================
# Unit conversions
# =============================================================================


def ms_to_s(ms: Milliseconds) -> Seconds:
    """Convert wall-clock milliseconds to seconds."""
    return Seconds(ms.value // 1000)


def s_to_ms(secondseconds: Seconds) -> Milliseconds:
    """Convert wall-clock seconds to milliseconds."""
    return Milliseconds(seconds.value * 1000)


def internal_ms_to_s(ms: InternalMilliseconds) -> InternalSeconds:
    """Convert monotonic milliseconds to seconds."""
    return InternalSeconds(ms.value // 1000)


def internal_s_to_ms(seconds: InternalSeconds) -> InternalMilliseconds:
    """Convert monotonic seconds to milliseconds."""
    return InternalMilliseconds(seconds.value * 1000)


# =============================================================================
# Monotonic-to-wall-clock conversion (for display/logging only)
# =============================================================================


def to_wall_ms(internal: InternalMilliseconds) -> Milliseconds:
    """Convert monotonic milliseconds to approximate wall-clock milliseconds.

    Computes the wall-clock equivalent of a monotonic timestamp at this moment.
    Only accurate at the time of call - do NOT store the result.

    Use for logging past events or future deadlines in human-readable form.
    """
    delta = internal.value - internal_ms().value
    return Milliseconds(now_ms().value + delta)


def to_wall_s(internal: InternalSeconds) -> Seconds:
    """Convert monotonic seconds to approximate wall-clock seconds.

    Computes the wall-clock equivalent of a monotonic timestamp at this moment.
    Only accurate at the time of call - do NOT store the result.

    Use for logging past events or future deadlines in human-readable form.
    """
    delta = internal.value - internal_s().value
    return Seconds(now_s().value + delta)


# =============================================================================
# Timestamp formatting for logging
# =============================================================================


def format_wall_timestamp(ms: Milliseconds, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format wall-clock milliseconds as a human-readable timestamp string (UTC)."""
    dt = datetime.fromtimestamp(ms.value / 1000, tz=UTC)
    return dt.strftime(fmt)


def format_wall_timestamp_local(ms: Milliseconds, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format wall-clock milliseconds as a human-readable timestamp in local timezone."""
    dt = datetime.fromtimestamp(ms.value / 1000)  # No tz = local
    return dt.strftime(fmt)


def format_internal_timestamp(internal_ms_val: InternalMilliseconds, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format internal (monotonic) milliseconds as a human-readable timestamp (UTC).

    Converts monotonic time to approximate wall-clock time before formatting.
    Only accurate at the moment of call.
    """
    wall = to_wall_ms(internal_ms_val)
    dt = datetime.fromtimestamp(wall.value / 1000, tz=UTC)
    return dt.strftime(fmt)


def format_internal_timestamp_local(internal_ms_val: InternalMilliseconds, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format internal (monotonic) milliseconds as a timestamp in local timezone.

    Converts monotonic time to approximate wall-clock time before formatting.
    Only accurate at the moment of call.
    """
    wall = to_wall_ms(internal_ms_val)
    dt = datetime.fromtimestamp(wall.value / 1000)  # No tz = local
    return dt.strftime(fmt)
