"""Schema definitions for the Nomarr persistence layer.

This package provides:
- ``CollectionNames`` — every collection name as a ``StrEnum`` (single source of truth)
- ``ddl`` module — collection/index/edge schema definitions consumed by bootstrap
"""

from __future__ import annotations

from .ddl import ALL_COLLECTIONS, CollectionDef, CollectionType, IndexDef, collections_by_type, index_defs
from .names import CollectionNames

__all__ = [
    "ALL_COLLECTIONS",
    "CollectionDef",
    "CollectionNames",
    "CollectionType",
    "IndexDef",
    "collections_by_type",
    "index_defs",
]
