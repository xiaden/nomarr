"""Persistence-layer domain exceptions.

Legacy persistence-layer exceptions, kept for backward compatibility.
Deprecated — use the domain exceptions in ``nomarr.helpers.exceptions``
(``DatabaseStateError``, ``DuplicateEntityError``, ``EntityNotFoundError``,
``ReferentialIntegrityError``) instead.

.. deprecated::
    ``PersistenceError`` and ``DuplicateKeyError`` are deprecated.
    Use the domain exceptions from ``nomarr.helpers.exceptions`` instead:
    ``DatabaseStateError``, ``DuplicateEntityError``, ``EntityNotFoundError``,
    ``ReferentialIntegrityError``.
"""

from __future__ import annotations

import warnings


class PersistenceError(RuntimeError):
    """Base class for all persistence-layer errors.

    .. deprecated::
        Use :class:`nomarr.helpers.exceptions.DatabaseStateError` instead.
    """

    def __init__(self, *args: object) -> None:
        warnings.warn(
            "PersistenceError is deprecated; use DatabaseStateError from nomarr.helpers.exceptions instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args)


class DuplicateKeyError(PersistenceError):
    """Raised when an insert violates a uniqueness constraint.

    Raised when an INSERT violates a unique constraint (e.g., duplicate key),
    without reference to the storage engine so callers remain storage-engine-agnostic.

    .. deprecated::
        Use :class:`nomarr.helpers.exceptions.DuplicateEntityError` instead.
    """

    def __init__(self, *args: object) -> None:
        warnings.warn(
            "DuplicateKeyError is deprecated; use DuplicateEntityError from nomarr.helpers.exceptions instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Skip PersistenceError.__init__ to avoid double warning
        RuntimeError.__init__(self, *args)
