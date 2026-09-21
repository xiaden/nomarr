"""Custom exceptions used across multiple layers.

Rules:
- Only put exceptions here if they need to be raised in one layer and caught in another.
- Keep exceptions simple and focused.
- No I/O, no config loading, no complex logic.
"""

from __future__ import annotations

import os
from typing import Any

from nomarr.helpers.fs_contract import FsFact  # noqa: TC001 - runtime import required by plan decision D-A2


class PlaylistQueryError(Exception):
    """Raised when a smart playlist query is invalid or cannot be parsed."""


class LibraryNotFoundError(ValueError):
    """Raised when a library row cannot be found by its ID."""


class LibraryAlreadyScanningError(ValueError):
    """Raised when a scan is requested for a library that is already scanning."""


class LibraryOperationConflict(ValueError):  # noqa: N818
    """Raised when a library lifecycle operation cannot be admitted.

    The axis values and hydration count are read inside the persistence-owned
    admission transaction and therefore are authoritative facts for adapters.
    """

    def __init__(
        self,
        operation: str,
        *,
        scan_state: str,
        tag_write_state: str,
        not_hydrated_count: int = 0,
    ) -> None:
        self.operation = operation
        self.scan_state = scan_state
        self.tag_write_state = tag_write_state
        self.not_hydrated_count = not_hydrated_count
        super().__init__(
            f"LibraryOperationConflict: operation {operation!r} conflicts with lifecycle state "
            f"scan_state={scan_state!r}, tag_write_state={tag_write_state!r}, "
            f"not_hydrated={not_hydrated_count}"
        )


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


class RetryableDatabaseError(DatabaseStateError):
    """A transaction may be retried in a fresh repository-owned session."""


class AmbiguousCommitError(DatabaseStateError):
    """Commit outcome is unknown; callers must perform authorized readback."""


class TaskCancelledError(Exception):
    """Raised by a managed task to signal cooperative cancellation.

    The BackgroundTaskService catches this and records a ``cancelled`` terminal
    status instead of ``complete`` (and does not invoke the completion callback).
    ``result`` carries the partial work product produced before cancellation,
    when available.
    """

    def __init__(self, message: str = "Task cancelled", *, result: Any | None = None) -> None:
        self.result = result
        super().__init__(message)


class FilesystemError(ValueError):
    """A filesystem operation failed; carries the structured ``FsFact``.

    Subclassing ``ValueError`` keeps every existing ``except ValueError`` call site
    working while still exposing the structured facts of the failure. The human-readable
    ``message`` must stay generic and client-safe (ADR-037) — it must never embed the
    path or the OS ``strerror`` — while ``.fact`` (and the derived ``.errno``/``.strerror``)
    are server-side only and may be logged.

    Raise sites must use ``raise FilesystemError(message, fact=fact) from exc`` so the
    original ``OSError`` is preserved as ``__cause__`` for diagnosis.
    """

    def __init__(self, message: str, *, fact: FsFact) -> None:
        super().__init__(message)
        self.fact = fact
        self.errno = fact.errno
        self.strerror = os.strerror(fact.errno) if fact.errno is not None else None
