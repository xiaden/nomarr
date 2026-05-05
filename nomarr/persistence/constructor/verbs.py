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
    """Upsert documents matching ``field`` or a compound key and return their ``_id`` values.

    Executes a single AQL query for the entire ``docs`` list regardless of
    size, replacing the previous per-document loop.
    """
    if not docs:
        return []

    if isinstance(field, list):
        for f in field:
            _validate_field_name(f)
        search_expr = "{" + ", ".join(f"`{f}`: doc.`{f}`" for f in field) + "}"
        cursor = _execute_aql(
            db,
            f"FOR doc IN @docs UPSERT {search_expr} INSERT doc UPDATE doc IN @@col RETURN NEW._id",
            bind_vars={"@col": collection, "docs": docs},
            retry_on_conflict=True,
        )
    else:
        _validate_field_name(field)
        cursor = _execute_aql(
            db,
            f"FOR doc IN @docs UPSERT {{`{field}`: doc.`{field}`}} INSERT doc UPDATE doc IN @@col RETURN NEW._id",
            bind_vars={"@col": collection, "docs": docs},
            retry_on_conflict=True,
        )
    return [cast("str", _id) for _id in cursor]


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


def update_many_by_key(
    db: SafeDatabase,
    collection: str,
    docs: list[Document],
) -> None:
    """Update each document in ``docs`` in-place, matched by ``_key``.

    Each element must contain a ``_key`` field. All other fields in the element
    are merged into the stored document (MERGE semantics — existing fields not
    present in the element are preserved).
    """
    if not docs:
        return
    _execute_aql(
        db,
        "FOR doc IN @docs UPDATE {_key: doc._key} WITH doc IN @@col",
        bind_vars={"@col": collection, "docs": docs},
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


def delete_in_by_field(db: SafeDatabase, collection: str, field: str, values: list[Any]) -> int:
    """Delete all documents where field IN values. Returns count deleted."""
    filter_clause, filter_vars = build_in_filter(field, values)
    cursor = _execute_aql(
        db,
        f"FOR doc IN @@col {filter_clause} REMOVE doc IN @@col RETURN 1",
        bind_vars={"@col": collection, **filter_vars},
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
    """Distinct values of field across collection, optionally narrowed by a
    multi-field equality ``filter`` passed to ``build_equality_filter``."""
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
    """Distinct values with occurrence counts, optionally narrowed by a
    multi-field equality ``filter`` passed to ``build_equality_filter``."""
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


def traversal_by_ids(
    db: Any,
    collection: str,
    start_ids: list[str],
    edge: str,
    direction: str,
    *,
    target_filter: dict[str, Any] | None = None,
    target_like_starts_with: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Graph traversal starting from multiple known document IDs."""
    del collection

    bind_vars: dict[str, Any] = {"start_ids": start_ids, "@edge": edge}
    filter_clauses: list[str] = []

    if target_filter is not None:
        for index, (field_name, value) in enumerate(target_filter.items()):
            bind_vars[f"tgt_field_{index}"] = field_name
            bind_vars[f"tgt_val_{index}"] = value
            filter_clauses.append(f"v[@tgt_field_{index}] == @tgt_val_{index}")

    if target_like_starts_with is not None:
        bind_vars["sw_field"] = target_like_starts_with[0]
        bind_vars["sw_prefix"] = target_like_starts_with[1]
        filter_clauses.append("STARTS_WITH(v[@sw_field], @sw_prefix)")

    if direction == "OUTBOUND":
        traversal_direction = "OUTBOUND"
    elif direction == "INBOUND":
        traversal_direction = "INBOUND"
    else:
        msg = f"Unsupported traversal direction: {direction}"
        raise ValueError(msg)

    filter_block = ""
    if filter_clauses:
        filter_block = f" FILTER {' AND '.join(filter_clauses)}"

    aql = (
        f"FOR start_id IN @start_ids "
        f"FOR v IN 1..1 {traversal_direction} start_id @@edge"
        f"{filter_block} "
        "RETURN {start_id: start_id, v: v}"
    )
    cursor = _execute_aql(db, aql, bind_vars=bind_vars)
    return list(cursor)


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


# ---------------------------------------------------------------------------
# MOVE COLLECTION verb
# ---------------------------------------------------------------------------

_EDGE_BATCH = 2_000


def move_collection(db: SafeDatabase, source: str, dest: str) -> int:
    """Move all documents from ``source`` to ``dest``, re-pointing every edge,
    then removing only the copied documents from source.

    Discovers all non-system edge collections at runtime via AQL — no hardcoded
    names. UPSERT semantics on ``_key`` make the document copy idempotent.
    Creates ``dest`` if it does not exist.

    Edge re-pointing is fully server-side (no Python materialization).
    Both the document copy and edge re-pointing run in batches of ``_EDGE_BATCH``
    using ``SORT _key / LIMIT offset, batch`` pagination so no single query
    handles large vector payloads. Phase 1 inserts new edges, Phase 2 removes
    old edges using a shrinking-set ``LIMIT`` loop.

    Args:
        db: Database handle.
        source: Source collection name.
        dest: Destination collection name.

    Returns:
        Number of documents moved (count before truncate).

    Raises:
        ValueError: If source collection does not exist.

    """
    if not db.has_collection(source):
        msg = f"Source collection '{source}' does not exist"
        raise ValueError(msg)

    count = cast("int", db.collection(source).count())
    if count == 0:
        return 0

    if not db.has_collection(dest):
        db.create_collection(dest)

    # Copy documents in batches — idempotent UPSERT by _key.
    # SORT + LIMIT offset, batch is stable because the source collection is
    # not mutated during this phase.
    doc_offset = 0
    while True:
        cursor = _execute_aql(
            db,
            "FOR doc IN @@src SORT doc._key LIMIT @offset, @batch "
            "UPSERT {_key: doc._key} INSERT doc UPDATE doc IN @@dest RETURN 1",
            bind_vars={"@src": source, "@dest": dest, "offset": doc_offset, "batch": _EDGE_BATCH},
        )
        copied = sum(1 for _ in cursor)
        if copied == 0:
            break
        doc_offset += copied

    src_prefix = f"{source}/"
    dest_prefix = f"{dest}/"

    # Discover all non-system edge collections via Python driver.
    # AQL _collections pseudo-collection is not reliably available in all
    # ArangoDB versions; the HTTP API is the authoritative way to enumerate.
    # type==3 is the ArangoDB integer code for edge collections.
    edge_names = [c["name"] for c in db.collections() if c.get("type") == 3 and not c.get("system", False)]

    for edge_name in edge_names:
        # Phase 1: INSERT new edges in sorted batches.
        # LIMIT @offset, @batch over an unchanged source set is stable — source
        # edges are not touched until Phase 2, so offsets do not shift.
        offset = 0
        while True:
            cursor = _execute_aql(
                db,
                """
                FOR e IN @@ec
                    FILTER STARTS_WITH(e._from, @src) OR STARTS_WITH(e._to, @src)
                    SORT e._key
                    LIMIT @offset, @batch
                    LET new_from = STARTS_WITH(e._from, @src)
                        ? CONCAT(@dest, SUBSTRING(e._from, LENGTH(@src)))
                        : e._from
                    LET new_to   = STARTS_WITH(e._to,   @src) ? CONCAT(@dest, SUBSTRING(e._to,   LENGTH(@src))) : e._to
                    INSERT MERGE(
                        UNSET(e, '_id', '_rev', '_from', '_to'),
                        {_key: CONCAT("mv_", e._key), _from: new_from, _to: new_to}
                    ) IN @@ec OPTIONS {overwriteMode: "replace"}
                    RETURN 1
                """,
                bind_vars={
                    "@ec": edge_name,
                    "src": src_prefix,
                    "dest": dest_prefix,
                    "offset": offset,
                    "batch": _EDGE_BATCH,
                },
            )
            inserted = sum(1 for _ in cursor)
            if inserted == 0:
                break
            offset += inserted

        if offset == 0:
            continue

        # Phase 2: REMOVE old edges in batches.
        # New edges have _from/_to pointing to @dest so the filter only hits
        # old edges; no offset tracking needed since removals shrink the set.
        while True:
            cursor = _execute_aql(
                db,
                "FOR e IN @@ec "
                "FILTER STARTS_WITH(e._from, @src) OR STARTS_WITH(e._to, @src) "
                "LIMIT @batch REMOVE e IN @@ec RETURN 1",
                bind_vars={"@ec": edge_name, "src": src_prefix, "batch": _EDGE_BATCH},
            )
            if sum(1 for _ in cursor) == 0:
                break

    # Delete only documents that were successfully copied to dest — do not
    # truncate. Truncate would destroy any documents written to source after
    # the copy loop started. Filter to keys that still exist in source so the
    # loop is idempotent on crash + resume: already-removed docs are simply
    # skipped rather than erroring.
    del_offset = 0
    while True:
        cursor = _execute_aql(
            db,
            "FOR doc IN @@dest SORT doc._key LIMIT @offset, @batch "
            "FILTER DOCUMENT(@@src, doc._key) != null "
            "REMOVE {_key: doc._key} IN @@src RETURN 1",
            bind_vars={"@dest": dest, "@src": source, "offset": del_offset, "batch": _EDGE_BATCH},
        )
        removed = sum(1 for _ in cursor)
        if removed == 0:
            break
        del_offset += removed

    return count


# ---------------------------------------------------------------------------
# TRANSITION verb
# ---------------------------------------------------------------------------


def transition(
    db: SafeDatabase,
    edge_col: str,
    ids: list[str],
    from_edge_target: str,
    to_edge_target: str,
) -> None:
    """Three-phase state transition: remove old edge, upsert new edge, per ADR-003."""
    for doc_id in ids:
        cursor = _execute_aql(
            db,
            "FOR e IN @@ec FILTER e._from == @fid AND e._to == @from RETURN e._key",
            bind_vars={"@ec": edge_col, "fid": doc_id, "from": from_edge_target},
        )
        old_key = next(cursor, None)

        if old_key is not None:
            _execute_aql(
                db,
                "REMOVE @key IN @@ec",
                bind_vars={"@ec": edge_col, "key": old_key},
            )

        _execute_aql(
            db,
            """
            UPSERT { _from: @fid, _to: @to }
            INSERT { _from: @fid, _to: @to }
            UPDATE {}
            IN @@ec
            """,
            bind_vars={"@ec": edge_col, "fid": doc_id, "to": to_edge_target},
        )


# ---------------------------------------------------------------------------
# VECTORS TRACK verbs
# ---------------------------------------------------------------------------


def get_vector(db: SafeDatabase, collection: str, file_id: str) -> Document | None:
    """Get the latest vector document for a file from a vectors_track collection."""
    cursor = _execute_aql(
        db,
        """
        FOR doc IN @@col
            FILTER doc.file_id == @file_id
            SORT doc.created_at DESC
            LIMIT 1
            RETURN doc
        """,
        bind_vars={"@col": collection, "file_id": file_id},
    )
    return cast("Document | None", next(cursor, None))


def get_vectors_by_file_ids(db: SafeDatabase, collection: str, file_ids: list[str]) -> list[Document]:
    """Get vector documents for multiple files from a vectors_track collection."""
    if not file_ids:
        return []
    cursor = _execute_aql(
        db,
        """
        FOR doc IN @@col
            FILTER doc.file_id IN @file_ids
            RETURN doc
        """,
        bind_vars={"@col": collection, "file_ids": file_ids},
    )
    return _cursor_to_documents(cursor)


def upsert_file_has_vectors_edge(db: SafeDatabase, file_id: str, vector_id: str) -> None:
    """Upsert the file_has_vectors edge between a file and its vector document."""
    _execute_aql(
        db,
        """
        UPSERT { _from: @file_id, _to: @vector_id }
        INSERT { _from: @file_id, _to: @vector_id }
        UPDATE {}
        IN file_has_vectors
        """,
        bind_vars={"file_id": file_id, "vector_id": vector_id},
    )
