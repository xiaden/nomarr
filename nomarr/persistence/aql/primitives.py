"""Low-level Tier 1 AQL primitive helpers used by the Tier 2 binding classes in `nomarr/persistence/database/`.

These functions provide validated building blocks for composing AQL queries."""

from __future__ import annotations

import re
from collections.abc import Set
from typing import Any, cast

from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]

# Dots are allowed intentionally so callers can reference nested AQL attribute
# paths like "metadata.title" when interpolating validated field names.
_FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.]*$")


def _validate_field_name(field_name: str) -> None:
    """Validate a field name before embedding it into AQL text."""
    if not field_name or field_name.startswith(("_", ".")) or _FIELD_NAME_PATTERN.fullmatch(field_name) is None:
        msg = f"Invalid field name for AQL interpolation: {field_name!r}"
        raise ValueError(msg)


def _require_allowed_field(field_name: str, allowed_fields: Set[str]) -> None:
    _validate_field_name(field_name)
    if field_name not in allowed_fields:
        msg = f"Field {field_name!r} is not allowed for this query"
        raise ValueError(msg)


def _normalize_bind_key(prefix: str, index: int) -> str:
    return f"{prefix}_{index}"


def _build_filter_lines(
    *,
    doc_name: str,
    filters: dict[str, Any],
    bind_vars: dict[str, Any],
    allowed_fields: Set[str],
) -> list[str]:
    filter_lines: list[str] = []
    for index, (field_name, value) in enumerate(sorted(filters.items())):
        _require_allowed_field(field_name, allowed_fields)
        bind_key = _normalize_bind_key("filter", index)
        filter_lines.append(f"    FILTER {doc_name}.{field_name} == @{bind_key}")
        bind_vars[bind_key] = value
    return filter_lines


def execute(db: SafeDatabase, query: str, bind_vars: dict[str, Any]) -> list[Document]:
    """Execute AQL and materialize the cursor as plain dictionaries."""
    cursor = db.aql.execute(query, bind_vars=bind_vars)
    return [cast("Document", row) for row in cursor]


def normalize_limit(limit: int | None) -> int | None:
    """Normalize optional limits so non-positive values disable LIMIT."""
    if limit is None or limit <= 0:
        return None
    return limit


def get_many_by_keys(db: SafeDatabase, collection: str, keys: list[str]) -> list[Document]:
    """Fetch multiple documents by ``_key``."""
    if not keys:
        return []

    return execute(
        db,
        """
        FOR doc IN @@collection
            FILTER doc._key IN @keys
            RETURN doc
        """,
        {"@collection": collection, "keys": keys},
    )


def get_many_by_field(
    db: SafeDatabase,
    collection: str,
    field_name: str,
    value: Any,
    *,
    limit: int | None,
    allowed_fields: Set[str],
) -> list[Document]:
    """Fetch documents that match one equality filter."""
    _require_allowed_field(field_name, allowed_fields)
    normalized_limit = normalize_limit(limit)

    query_lines = [
        "FOR doc IN @@collection",
        f"    FILTER doc.{field_name} == @value",
        "    SORT doc._key",
    ]
    bind_vars: dict[str, Any] = {"@collection": collection, "value": value}
    if normalized_limit is not None:
        query_lines.append("    LIMIT @limit")
        bind_vars["limit"] = normalized_limit
    query_lines.append("    RETURN doc")

    return execute(db, "\n".join(query_lines), bind_vars)


def get_filtered_docs(
    db: SafeDatabase,
    collection: str,
    *,
    filters: dict[str, Any],
    sort_field: str | None,
    limit: int | None,
    allowed_fields: Set[str],
) -> list[Document]:
    """Fetch documents matching equality filters with optional sort and limit."""
    bind_vars: dict[str, Any] = {"@collection": collection}
    query_lines = ["FOR doc IN @@collection"]
    query_lines.extend(
        _build_filter_lines(doc_name="doc", filters=filters, bind_vars=bind_vars, allowed_fields=allowed_fields),
    )
    if sort_field is not None:
        _require_allowed_field(sort_field, allowed_fields)
        query_lines.append(f"    SORT doc.{sort_field}")
    normalized_limit = normalize_limit(limit)
    if normalized_limit is not None:
        query_lines.append("    LIMIT @limit")
        bind_vars["limit"] = normalized_limit
    query_lines.append("    RETURN doc")
    return execute(db, "\n".join(query_lines), bind_vars)


