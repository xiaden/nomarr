"""Small reusable AQL primitives for Nomarr persistence operations."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.constructor.verbs import _execute_aql

_FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def _validate_field_name(field_name: str, *, allowed_fields: set[str] | None = None) -> str:
    """Validate dynamic field names used in bindable AQL templates.

    This pattern allows Arango system fields (for example ``_id``, ``_key``,
    ``_from``, ``_to``). Use ``allowed_fields`` to narrow accepted names for a
    specific query capability.
    """
    if not _FIELD_NAME_PATTERN.fullmatch(field_name):
        raise ValueError(
            f"Invalid field name: {field_name}. Must match pattern ^[A-Za-z_][A-Za-z0-9_]*$"
        )
    if allowed_fields is not None and field_name not in allowed_fields:
        raise ValueError(f"Field '{field_name}' is not allowed")
    return field_name


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


def get_many_by_field(
    db: SafeDatabase,
    collection: str,
    field_name: str,
    value: Any,
    *,
    limit: int | None = None,
    allowed_fields: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch docs by one field with optional field allowlist and limit."""
    safe_field_name = _validate_field_name(field_name, allowed_fields=allowed_fields)
    query = """
    FOR doc IN @@collection
      FILTER doc[@field_name] == @value
      LIMIT @limit
      RETURN doc
    """
    rows = execute(
        db,
        query,
        {
            "@collection": collection,
            "field_name": safe_field_name,
            "value": value,
            "limit": normalize_limit(limit),
        },
    )
    return [row for row in rows if isinstance(row, dict)]


def get_filtered_docs(
    db: SafeDatabase,
    collection: str,
    *,
    filters: dict[str, Any] | None = None,
    sort_field: str | None = None,
    limit: int | None = None,
    allowed_fields: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch docs with optional equality filters, sorting, and limit."""
    filter_items = list((filters or {}).items())
    for filter_field, _ in filter_items:
        _validate_field_name(filter_field, allowed_fields=allowed_fields)
    safe_sort_field = None
    if sort_field is not None:
        safe_sort_field = _validate_field_name(sort_field, allowed_fields=allowed_fields)
    sort_clause = "SORT doc[@sort_field]" if safe_sort_field is not None else ""
    query = f"""
    FOR doc IN @@collection
      FILTER LENGTH(@filters) == 0
        OR ALL(
          FOR criterion IN @filters
            RETURN doc[criterion.name] == criterion.value
        )
      {sort_clause}
      LIMIT @limit
      RETURN doc
    """
    rows = execute(
        db,
        query,
        {
            "@collection": collection,
            "sort_field": safe_sort_field,
            "limit": normalize_limit(limit),
            "filters": [{"name": name, "value": value} for name, value in filter_items],
        },
    )
    return [row for row in rows if isinstance(row, dict)]


def list_field_values(
    db: SafeDatabase,
    collection: str,
    value_field: str,
    *,
    sort_field: str | None = None,
    limit: int | None = None,
    filters: dict[str, Any] | None = None,
    allowed_fields: set[str] | None = None,
) -> list[Any]:
    """Return one field value from docs matching optional equality filters."""
    safe_value_field = _validate_field_name(value_field, allowed_fields=allowed_fields)
    filter_items = list((filters or {}).items())
    for filter_field, _ in filter_items:
        _validate_field_name(filter_field, allowed_fields=allowed_fields)
    safe_sort_field = None
    if sort_field is not None:
        safe_sort_field = _validate_field_name(sort_field, allowed_fields=allowed_fields)
    sort_clause = "SORT doc[@sort_field]" if safe_sort_field is not None else ""
    query = f"""
    FOR doc IN @@collection
      FILTER LENGTH(@filters) == 0
        OR ALL(
          FOR criterion IN @filters
            RETURN doc[criterion.name] == criterion.value
        )
      {sort_clause}
      LIMIT @limit
      RETURN doc[@value_field]
    """
    return execute(
        db,
        query,
        {
            "@collection": collection,
            "value_field": safe_value_field,
            "sort_field": safe_sort_field,
            "limit": normalize_limit(limit),
            "filters": [{"name": name, "value": value} for name, value in filter_items],
        },
    )


def count_distinct_edge_sources_to_filtered_vertices(
    db: SafeDatabase,
    *,
    edge_collection: str,
    edge_source_field: str,
    edge_target_field: str,
    vertex_collection: str,
    vertex_filters: dict[str, Any],
    vertex_allowed_fields: set[str] | None = None,
    edge_allowed_fields: set[str] | None = None,
) -> int:
    """Count unique edge sources whose target points at filtered vertices."""
    safe_source_field = _validate_field_name(edge_source_field, allowed_fields=edge_allowed_fields)
    safe_target_field = _validate_field_name(edge_target_field, allowed_fields=edge_allowed_fields)
    vertex_filter_items = list(vertex_filters.items())
    for filter_field, _ in vertex_filter_items:
        _validate_field_name(filter_field, allowed_fields=vertex_allowed_fields)

    query = """
    LET vertex_ids = (
      FOR vertex IN @@vertex_collection
        FILTER LENGTH(@vertex_filters) == 0
          OR ALL(
            FOR criterion IN @vertex_filters
              RETURN vertex[criterion.name] == criterion.value
          )
        RETURN vertex._id
    )
    RETURN LENGTH(UNIQUE(
      FOR edge IN @@edge_collection
        FILTER edge[@edge_target_field] IN vertex_ids
        RETURN edge[@edge_source_field]
    ))
    """
    rows = execute(
        db,
        query,
        {
            "@edge_collection": edge_collection,
            "@vertex_collection": vertex_collection,
            "edge_source_field": safe_source_field,
            "edge_target_field": safe_target_field,
            "vertex_filters": [{"name": name, "value": value} for name, value in vertex_filter_items],
        },
    )
    return int(rows[0]) if rows else 0


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


def insert_document(db: SafeDatabase, collection: str, payload: dict[str, Any]) -> str:
    """Insert one document and return its `_id`."""
    query = """
    INSERT @payload IN @@collection
    RETURN NEW._id
    """
    rows = execute(db, query, {"@collection": collection, "payload": payload})
    if not rows or not isinstance(rows[0], str):
        raise RuntimeError(f"Failed to insert document into {collection}")
    return rows[0]


def update_document_by_key(db: SafeDatabase, collection: str, key: str, fields: dict[str, Any]) -> None:
    """Update one document by `_key`."""
    query = """
    UPDATE @key WITH @fields IN @@collection
    """
    execute(db, query, {"@collection": collection, "key": key, "fields": fields})
