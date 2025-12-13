"""Time utility helpers."""

import time


def now_ms() -> int:
    """
    Get current timestamp in milliseconds since epoch.

    Returns:
        Current time as integer milliseconds
    """
    return int(time.time() * 1000)
