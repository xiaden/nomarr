"""Map SQLAlchemy exceptions to persistence-layer domain exceptions.

Translates engine-specific SQLAlchemy errors into the storage-agnostic
exceptions defined in ``nomarr.helpers.exceptions`` so callers above
the persistence boundary never see SQLAlchemy types.

The primary translation mechanism is :func:`map_persistence_exceptions`,
a context manager that uses PostgreSQL error codes (pgcodes) to
discriminate between different failure modes.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError, NoResultFound, OperationalError, SQLAlchemyError

from nomarr.helpers.exceptions import (
    DatabaseStateError,
    DuplicateEntityError,
    EntityNotFoundError,
    ReferentialIntegrityError,
)
from nomarr.persistence.exceptions import DuplicateKeyError, PersistenceError

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


@contextmanager
def map_persistence_exceptions() -> Iterator[None]:
    """Translate SQLAlchemy exceptions into domain exceptions.

    Catches SQLAlchemy exceptions raised inside the ``with`` block
    and re-raises the appropriate domain exception from
    ``nomarr.helpers.exceptions``.  The original exception chain is
    suppressed (``from None``) so SQLAlchemy internals never leak to
    callers above the persistence boundary.

    Translation table:

    * ``NoResultFound`` → ``EntityNotFoundError``
    * ``IntegrityError`` with pgcode 23505 (unique_violation) → ``DuplicateEntityError``
    * ``IntegrityError`` with pgcode 23503 (foreign_key_violation) → ``ReferentialIntegrityError``
    * ``IntegrityError`` with unknown/missing pgcode → ``DatabaseStateError`` (logged at WARNING)
    * ``OperationalError`` → ``DatabaseStateError``
    """
    try:
        yield
    except NoResultFound:
        raise EntityNotFoundError("Entity not found") from None
    except IntegrityError as e:
        pgcode = getattr(e.orig, "pgcode", None) if e.orig is not None else None
        if pgcode == "23505":
            raise DuplicateEntityError(f"Duplicate entity: {e}") from None
        if pgcode == "23503":
            raise ReferentialIntegrityError(f"Referential integrity violation: {e}") from None
        logger.warning("IntegrityError with unexpected pgcode=%s: %s", pgcode, e)
        raise DatabaseStateError(f"Database error (pgcode={pgcode}): {e}") from None
    except OperationalError as e:
        raise DatabaseStateError(f"Database operational error: {e}") from None


# ---------------------------------------------------------------------------
# Deprecated: use map_persistence_exceptions() instead.
#
# This synchronous function maps all IntegrityError to DuplicateKeyError
# without pgcode discrimination, which is incorrect for foreign-key and
# check-constraint violations.  It is retained only for callers that have
# not yet migrated to the context manager above.
# ---------------------------------------------------------------------------


def map_sqlalchemy_error(exc: SQLAlchemyError) -> PersistenceError:
    """Convert a SQLAlchemy exception into the appropriate domain exception.

    .. deprecated::
        Use :func:`map_persistence_exceptions` instead.  This function maps
        *all* ``IntegrityError`` exceptions to ``DuplicateKeyError`` without
        inspecting the PostgreSQL error code, which is incorrect for foreign-key
        and check-constraint violations.

    Args:
        exc: The SQLAlchemy exception caught during a database operation.

    Returns:
        A ``DuplicateKeyError`` for integrity-constraint violations,
        or a generic ``PersistenceError`` for all other SQLAlchemy errors.

    """
    if isinstance(exc, IntegrityError):
        return DuplicateKeyError(str(exc))
    return PersistenceError(str(exc))
