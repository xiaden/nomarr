"""Persistence layer — PostgreSQL database access and schema definitions.

Provides type-safe access to the PostgreSQL database using SQLAlchemy.
All database operations flow through this layer; layers above (interfaces,
services, workflows) must never access the database directly.

Key exports (lazy-imported via ``__getattr__`` for boot-time performance):

- ``Database`` — Top-level database handle (connections, version management)
- ``DuplicateKeyError`` — Custom exception for unique-constraint violations (deprecated)
- ``EntityNotFoundError`` — Raised when a query returns no result (pgcode 02000)
- ``DuplicateEntityError`` — Raised on uniqueness violations (pgcode 23505)
- ``ReferentialIntegrityError`` — Raised on foreign-key violations (pgcode 23503)
- ``DatabaseStateError`` — Raised for unknown database errors or operational failures

Internal structure:

- ``api/`` — Domain-oriented persistence surfaces (LibraryDb, AppDb, MlDb)
- ``database/`` — Repository classes organized by domain/table
- ``models/`` — SQLAlchemy ORM models
- ``db.py`` — Database class (connect, version, lifecycle)
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "Database",
    "DatabaseStateError",
    "DuplicateEntityError",
    "DuplicateKeyError",
    "EntityNotFoundError",
    "ReferentialIntegrityError",
]


def __getattr__(name: str) -> Any:
    if name == "Database":
        from .db import Database

        return Database
    if name == "DuplicateKeyError":
        from .exceptions import DuplicateKeyError

        return DuplicateKeyError
    if name == "DuplicateEntityError":
        from nomarr.helpers.exceptions import DuplicateEntityError

        return DuplicateEntityError
    if name == "EntityNotFoundError":
        from nomarr.helpers.exceptions import EntityNotFoundError

        return EntityNotFoundError
    if name == "ReferentialIntegrityError":
        from nomarr.helpers.exceptions import ReferentialIntegrityError

        return ReferentialIntegrityError
    if name == "DatabaseStateError":
        from nomarr.helpers.exceptions import DatabaseStateError

        return DatabaseStateError
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
