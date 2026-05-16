"""Persistence-layer domain exceptions.

These exceptions are storage-engine-agnostic. Callers above the persistence
boundary should import and catch only these — never arango-specific exceptions.
"""

from __future__ import annotations


class PersistenceError(RuntimeError):
    """Base class for all persistence-layer errors."""


class DuplicateKeyError(PersistenceError):
    """Raised when an insert violates a uniqueness constraint.

    Equivalent to ArangoDB's ``DocumentInsertError`` (ERR 1210), but expressed
    without reference to the storage engine so callers remain backend-agnostic.
    """
