"""Map SQLAlchemy exceptions to persistence-layer domain exceptions.

Translates engine-specific SQLAlchemy errors into the storage-agnostic
exceptions defined in ``nomarr.persistence.exceptions`` so callers above
the persistence boundary never see SQLAlchemy types.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from nomarr.persistence.exceptions import DuplicateKeyError, PersistenceError


def map_sqlalchemy_error(exc: SQLAlchemyError) -> PersistenceError:
    """Convert a SQLAlchemy exception into the appropriate domain exception.

    Args:
        exc: The SQLAlchemy exception caught during a database operation.

    Returns:
        A ``DuplicateKeyError`` for integrity-constraint violations,
        or a generic ``PersistenceError`` for all other SQLAlchemy errors.

    """
    if isinstance(exc, IntegrityError):
        return DuplicateKeyError(str(exc))
    return PersistenceError(str(exc))
