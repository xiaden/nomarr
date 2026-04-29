"""AQL verb template implementations for the schema-driven constructor.

Each function generates and executes an AQL query using the python-arango db handle.
The collection name uses @@ bind var notation (two @ = collection bind).
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, cast

from arango.exceptions import AQLQueryExecuteError

from nomarr.helpers.filter_types import AggResult, FilterDict
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.constructor.filters import (
    build_comparison_filter,
    build_equality_filter,
    build_in_filter,
    build_like_filter,
)
from nomarr.persistence.constructor.pagination import inject_pagination

Document = dict[str, Any]

_WRITE_WRITE_CONFLICT_CODE = 1200
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.05  # 50ms, doubles each retry

logger = logging.getLogger(__name__)


_CURSOR_TTL = 3600  # seconds — prevents ERR 1600 on large multi-batch result sets


def _execute_aql(
    db: SafeDatabase,
    query: str,
    bind_vars: dict[str, Any],
    *,
    retry_on_conflict: bool = False,
) -> Any:
    """Execute AQL via python-arango, logging the query at DEBUG level.

    A server-side cursor TTL of ``_CURSOR_TTL`` seconds is set on every query
    so that large result sets fetched in multiple batches never hit the default
    30-second expiry (ArangoDB ERR 1600).

    When *retry_on_conflict* is ``True``, transient ArangoDB write-write
    conflicts (error 1200) are retried up to ``_MAX_RETRIES`` times with
    exponential back-off.
    """
    logger.debug("AQL: %s | bind_vars: %s", query, bind_vars)
    if not retry_on_conflict:
        return db.aql.execute(query, bind_vars=bind_vars, ttl=_CURSOR_TTL)

    last_exc: AQLQueryExecuteError | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return db.aql.execute(query, bind_vars=bind_vars, ttl=_CURSOR_TTL)
        except AQLQueryExecuteError as exc:
            if exc.error_code != _WRITE_WRITE_CONFLICT_CODE or attempt == _MAX_RETRIES:
                raise
            last_exc = exc
            delay = _RETRY_BASE_DELAY * (2**attempt) + random.uniform(0, _RETRY_BASE_DELAY)
            logger.debug("Write-write conflict (attempt %d/%d), retrying in %.3fs", attempt + 1, _MAX_RETRIES, delay)
            time.sleep(delay)
    assert last_exc is not None  # unreachable: loop always runs ≥1 iteration
    raise last_exc


def _validate_field_name(field: str) -> None:
    """Ensure *field* is safe for backtick-quoted AQL interpolation."""
    if not field or "`" in field:
        msg = f"Invalid field name for AQL interpolation: {field!r}"
        raise ValueError(msg)


def _cursor_to_documents(cursor: Any) -> list[Document]:
    """Normalize a cursor-like result into a list of document dictionaries."""
    return [cast("Document", document) for document in cursor]


# ---------------------------------------------------------------------------
# GET verbs
# ---------------------------------------------------------------------------


def get_one_by_id(db: SafeDatabase, collection: str, doc_id: str) -> Document | None:
    """Get a single document by _id using python-arango direct access (no AQL)."""
    return cast("Document | None", db.collection(collection).get(doc_id))


def get_many_by_ids(db: SafeDatabase, collection: str, ids: list[str]) -> list[Document]:
    """Get multiple documents by _id list."""
    cursor = _execute_aql(
        db,
        "FOR doc IN @@col FILTER doc._id IN @ids RETURN doc",
        bind_vars={"@col": collection, "ids": ids},
    )
    return _cursor_to_documents(cursor)


def get_one_by_field(db: SafeDatabase, collection: str, field: str, value: Any) -> Document | None:
    """Get single document where field == value."""
    cursor = _execute_aql(
        db,
        "FOR doc IN @@col FILTER doc[@field] == @val LIMIT 1 RETURN doc",
        bind_vars={"@col": collection, "field": field, "val": value},
    )
    return cast("Document | None", next(cursor, None))


def get_many_by_field(
    db: SafeDatabase,
    collection: str,
    field: str,
    value: Any,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[Document]:
    """Get all documents where field == value (paginated)."""
    query, pagination_vars = inject_pagination(
        "FOR doc IN @@col FILTER doc[@field] == @val RETURN doc",
        limit,
        offset,
    )
    bind_vars = {"@col": collection, "field": field, "val": value}
    bind_vars.update(pagination_vars)
    cursor = _execute_aql(
        db,
        query,
        bind_vars=bind_vars,
    )
    return _cursor_to_documents(cursor)


def get_many_by_filter(
    db: SafeDatabase,
    collection: str,
    filter_dict: dict[str, Any],
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[Document]:
    """Get all documents matching an equality filter dict (paginated)."""
    filter_fragment, filter_vars = build_equality_filter(filter_dict)
    query_lines = ["FOR doc IN @@col"]
    if filter_fragment:
        query_lines.append(f"  {filter_fragment}")
    query_lines.append("  RETURN doc")
    query, pagination_vars = inject_pagination("\n".join(query_lines), limit, offset)

    bind_vars = {"@col": collection}
    bind_vars.update(filter_vars)
    bind_vars.update(pagination_vars)
    cursor = _execute_aql(db, query, bind_vars=bind_vars)
    return _cursor_to_documents(cursor)


def get_in_by_field(
    db: SafeDatabase,
    collection: str,
    field: str,
    values: list[Any],
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[Document]:
    """Get documents where field IN values list."""
    filter_clause, bind_vars = build_in_filter(field, values)
    query, pagination_vars = inject_pagination(
        f"FOR doc IN @@col {filter_clause} RETURN doc",
        limit,
        offset,
    )
    bind_vars["@col"] = collection
    bind_vars.update(pagination_vars)
    cursor = _execute_aql(db, query, bind_vars=bind_vars)
    return _cursor_to_documents(cursor)


def get_range_by_field(
    db: SafeDatabase,
    collection: str,
    field: str,
    filter_dict: FilterDict,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[Document]:
    """Get documents matching range/comparison filter (FilterDict mode)."""
    filter_clause, bind_vars = build_comparison_filter(field, filter_dict)
    query, pagination_vars = inject_pagination(
        f"FOR doc IN @@col {filter_clause} RETURN doc",
        limit,
        offset,
    )
    bind_vars["@col"] = collection
    bind_vars.update(pagination_vars)
    cursor = _execute_aql(db, query, bind_vars=bind_vars)
    return _cursor_to_documents(cursor)


def get_like_by_field(
    db: SafeDatabase,
    collection: str,
    field: str,
    pattern: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[Document]:
    """Get documents where field LIKE pattern."""
    filter_clause, bind_vars = build_like_filter(field, pattern)
    query, pagination_vars = inject_pagination(
        f"FOR doc IN @@col {filter_clause} RETURN doc",
        limit,
        offset,
    )
    bind_vars["@col"] = collection
    bind_vars.update(pagination_vars)
    cursor = _execute_aql(db, query, bind_vars=bind_vars)
    return _cursor_to_documents(cursor)


# ---------------------------------------------------------------------------
# INSERT / UPSERT / UPDATE verbs
# ---------------------------------------------------------------------------


def insert(db: SafeDatabase, collection: str, docs: list[Document]) -> list[str]:
    """Insert documents and return their ``_id`` values."""
    results = cast(
        "list[Document]", db.collection(collection).insert_many(docs, return_new=True, raise_on_document_error=True)
    )
    return [cast("str", result["new"]["_id"]) for result in results]


def upsert_by_field(
    db: SafeDatabase,
    collection: str,
    field: str | list[str],
    docs: list[Document],
) -> list[str]:
    """Upsert documents matching ``field`` or a compound key and return their ``_id`` values."""
    ids: list[str] = []
    for doc in docs:
        if isinstance(field, list):
            for f in field:
                _validate_field_name(f)
            upsert_fields = ", ".join(f"`{f}`: @kv{i}" for i, f in enumerate(field))
            bind_vars: dict[str, Any] = {"@col": collection, "doc": doc}
            for i, f in enumerate(field):
                bind_vars[f"kv{i}"] = doc.get(f)
            cursor = _execute_aql(
                db,
                f"UPSERT {{ {upsert_fields} }} INSERT @doc UPDATE @doc IN @@col RETURN NEW._id",
                bind_vars=bind_vars,
                retry_on_conflict=True,
            )
        else:
            _validate_field_name(field)
            cursor = _execute_aql(
                db,
                f"UPSERT {{ `{field}`: @key_val }} INSERT @doc UPDATE @doc IN @@col RETURN NEW._id",
                bind_vars={
                    "@col": collection,
                    "key_val": doc.get(field),
                    "doc": doc,
                },
                retry_on_conflict=True,
            )
        ids.append(cast("str", next(cursor)))
    return ids


def update_by_field(
    db: SafeDatabase,
    collection: str,
    field: str,
    match_value: Any,
    fields: Document,
) -> None:
    """Update all documents where field == match_value."""
    _execute_aql(
        db,
        "FOR doc IN @@col FILTER doc[@field] == @val UPDATE doc WITH @fields IN @@col",
        bind_vars={"@col": collection, "field": field, "val": match_value, "fields": fields},
    )


def update_by_filter(
    db: SafeDatabase,
    collection: str,
    filter_dict: dict[str, Any],
    fields: Document,
) -> None:
    """Update all documents matching an equality filter dict."""
    filter_fragment, filter_vars = build_equality_filter(filter_dict)
    query_lines = ["FOR doc IN @@col"]
    if filter_fragment:
        query_lines.append(f"  {filter_fragment}")
    query_lines.append("  UPDATE doc WITH @fields IN @@col")

    bind_vars = {"@col": collection, "fields": fields}
    bind_vars.update(filter_vars)
    _execute_aql(db, "\n".join(query_lines), bind_vars=bind_vars)


# ---------------------------------------------------------------------------
# DELETE verbs
# ---------------------------------------------------------------------------


def delete_by_ids(db: SafeDatabase, collection: str, ids: list[str]) -> None:
    """Delete documents by ``_id`` list."""
    _execute_aql(
        db,
        "FOR id IN @ids REMOVE {_key: PARSE_IDENTIFIER(id).key} IN @@col",
        bind_vars={"@col": collection, "ids": ids},
    )


def delete_by_field(db: SafeDatabase, collection: str, field: str, value: Any) -> int:
    """Delete all documents where field == value. Returns count deleted."""
    cursor = _execute_aql(
        db,
        "FOR doc IN @@col FILTER doc[@field] == @val REMOVE doc IN @@col RETURN 1",
        bind_vars={"@col": collection, "field": field, "val": value},
    )
    return sum(1 for _ in cursor)


def delete_by_filter(db: SafeDatabase, collection: str, filter_dict: dict[str, Any]) -> int:
    """Delete all documents matching an equality filter dict. Returns count deleted."""
    filter_fragment, filter_vars = build_equality_filter(filter_dict)
    query_lines = ["FOR doc IN @@col"]
    if filter_fragment:
        query_lines.append(f"  {filter_fragment}")
    query_lines.extend(
        [
            "  REMOVE doc IN @@col",
            "  RETURN 1",
        ]
    )

    bind_vars = {"@col": collection}
    bind_vars.update(filter_vars)
    cursor = _execute_aql(db, "\n".join(query_lines), bind_vars=bind_vars)
    return sum(1 for _ in cursor)


# ---------------------------------------------------------------------------
# STATS verbs
# ---------------------------------------------------------------------------


def count_all(db: SafeDatabase, collection: str) -> int:
    """Count all documents in collection."""
    cursor = _execute_aql(
        db,
        "RETURN LENGTH(@@col)",
        bind_vars={"@col": collection},
    )
    return cast("int", next(cursor, 0))


def count_by_field(db: SafeDatabase, collection: str, field: str, value: Any) -> int:
    """Count documents where field == value."""
    cursor = _execute_aql(
        db,
        "FOR doc IN @@col FILTER doc[@field] == @val COLLECT WITH COUNT INTO c RETURN c",
        bind_vars={"@col": collection, "field": field, "val": value},
    )
    return cast("int", next(cursor, 0))


def count_by_filter(db: SafeDatabase, collection: str, filter_dict: dict[str, Any]) -> int:
    """Count documents matching an equality filter dict."""
    filter_fragment, filter_vars = build_equality_filter(filter_dict)
    query_lines = ["FOR doc IN @@col"]
    if filter_fragment:
        query_lines.append(f"  {filter_fragment}")
    query_lines.extend(
        [
            "  COLLECT WITH COUNT INTO c",
            "  RETURN c",
        ]
    )

    bind_vars = {"@col": collection}
    bind_vars.update(filter_vars)
    cursor = _execute_aql(db, "\n".join(query_lines), bind_vars=bind_vars)
    return cast("int", next(cursor, 0))


def collect_field(
    db: SafeDatabase,
    collection: str,
    field: str,
    *,
    filter: dict[str, Any] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Any]:
    """Distinct values of field across collection, optionally narrowed by a multi-field equality ``filter`` passed to ``build_equality_filter``."""
    filter_fragment, filter_vars = build_equality_filter(filter or {})
    query_lines = ["FOR doc IN @@col"]
    if filter_fragment:
        query_lines.append(f"  {filter_fragment}")
    query_lines.extend(
        [
            "  COLLECT val = doc[@field]",
            "  RETURN val",
        ]
    )
    query, pagination_vars = inject_pagination("\n".join(query_lines), limit, offset)
    bind_vars = {"@col": collection, "field": field}
    bind_vars.update(filter_vars)
    bind_vars.update(pagination_vars)
    cursor = _execute_aql(db, query, bind_vars=bind_vars)
    return list(cursor)


def aggregate_field(
    db: SafeDatabase,
    collection: str,
    field: str,
    *,
    filter: dict[str, Any] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[AggResult]:
    """Distinct values with occurrence counts, optionally narrowed by a multi-field equality ``filter`` passed to ``build_equality_filter``."""
    filter_fragment, filter_vars = build_equality_filter(filter or {})
    query_lines = ["FOR doc IN @@col"]
    if filter_fragment:
        query_lines.append(f"  {filter_fragment}")
    query_lines.extend(
        [
            "  COLLECT val = doc[@field] WITH COUNT INTO c",
            "  RETURN {value: val, count: c}",
        ]
    )
    query, pagination_vars = inject_pagination("\n".join(query_lines), limit, offset)
    bind_vars = {"@col": collection, "field": field}
    bind_vars.update(filter_vars)
    bind_vars.update(pagination_vars)
    cursor = _execute_aql(db, query, bind_vars=bind_vars)
    return [cast("AggResult", row) for row in cursor]


# ---------------------------------------------------------------------------
# GRAPH verbs
# ---------------------------------------------------------------------------


def traversal_by_id(
    db: SafeDatabase,
    collection: str,
    start_id: str,
    edge: str,
    direction: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[Document]:
    """Graph traversal starting from a known document ID."""
    del collection

    if direction == "OUTBOUND":
        query, pagination_vars = inject_pagination(
            "FOR v IN 1..1 OUTBOUND @start_id @@edge RETURN v",
            limit,
            offset,
        )
    elif direction == "INBOUND":
        query, pagination_vars = inject_pagination(
            "FOR v IN 1..1 INBOUND @start_id @@edge RETURN v",
            limit,
            offset,
        )
    else:
        msg = f"Unsupported traversal direction: {direction}"
        raise ValueError(msg)

    bind_vars = {"start_id": start_id, "@edge": edge}
    bind_vars.update(pagination_vars)
    cursor = _execute_aql(db, query, bind_vars=bind_vars)
    return _cursor_to_documents(cursor)


def traversal_by_filter(
    db: SafeDatabase,
    collection: str,
    source_filter: dict[str, Any],
    edge: str,
    direction: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[Document]:
    """Graph traversal from documents matching source filter."""
    filter_parts: list[str] = []
    bind_vars: dict[str, Any] = {"@col": collection, "@edge": edge}

    for index, (field_name, value) in enumerate(source_filter.items()):
        bind_vars[f"src_field_{index}"] = field_name
        bind_vars[f"src_val_{index}"] = value
        filter_parts.append(f"doc[@src_field_{index}] == @src_val_{index}")

    filter_clause = " AND ".join(filter_parts)

    if direction == "OUTBOUND":
        query, pagination_vars = inject_pagination(
            f"FOR doc IN @@col FILTER {filter_clause} FOR v IN 1..1 OUTBOUND doc @@edge RETURN v",
            limit,
            offset,
        )
    elif direction == "INBOUND":
        query, pagination_vars = inject_pagination(
            f"FOR doc IN @@col FILTER {filter_clause} FOR v IN 1..1 INBOUND doc @@edge RETURN v",
            limit,
            offset,
        )
    else:
        msg = f"Unsupported traversal direction: {direction}"
        raise ValueError(msg)

    bind_vars.update(pagination_vars)
    cursor = _execute_aql(db, query, bind_vars=bind_vars)
    return _cursor_to_documents(cursor)


def traversal_by_filter_with_target_filter(
    db: SafeDatabase,
    collection: str,
    source_filter: dict[str, Any],
    edge: str,
    direction: str,
    target_filter: dict[str, Any],
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[Document]:
    """Graph traversal from source filter to target filter."""
    source_parts: list[str] = []
    target_parts: list[str] = []
    bind_vars: dict[str, Any] = {"@col": collection, "@edge": edge}

    for index, (field_name, value) in enumerate(source_filter.items()):
        bind_vars[f"src_field_{index}"] = field_name
        bind_vars[f"src_val_{index}"] = value
        source_parts.append(f"doc[@src_field_{index}] == @src_val_{index}")

    for index, (field_name, value) in enumerate(target_filter.items()):
        bind_vars[f"tgt_field_{index}"] = field_name
        bind_vars[f"tgt_val_{index}"] = value
        target_parts.append(f"v[@tgt_field_{index}] == @tgt_val_{index}")

    filter_clause = " AND ".join(source_parts)
    filter_block = " AND ".join(target_parts)

    if direction == "OUTBOUND":
        query, pagination_vars = inject_pagination(
            f"FOR doc IN @@col FILTER {filter_clause} FOR v IN 1..1 OUTBOUND doc @@edge FILTER {filter_block} RETURN v",
            limit,
            offset,
        )
    elif direction == "INBOUND":
        query, pagination_vars = inject_pagination(
            f"FOR doc IN @@col FILTER {filter_clause} FOR v IN 1..1 INBOUND doc @@edge FILTER {filter_block} RETURN v",
            limit,
            offset,
        )
    else:
        msg = f"Unsupported traversal direction: {direction}"
        raise ValueError(msg)

    bind_vars.update(pagination_vars)
    cursor = _execute_aql(db, query, bind_vars=bind_vars)
    return _cursor_to_documents(cursor)


def ann_search(
    db: SafeDatabase,
    collection: str,
    query_vector: list[float],
    limit: int,
    nprobe: int,
    *,
    filter: dict[str, Any] | None = None,
) -> list[Document]:
    """Run APPROX_NEAR_COSINE against a template vector collection.

    Returns stored documents merged with a cosine ``score`` field. When a
    single-entry ``filter`` is provided, the field is matched either by direct
    equality or list membership (for fields such as ``genres``).
    """
    bind_vars: dict[str, Any] = {
        "@col": collection,
        "query_vector": query_vector,
        "nprobe": nprobe,
        "limit": limit,
    }
    filter_clause = ""
    if filter:
        if len(filter) != 1:
            msg = "ann_search filter currently supports exactly one field"
            raise ValueError(msg)
        filter_field, filter_value = next(iter(filter.items()))
        bind_vars["filter_field"] = filter_field
        bind_vars["filter_value"] = filter_value
        filter_clause = "FILTER @filter_value IN doc[@filter_field] OR doc[@filter_field] == @filter_value"

    cursor = _execute_aql(
        db,
        f"""
        FOR doc IN APPROX_NEAR_COSINE(@@col, @query_vector, @nprobe)
            {filter_clause}
            LET score = SUM(
                FOR idx IN 0..(LENGTH(doc.vector_n) - 1)
                    RETURN doc.vector_n[idx] * @query_vector[idx]
            )
            LIMIT @limit
            RETURN MERGE(doc, {{file_id: doc.file_id, score: score}})
        """,
        bind_vars=bind_vars,
    )
    return _cursor_to_documents(cursor)


# ---------------------------------------------------------------------------
# TRUNCATE verb
# ---------------------------------------------------------------------------


def truncate(db: SafeDatabase, collection_name: str) -> None:
    """Remove all documents from a collection.

    Uses python-arango's native ``Collection.truncate()`` — no AQL needed.
    """
    db.collection(collection_name).truncate()
