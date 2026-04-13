"""Namespace objects for the schema-driven persistence constructor."""

from __future__ import annotations

import hashlib
import math
from typing import Any, cast

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.constructor import verbs
from nomarr.persistence.schema import AggResult, FilterDict, SchemaValidationError

Document = dict[str, Any]
FieldSpec = dict[str, Any]
CollectionSpec = dict[str, Any]


def _make_vector_key(file_id: str, model_suite_hash: str) -> str:
    """Build the deterministic key used by vectors_track hot/cold collections."""
    return hashlib.sha1(f"{file_id}|{model_suite_hash}".encode()).hexdigest()


class IdGetNamespace:
    """Single-document `_id` lookup namespace."""

    def __init__(self, db: SafeDatabase, collection_name: str) -> None:
        self._db = db
        self._collection_name = collection_name

    def __call__(self, doc_id: str) -> Document | None:
        """Allow `db.collection.get.one(id)` as shorthand for `.id(id)`."""
        return self.id(doc_id)

    def id(self, doc_id: str) -> Document | None:
        """Get a single document by `_id`."""
        return verbs.get_one_by_id(self._db, self._collection_name, doc_id)


class IdGetManyNamespace:
    """Multi-document `_id` lookup namespace."""

    def __init__(self, db: SafeDatabase, collection_name: str) -> None:
        self._db = db
        self._collection_name = collection_name

    def __call__(self, ids: list[str]) -> list[Document]:
        """Allow `db.collection.get.many(ids)` as shorthand for `.id(ids)`."""
        return self.id(ids)

    def id(self, ids: list[str]) -> list[Document]:
        """Get multiple documents by `_id`."""
        return verbs.get_many_by_ids(self._db, self._collection_name, ids)

    def by_filter(
        self,
        filter_dict: dict[str, Any],
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        """Get multiple documents by a multi-field equality filter."""
        return verbs.get_many_by_filter(
            self._db,
            self._collection_name,
            filter_dict,
            limit=limit,
            offset=offset,
        )


class CollectionGetNamespace:
    """Collection-level `get` namespace with `.one.id()` and `.many.id()` accessors."""

    def __init__(self, db: SafeDatabase, collection_name: str) -> None:
        self.one = IdGetNamespace(db, collection_name)
        self.many = IdGetManyNamespace(db, collection_name)

    def __call__(self, doc_id: str) -> Document | None:
        """Shorthand for `get.one.id(doc_id)`."""
        return self.one.id(doc_id)


class GetModifierNamespace:
    """Field-level `get` namespace with cardinality and operator modifiers."""

    def __init__(
        self,
        db: SafeDatabase,
        collection_name: str,
        field_name: str,
        field_spec: FieldSpec,
        collection_operators: dict[str, list[str]] | None = None,
    ) -> None:
        """Initialize field-level ``get`` access for a schema field.

        ``field_spec["unique"]`` determines whether shorthand lookups use
        ``.one`` or dispatch to ``.many`` and whether ``.one`` is exposed at
        all. ``collection_operators`` gates optional operator helpers on this
        namespace: when omitted or ``None``, ``.like`` is always attached; when
        provided, ``.like`` is attached only if ``"like"`` appears in
        ``collection_operators["get"]``.
        """
        self._db = db
        self._collection_name = collection_name
        self._field_name = field_name
        self._unique = bool(field_spec.get("unique", False))

        get_ops: list[str] | None = (collection_operators or {}).get("get", None)
        if get_ops is None or "like" in get_ops:
            self.like = self._like_impl

    def __call__(self, value: Any) -> Document | None | list[Document]:
        """Dispatch shorthand lookups by field uniqueness."""
        if self._unique:
            return self._one(value)
        return self.many(value)

    def __getattr__(self, name: str) -> Any:
        """Expose `.one` only for unique fields and alias `.in` to `.in_`."""
        if name == "one":
            if self._unique:
                return self._one
            msg = f"'{self._field_name}' is not unique; .one is unavailable"
            raise AttributeError(msg)

        if name == "in":
            return self.in_

        msg = f"{type(self).__name__!s} has no attribute {name!r}"
        raise AttributeError(msg)

    def _one(self, value: Any) -> Document | None:
        """Get one document by a unique field value."""
        return verbs.get_one_by_field(self._db, self._collection_name, self._field_name, value)

    def many(self, value: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        """Get many documents by field equality."""
        return verbs.get_many_by_field(
            self._db,
            self._collection_name,
            self._field_name,
            value,
            limit=limit,
            offset=offset,
        )

    def in_(
        self,
        values: list[Any] | FilterDict,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        """Dispatch `.in()` to either IN-list or comparison-filter behavior."""
        if isinstance(values, list):
            return verbs.get_in_by_field(
                self._db,
                self._collection_name,
                self._field_name,
                values,
                limit=limit,
                offset=offset,
            )

        return verbs.get_range_by_field(
            self._db,
            self._collection_name,
            self._field_name,
            values,
            limit=limit,
            offset=offset,
        )

    def _like_impl(
        self,
        pattern: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        """Run a LIKE query against the field."""
        return verbs.get_like_by_field(
            self._db,
            self._collection_name,
            self._field_name,
            pattern,
            limit=limit,
            offset=offset,
        )


class FieldNamespace:
    """Field namespace built dynamically from a field schema spec."""

    def __init__(
        self,
        db: SafeDatabase,
        collection_name: str,
        field_name: str,
        field_spec: FieldSpec,
        collection_operators: dict[str, list[str]] | None = None,
    ) -> None:
        """Wire capability-based accessors for a single schema field.

        Dynamically attaches ``get``, ``count``, ``collect``, ``aggregate``,
        ``update``, ``upsert``, and ``delete`` methods based on the
        capabilities declared in ``field_spec``. When ``get`` is enabled,
        ``collection_operators`` is forwarded to ``GetModifierNamespace`` to
        gate operator helpers such as ``.like`` on the field's ``get``
        accessor.
        """
        self._db = db
        self._collection_name = collection_name
        self._field_name = field_name
        self._field_spec = field_spec

        capabilities = set(cast("list[str]", field_spec.get("capabilities", [])))

        if "get" in capabilities:
            self.get = GetModifierNamespace(
                db,
                collection_name,
                field_name,
                field_spec,
                collection_operators,
            )
        if "count" in capabilities:
            self.count = self._count
        if "collect" in capabilities:
            self.collect = self._collect
        if "aggregate" in capabilities:
            self.aggregate = self._aggregate
        if "update" in capabilities:
            self.update = self._update
        if "upsert" in capabilities:
            self.upsert = self._upsert
        if "delete" in capabilities:
            self.delete = self._delete

    def _count(self, value: Any) -> int:
        """Count documents where this field matches a value."""
        return verbs.count_by_field(self._db, self._collection_name, self._field_name, value)

    def _collect(
        self,
        *,
        filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Any]:
        """Collect distinct values for this field."""
        return verbs.collect_field(
            self._db,
            self._collection_name,
            self._field_name,
            filter=filter,
            limit=limit,
            offset=offset,
        )

    def _aggregate(
        self,
        *,
        filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AggResult]:
        """Aggregate this field into value/count pairs."""
        return verbs.aggregate_field(
            self._db,
            self._collection_name,
            self._field_name,
            filter=filter,
            limit=limit,
            offset=offset,
        )

    def _update(self, match_value: Any, fields: Document) -> None:
        """Update documents matching this field value."""
        verbs.update_by_field(self._db, self._collection_name, self._field_name, match_value, fields)

    def _upsert(self, docs: list[Document], match_field: str | list[str]) -> list[str]:
        """Upsert documents using the supplied match field or fields."""
        return verbs.upsert_by_field(self._db, self._collection_name, match_field, docs)

    def _delete(self, value: Any) -> int:
        """Delete documents where this field equals the provided value."""
        return verbs.delete_by_field(self._db, self._collection_name, self._field_name, value)


class CollectionNamespace:
    """Collection namespace built dynamically from a collection schema spec."""

    def __init__(
        self,
        db: SafeDatabase,
        collection_name: str,
        spec: CollectionSpec,
        schema: dict[str, Any],
        registry: dict[str, Any] | None = None,
    ) -> None:
        """Wire collection-level and field-level namespaces from a schema spec.

        Always attaches a ``get`` accessor. Conditionally attaches ``insert``,
        ``delete``, ``cascade``, ``count``, ``transition``, ``traversal``, and
        ``ann_search`` based on ``spec["capabilities"]``. Creates a
        ``FieldNamespace`` for each field in ``spec["fields"]`` and forwards
        ``spec["operators"]`` so each field's ``get`` accessor exposes only
        the allowed operators, such as ``.like``.
        """
        self._db = db
        self._collection_name = collection_name
        self._spec = spec
        self._schema = schema
        self._registry = registry
        self.get = CollectionGetNamespace(db, collection_name)

        capabilities = set(cast("list[str]", spec.get("capabilities", [])))
        collection_operators = cast("dict[str, list[str]] | None", spec.get("operators"))

        if "insert" in capabilities:
            self.insert = self._insert
        if "delete" in capabilities:
            self.delete = self._delete
        if "cascade" in capabilities:
            self.cascade = self._cascade
        if "count" in capabilities:
            self.count = self._count
            self.count_by_filter = self._count_by_filter
        if "delete" in capabilities:
            self.delete_by_filter = self._delete_by_filter
        if "update" in capabilities:
            self.update_by_filter = self._update_by_filter
        if "truncate" in capabilities:
            self.truncate = self._truncate
        if "transition" in capabilities:
            self.transition = self._transition
        if "traversal" in capabilities:
            self.traversal = self._traversal
        if "ann_search" in capabilities:
            self.ann_search = self._ann_search

        template_family = cast("str | None", spec.get("template_family"))
        template_tier = cast("str | None", spec.get("template_tier"))
        if template_family == "vectors_track":
            self.get_vector = self._get_vector
            self.get_vectors_by_file_ids = self._get_vectors_by_file_ids
            if template_tier == "hot":
                self.upsert_vector = self._upsert_vector

        for field_name, field_spec in cast("dict[str, FieldSpec]", spec.get("fields", {})).items():
            setattr(
                self,
                field_name,
                FieldNamespace(
                    db,
                    collection_name,
                    field_name,
                    field_spec,
                    collection_operators,
                ),
            )

    def _insert(self, docs: list[Document]) -> list[str]:
        """Insert documents into the collection."""
        return verbs.insert(self._db, self._collection_name, docs)

    def _delete(self, ids: list[str]) -> None:
        """Delete documents by `_id`."""
        verbs.delete_by_ids(self._db, self._collection_name, ids)

    def _count(self) -> int:
        """Count all documents in the collection."""
        return verbs.count_all(self._db, self._collection_name)

    def _count_by_filter(self, filter_dict: dict[str, Any]) -> int:
        """Count documents matching a multi-field equality filter."""
        return verbs.count_by_filter(self._db, self._collection_name, filter_dict)

    def _truncate(self) -> None:
        """Remove all documents from the collection."""
        verbs.truncate(self._db, self._collection_name)

    def _delete_by_filter(self, filter_dict: dict[str, Any]) -> int:
        """Delete documents matching a multi-field equality filter."""
        return verbs.delete_by_filter(self._db, self._collection_name, filter_dict)

    def _update_by_filter(self, filter_dict: dict[str, Any], fields: Document) -> None:
        """Update documents matching a multi-field equality filter."""
        verbs.update_by_filter(self._db, self._collection_name, filter_dict, fields)

    def _transition(self, ids: list[str], from_edge_target: str, to_edge_target: str) -> None:
        """Three-phase state transition per DD §3.7, ADR-003, and ERR 1579."""
        edge_col = cast("str | None", self._spec.get("edge_collection"))
        if not edge_col:
            raise SchemaValidationError(
                f"transition() called on {self._collection_name} but no edge_collection defined"
            )

        for doc_id in ids:
            cursor = self._db.aql.execute(
                "FOR e IN @@ec FILTER e._from == @fid AND e._to == @from RETURN e._key",
                bind_vars={"@ec": edge_col, "fid": doc_id, "from": from_edge_target},
            )
            old_key = next(cursor, None)

            if old_key is not None:
                self._db.aql.execute(
                    "REMOVE @key IN @@ec",
                    bind_vars={"@ec": edge_col, "key": old_key},
                )

            self._db.aql.execute(
                "INSERT {_from: @fid, _to: @to} INTO @@ec",
                bind_vars={"@ec": edge_col, "fid": doc_id, "to": to_edge_target},
            )

    def _cascade(self, ids: list[str]) -> int:
        """Cascade delete across schema-declared edge targets."""
        from nomarr.persistence.constructor.cascade import CascadeEngine

        cascade_targets = cast("list[str]", self._spec.get("cascade", []))
        if not cascade_targets:
            return 0

        engine = CascadeEngine()
        return engine.cascade(
            self._db,
            self._collection_name,
            ids,
            cascade_targets,
            self._schema,
            self._registry,
        )

    def _ann_search(
        self,
        query_vector: list[float],
        limit: int,
        nprobe: int,
        *,
        filter: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Run ANN search on a constructed template collection."""
        return verbs.ann_search(
            self._db,
            self._collection_name,
            query_vector,
            limit,
            nprobe,
            filter=filter,
        )

    def _get_vector(self, file_id: str) -> Document | None:
        """Get the latest vector document for a file from this template collection."""
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@col
                FILTER doc.file_id == @file_id
                SORT doc.created_at DESC
                LIMIT 1
                RETURN doc
            """,
            bind_vars={"@col": self._collection_name, "file_id": file_id},
        )
        return cast("Document | None", next(cursor, None))

    def _get_vectors_by_file_ids(self, file_ids: list[str]) -> list[Document]:
        """Get vector documents for multiple files from this template collection."""
        if not file_ids:
            return []
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@col
                FILTER doc.file_id IN @file_ids
                RETURN doc
            """,
            bind_vars={"@col": self._collection_name, "file_ids": file_ids},
        )
        return [cast("Document", row) for row in cursor]

    def _upsert_vector(
        self,
        file_id: str,
        model_suite_hash: str,
        embed_dim: int,
        vector: list[float],
        num_segments: int,
    ) -> None:
        """Upsert a hot vectors_track document plus its file_has_vectors edge."""
        _key = _make_vector_key(file_id, model_suite_hash)
        norm = math.sqrt(math.fsum(x * x for x in vector))
        vector_n = [x / norm for x in vector] if norm > 0.0 else list(vector)

        doc: Document = {
            "_key": _key,
            "file_id": file_id,
            "model_suite_hash": model_suite_hash,
            "embed_dim": embed_dim,
            "vector": vector,
            "vector_n": vector_n,
            "num_segments": num_segments,
            "created_at": 0,
        }
        cursor = self._db.aql.execute(
            "RETURN DATE_NOW()",
            bind_vars={},
        )
        doc["created_at"] = cast("int", next(cursor, 0))
        verbs.upsert_by_field(self._db, self._collection_name, "_key", [doc])

        vector_id = f"{self._collection_name}/{_key}"
        self._db.aql.execute(
            """
            UPSERT { _from: @file_id, _to: @vector_id }
            INSERT { _from: @file_id, _to: @vector_id }
            UPDATE {}
            IN file_has_vectors
            """,
            bind_vars={"file_id": file_id, "vector_id": vector_id},
        )

    def _traversal(
        self,
        start: str | dict[str, Any],
        edge: str,
        *,
        target_filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        """Traverse an edge in one of the DD-defined modes."""
        edge_spec = cast("dict[str, str] | None", self._spec.get("edges", {}).get(edge))
        if edge_spec is None:
            msg = f"Edge '{edge}' is not declared on collection '{self._collection_name}'"
            raise AttributeError(msg)

        direction = edge_spec["direction"]

        if isinstance(start, str):
            return verbs.traversal_by_id(
                self._db,
                self._collection_name,
                start,
                edge,
                direction,
                limit=limit,
                offset=offset,
            )

        if target_filter is None:
            return verbs.traversal_by_filter(
                self._db,
                self._collection_name,
                start,
                edge,
                direction,
                limit=limit,
                offset=offset,
            )

        return verbs.traversal_by_filter_with_target_filter(
            self._db,
            self._collection_name,
            start,
            edge,
            direction,
            target_filter,
            limit=limit,
            offset=offset,
        )


class VectorsTrackMaintenanceNamespace:
    """Maintenance operations spanning a vectors_track hot/cold collection pair."""

    def __init__(self, db: SafeDatabase, hot_collection_name: str, cold_collection_name: str) -> None:
        self._db = db
        self._hot_collection_name = hot_collection_name
        self._cold_collection_name = cold_collection_name

    def drain_to_cold(self) -> int:
        """Drain all hot vectors into cold using convergent UPSERT semantics."""
        if not self._db.has_collection(self._hot_collection_name):
            msg = f"Hot collection '{self._hot_collection_name}' does not exist"
            raise ValueError(msg)

        hot_collection = self._db.collection(self._hot_collection_name)
        hot_count = cast("int", hot_collection.count())
        if hot_count == 0:
            return 0

        if not self._db.has_collection(self._cold_collection_name):
            self._db.create_collection(self._cold_collection_name)

        self._db.aql.execute(
            """
            FOR doc IN @@hot_coll
                LET genres = (
                    FOR edge IN song_has_tags
                        FILTER edge._from == doc.file_id
                        FOR tag IN tags
                            FILTER tag._id == edge._to AND tag.rel == "genre"
                            RETURN tag.value
                )
                UPSERT { _key: doc._key }
                INSERT MERGE(doc, { genres: genres })
                UPDATE MERGE(doc, { genres: genres })
                IN @@cold_coll
            """,
            bind_vars={
                "@hot_coll": self._hot_collection_name,
                "@cold_coll": self._cold_collection_name,
            },
        )
        self._db.aql.execute(
            """
            FOR doc IN @@hot_coll
                FOR e IN file_has_vectors
                    FILTER e._from == doc.file_id AND e._to == CONCAT(@hot_prefix, doc._key)
                    REMOVE e IN file_has_vectors
            """,
            bind_vars={
                "@hot_coll": self._hot_collection_name,
                "hot_prefix": f"{self._hot_collection_name}/",
            },
        )
        self._db.aql.execute(
            """
            FOR doc IN @@hot_coll
                UPSERT { _from: doc.file_id, _to: CONCAT(@cold_prefix, doc._key) }
                INSERT { _from: doc.file_id, _to: CONCAT(@cold_prefix, doc._key) }
                UPDATE {}
                IN file_has_vectors
            """,
            bind_vars={
                "@hot_coll": self._hot_collection_name,
                "cold_prefix": f"{self._cold_collection_name}/",
            },
        )
        hot_collection.truncate()
        return hot_count

    def ensure_cold_collection(self) -> None:
        """Create the cold collection if it does not already exist."""
        if not self._db.has_collection(self._cold_collection_name):
            self._db.create_collection(self._cold_collection_name)

    def drop_index(self) -> None:
        """Drop the cold collection vector index if it exists."""
        if not self._db.has_collection(self._cold_collection_name):
            msg = f"Cold collection '{self._cold_collection_name}' does not exist"
            raise ValueError(msg)

        cold_collection = self._db.collection(self._cold_collection_name)
        existing_indexes = cast("list[dict[str, Any]]", cold_collection.indexes())
        for index in existing_indexes:
            if index.get("type") == "vector" and index.get("id"):
                cold_collection.delete_index(index["id"])

    def build_index(self, *, embed_dim: int, nlists: int) -> None:
        """Create the cold collection vector index."""
        if not self._db.has_collection(self._cold_collection_name):
            msg = f"Cold collection '{self._cold_collection_name}' does not exist"
            raise ValueError(msg)

        cold_collection = self._db.collection(self._cold_collection_name)

        cold_collection.add_index(
            {
                "type": "vector",
                "fields": ["vector_n"],
                "params": {
                    "metric": "cosine",
                    "dimension": embed_dim,
                    "nLists": nlists,
                },
                "storedValues": ["genres"],
            }
        )

    def rebuild_index(self, *, embed_dim: int, nlists: int) -> None:
        """Drop and rebuild the cold collection vector index."""
        self.drop_index()
        self.build_index(embed_dim=embed_dim, nlists=nlists)

    def get_stats(self) -> dict[str, int | bool]:
        """Return current hot/cold counts and cold-index state."""
        hot_count = 0
        if self._db.has_collection(self._hot_collection_name):
            hot_count = cast("int", self._db.collection(self._hot_collection_name).count())

        cold_count = 0
        index_exists = False
        if self._db.has_collection(self._cold_collection_name):
            cold_collection = self._db.collection(self._cold_collection_name)
            cold_count = cast("int", cold_collection.count())
            existing_indexes = cast("list[dict[str, Any]]", cold_collection.indexes())
            index_exists = any(index.get("type") == "vector" for index in existing_indexes)

        return {
            "hot_count": hot_count,
            "cold_count": cold_count,
            "index_exists": index_exists,
        }