def list_field_values(
    db: SafeDatabase,
    collection: str,
    value_field: str,
    *,
    sort_field: str | None,
    limit: int | None,
    filters: dict[str, Any],
    allowed_fields: Set[str],
) -> list[Any]:
    """Return a flat list of one projected field from filtered documents."""
    _require_allowed_field(value_field, allowed_fields)
    bind_vars: dict[str, Any] = {"@collection": collection}
    query_lines = ["FOR doc IN @@collection"]
    query_lines.extend(
        _build_filter_lines(doc_name="doc", filters=filters, bind_vars=bind_vars, allowed_fields=allowed_fields),
    )
    if sort_field is not None:
        _require_allowed_field(sort_field, allowed_fields)
        query_lines.append(f"    SORT doc.{sort_field}")
    normalized_limit = normalize_limit(limit)
    if normalized_limit is not None:
        query_lines.append("    LIMIT @limit")
        bind_vars["limit"] = normalized_limit
    query_lines.append(f"    RETURN doc.{value_field}")
    cursor = db.aql.execute("\n".join(query_lines), bind_vars=bind_vars)
    return list(cursor)


def count_distinct_edge_sources_to_filtered_vertices(
    db: SafeDatabase,
    *,
    edge_collection: str,
    vertex_collection: str,
    vertex_filters: dict[str, Any],
) -> int:
    """Count distinct edge ``_from`` values that point at filtered vertices."""
    bind_vars: dict[str, Any] = {
        "@edge_collection": edge_collection,
        "@vertex_collection": vertex_collection,
    }
    query_lines = ["LET sources = UNIQUE(", "    FOR vertex IN @@vertex_collection"]
    for index, (field_name, value) in enumerate(sorted(vertex_filters.items())):
        _validate_field_name(field_name)
        bind_key = _normalize_bind_key("vertex_filter", index)
        query_lines.append(f"        FILTER vertex.{field_name} == @{bind_key}")
        bind_vars[bind_key] = value
    query_lines.extend(
        [
            "        FOR edge IN @@edge_collection",
            "            FILTER edge._to == vertex._id",
            "            RETURN edge._from",
            ")",
            "RETURN LENGTH(sources)",
        ],
    )
    cursor = db.aql.execute("\n".join(query_lines), bind_vars=bind_vars)
    results = list(cursor)
    return int(results[0]) if results else 0


def delete_many_by_keys(db: SafeDatabase, collection: str, keys: list[str]) -> int:
    """Delete documents by ``_key`` and return the number removed."""
    if not keys:
        return 0

    cursor = db.aql.execute(
        """
        LET removed = (
            FOR key IN @keys
                REMOVE { _key: key } IN @@collection
                OPTIONS { ignoreErrors: true }
                RETURN 1
        )
        RETURN LENGTH(removed)
        """,
        bind_vars={"@collection": collection, "keys": keys},
    )
    results = list(cursor)
    return int(results[0]) if results else 0


def upsert_by_field(
    db: SafeDatabase,
    collection: str,
    field_name: str,
    field_value: Any,
    payload: dict[str, Any],
) -> str:
    """Upsert one document addressed by a validated field name and return its ``_id``."""
    _validate_field_name(field_name)
    query = f"""
    UPSERT {{ {field_name}: @field_value }}
        INSERT MERGE(@payload, {{ {field_name}: @field_value }})
        UPDATE @payload
        IN @@collection
    RETURN NEW._id
    """
    cursor = db.aql.execute(
        query,
        bind_vars={"@collection": collection, "field_value": field_value, "payload": payload},
    )
    return cast("str", next(iter(cursor)))


def upsert_many_by_field(
    db: SafeDatabase,
    collection: str,
    field_name: str,
    payloads: list[dict[str, Any]],
) -> list[str]:
    """Batch-upsert documents matched by ``field_name``, returning ``_id`` list in input order."""
    if not payloads:
        return []
    _validate_field_name(field_name)
    query = f"""
    FOR doc IN @docs
        UPSERT {{ {field_name}: doc.{field_name} }}
            INSERT doc
            UPDATE doc
            IN @@collection
        RETURN NEW._id
    """
    cursor = db.aql.execute(
        query,
        bind_vars={"@collection": collection, "docs": payloads},
    )
    return cast("list[str]", list(cursor))


def insert_document(db: SafeDatabase, collection: str, payload: dict[str, Any]) -> str:
    """Insert one document and return its ``_id``."""
    result = cast("dict[str, Any]", db.collection(collection).insert(payload))
    return cast("str", result["_id"])


def update_document_by_key(db: SafeDatabase, collection: str, key: str, fields: dict[str, Any]) -> None:
    """Update one document by ``_key``."""
    if not fields:
        return

    db.aql.execute(
        """
        UPDATE { _key: @key }
            WITH @fields
            IN @@collection
            OPTIONS { mergeObjects: true }
        """,
        bind_vars={"@collection": collection, "key": key, "fields": fields},
    )
