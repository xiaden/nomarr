"""Small reusable AQL primitives for Nomarr persistence operations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.constructor.verbs import _execute_aql


def execute(
    db: SafeDatabase,
    query: str,
    bind_vars: dict[str, Any],
) -> list[Any]:
    """Execute AQL and materialize the cursor."""
    return list(_execute_aql(db, query, bind_vars=bind_vars))


def normalize_limit(limit: int | None) -> int:
    """Normalize optional limits for AQL LIMIT clauses."""
    return 2**31 - 1 if limit is None else max(0, int(limit))


def get_many_by_keys(db: SafeDatabase, collection: str, keys: Iterable[str]) -> list[dict[str, Any]]:
    """Fetch many docs by `_key` for one collection."""
    key_list = [key for key in keys if isinstance(key, str)]
    if not key_list:
        return []
    query = """
    FOR doc IN @@collection
      FILTER doc._key IN @keys
      RETURN doc
    """
    rows = execute(db, query, {"@collection": collection, "keys": key_list})
    return [row for row in rows if isinstance(row, dict)]


def get_many_by_field(db: SafeDatabase, collection: str, field_name: str, value: Any) -> list[dict[str, Any]]:
    """Fetch many docs by one field."""
    query = """
    FOR doc IN @@collection
      FILTER doc[@field_name] == @value
      RETURN doc
    """
    rows = execute(
        db,
        query,
        {
            "@collection": collection,
            "field_name": field_name,
            "value": value,
        },
    )
    return [row for row in rows if isinstance(row, dict)]


def delete_many_by_keys(db: SafeDatabase, collection: str, keys: Iterable[str]) -> int:
    """Delete many docs by `_key` and return deleted count."""
    key_list = [key for key in keys if isinstance(key, str)]
    if not key_list:
        return 0
    query = """
    FOR doc IN @@collection
      FILTER doc._key IN @keys
      REMOVE doc IN @@collection
      COLLECT WITH COUNT INTO length
      RETURN length
    """
    rows = execute(db, query, {"@collection": collection, "keys": key_list})
    return int(rows[0]) if rows else 0


def upsert_by_field(
    db: SafeDatabase,
    collection: str,
    field_name: str,
    field_value: Any,
    payload: dict[str, Any],
) -> list[str]:
    """Upsert one doc by one field and return inserted/updated ids."""
    query = """
    UPSERT { [@field_name]: @field_value }
      INSERT MERGE({ [@field_name]: @field_value }, @payload)
      UPDATE @payload
      IN @@collection
      RETURN NEW._id
    """
    rows = execute(
        db,
        query,
        {
            "@collection": collection,
            "field_name": field_name,
            "field_value": field_value,
            "payload": payload,
        },
    )
    return [row for row in rows if isinstance(row, str)]
