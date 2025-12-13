"""Path validation DTOs for secure filesystem operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidatedPath:
    """
    A filesystem path that has been validated for security and existence.

    This DTO proves that a path has gone through proper validation:
    - Security: validated against library root (prevents path traversal)
    - Existence: file exists and is accessible
    - Type: confirmed as a file (not directory)

    Construction should only happen after calling validate_library_path()
    or equivalent validation function. The frozen=True prevents mutation.

    Persistence layer accepts ValidatedPath instead of raw strings,
    making it impossible to pass unvalidated paths through the type system.
    """

    path: str
