"""Custom exceptions used across multiple layers.

Rules:
- Only put exceptions here if they need to be raised in one layer and caught in another.
- Keep exceptions simple and focused.
- No I/O, no config loading, no complex logic.
"""

from __future__ import annotations


class PlaylistQueryError(Exception):
    """Raised when a smart playlist query is invalid or cannot be parsed."""

