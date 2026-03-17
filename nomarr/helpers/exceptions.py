"""Custom exceptions used across multiple layers.

Rules:
- Only put exceptions here if they need to be raised in one layer and caught in another.
- Keep exceptions simple and focused.
- No I/O, no config loading, no complex logic.
"""

from __future__ import annotations


class PlaylistQueryError(Exception):
    """Raised when a smart playlist query is invalid or cannot be parsed."""



class LibraryNotFoundError(ValueError):
    """Raised when a library document cannot be found by its ID."""


class LibraryAlreadyScanningError(ValueError):
    """Raised when a scan is requested for a library that is already scanning."""



class PlaylistConversionError(Exception):
    """Raised when playlist conversion fails."""


class SubsonicApiError(Exception):
    """Raised when the Subsonic API returns a non-ok response."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Subsonic error {code}: {message}")
