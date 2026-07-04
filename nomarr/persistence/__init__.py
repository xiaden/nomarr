"""Persistence layer — ArangoDB database access and schema definitions.

Provides type-safe access to the ArangoDB graph database using AQL queries.
All database operations flow through this layer; layers above (interfaces,
services, workflows) must never access ArangoDB directly.

Key exports (lazy-imported via ``__getattr__`` for boot-time performance):

- ``Database`` — Top-level database handle (connections, version management)
- ``DuplicateKeyError`` — Custom exception for unique-constraint violations

Internal structure:

- ``api/`` — Domain-oriented persistence surfaces (LibraryDb, AppDb, MlDb)
- ``aql/`` — Reusable AQL query primitives (execute, upsert, delete, etc.)
- ``database/`` — AQL operation classes organized by collection/domain
- ``models/`` — ArangoDB document and edge base classes
- ``schema/`` — Collection and index DDL definitions
- ``arango_client.py`` — ArangoDB client factory with safe DB wrapper
- ``db.py`` — Database class (connect, version, lifecycle)
"""

from __future__ import annotations

from typing import Any

__all__ = ["Database", "DuplicateKeyError"]


def __getattr__(name: str) -> Any:
    if name == "Database":
        from .db import Database

        return Database
    if name == "DuplicateKeyError":
        from .exceptions import DuplicateKeyError

        return DuplicateKeyError
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
