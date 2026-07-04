"""Deprecated — use ``nomarr.helpers.exceptions`` instead.

This module was a duplicate of ``exceptions.py`` and has no importers.
All canonical exception definitions live in ``nomarr.helpers.exceptions``.
"""

from __future__ import annotations


class PlaylistQueryError(Exception):
    """Raised when a smart playlist query is invalid or cannot be parsed."""


class LibraryNotFoundError(ValueError):
    """Raised when a library document cannot be found by its ID."""


class LibraryAlreadyScanningError(ValueError):
    """Raised when a scan is requested for a library that is already scanning."""


class MisconfiguredError(ValueError):
    """Raised at request time when a required configuration value is absent or invalid.

    Interfaces should catch this and return HTTP 422.
    """


class PlaylistConversionError(Exception):
    """Raised when playlist conversion fails."""


class SubsonicApiError(Exception):
    """Raised when the Subsonic API returns a non-ok response."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Subsonic error {code}: {message}")
