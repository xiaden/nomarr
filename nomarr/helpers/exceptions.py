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
    """Raised when a library row cannot be found by its ID."""


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


class EntityNotFoundError(Exception):
    """Raised when a database query returns no result (pgcode 02000 no_data)."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message)


class DuplicateEntityError(Exception):
    """Raised when an insert violates a uniqueness constraint (pgcode 23505 unique_violation)."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message)


class ReferentialIntegrityError(Exception):
    """Raised when a foreign key constraint is violated (pgcode 23503 foreign_key_violation)."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message)


class DatabaseStateError(Exception):
    """Raised for unknown database errors, operational failures, or unrecognized pgcodes."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message)
