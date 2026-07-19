"""SQL Core primitives and exception mapping for the persistence layer.

Re-exports all eight Tier 1 CRUD primitives, the deprecated synchronous
``map_sqlalchemy_error`` mapper, and the ``map_persistence_exceptions``
context manager so callers can import directly from ``nomarr.persistence.sql``.
"""

from __future__ import annotations

from .exceptions import map_persistence_exceptions, map_sqlalchemy_error
from .primitives import (
    batch_upsert,
    delete_by_key,
    insert_one,
    is_table_empty,
    select_by_key,
    select_many_by_keys,
    update_by_field,
    upsert_by_field,
)

__all__ = [
    "batch_upsert",
    "delete_by_key",
    "insert_one",
    "is_table_empty",
    "map_persistence_exceptions",
    "map_sqlalchemy_error",
    "select_by_key",
    "select_many_by_keys",
    "update_by_field",
    "upsert_by_field",
]
