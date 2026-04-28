"""Namespace objects for the schema-driven persistence constructor."""

from __future__ import annotations

import hashlib
import math
from typing import Any, cast

from nomarr.helpers.filter_types import AggResult, FilterDict
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.constructor import verbs
from nomarr.persistence.constructor.cascade import CascadeEngine
from nomarr.persistence.schema import CapabilityError, SchemaValidationError

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
    """Field-level `get` namespace with cardinality and operator modifiers.

    All accessors (``__call__``, ``one``, ``many``, ``in_``, ``like``) are
    always bound. Capability and uniqueness constraints are enforced at call
    time: invoking a method that is not declared in the field's capabilities
    or operators raises :class:`CapabilityError`. Calling ``.one`` on a
    non-unique field raises :class:`CapabilityError` since uniqueness is a
    structural prerequisite for single-document lookup.
    """

    def __init__(
        self,
        db: SafeDatabase,
        collection_name: str,
        field_name: str,
        field_spec: FieldSpec,
        collection_operators: dict[str, list[str]] | None = None,
        *,
        get_enabled: bool = True,
    ) -> None:
        self._db = db
        self._collection_name = collection_name
        self._field_name = field_name
        self._unique = bool(field_spec.get("unique", False))
        self._get_enabled = get_enabled

        get_ops: list[str] | None = (collection_operators or {}).get("get", None)
        # ``None`` operators dict means "all operators allowed". An explicit
        # list gates each operator individually.
        self._like_enabled = get_ops is None or "like" in get_ops

    def _require_get(self) -> None:
        if not self._get_enabled:
            raise CapabilityError(f"field {self._collection_name}.{self._field_name} does not declare 'get' capability")

    def __getattr__(self, name: str) -> Any:
        """Alias `.in` (Python keyword) to `.in_`."""
        if name == "in":
            return self.in_
        msg = f"{type(self).__name__!s} has no attribute {name!r}"
        raise AttributeError(msg)

    def __call__(self, value: Any) -> Document | None | list[Document]:
        """Dispatch shorthand lookups by field uniqueness."""
        if self._unique:
            return self.one(value)
        return self.many(value)

    def one(self, value: Any) -> Document | None:
        """Get one document by a unique field value."""
        self._require_get()
        if not self._unique:
            raise CapabilityError(
                f"field {self._collection_name}.{self._field_name} is not unique; .one is unavailable"
            )
        return verbs.get_one_by_field(self._db, self._collection_name, self._field_name, value)

    def many(self, value: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        """Get many documents by field equality."""
        self._require_get()
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
        self._require_get()
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

    def like(
        self,
        pattern: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        """Run a LIKE query against the field."""
        self._require_get()
        if not self._like_enabled:
            raise CapabilityError(f"field {self._collection_name}.{self._field_name} does not declare 'like' operator")
        return verbs.get_like_by_field(
            self._db,
            self._collection_name,
            self._field_name,
            pattern,
            limit=limit,
            offset=offset,
        )


class FieldNamespace:
    """Field namespace built dynamically from a field schema spec.

    Every accessor (``get``, ``count``, ``collect``, ``aggregate``, ``update``,
    ``upsert``, ``delete``) is always attached. Capability gating happens at
    call time via :meth:`_require_capability`, which raises
    :class:`CapabilityError` for any verb not declared in the field's
    ``capabilities`` list. The ``get`` accessor is always a
    :class:`GetModifierNamespace`; if ``get`` is not declared, every method on
    that sub-namespace also raises :class:`CapabilityError`.
    """

    def __init__(
        self,
        db: SafeDatabase,
        collection_name: str,
        field_name: str,
        field_spec: FieldSpec,
        collection_operators: dict[str, list[str]] | None = None,
    ) -> None:
        self._db = db
        self._collection_name = collection_name
        self._field_name = field_name
        self._field_spec = field_spec
        self._capabilities = set(cast("list[str]", field_spec.get("capabilities", [])))

        self.get = GetModifierNamespace(
            db,
            collection_name,
            field_name,
            field_spec,
            collection_operators,
            get_enabled="get" in self._capabilities,
        )

    def _require_capability(self, name: str) -> None:
        if name not in self._capabilities:
            raise CapabilityError(
                f"field {self._collection_name}.{self._field_name} does not declare {name!r} capability"
            )

    def count(self, value: Any) -> int:
        """Count documents where this field matches a value."""
        self._require_capability("count")
        return verbs.count_by_field(self._db, self._collection_name, self._field_name, value)

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Any]:
        """Collect distinct values for this field."""
        self._require_capability("collect")
        return verbs.collect_field(
            self._db,
            self._collection_name,
            self._field_name,
            filter=filter,
            limit=limit,
            offset=offset,
        )

    def aggregate(
        self,
        *,
        filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AggResult]:
        """Aggregate this field into value/count pairs."""
        self._require_capability("aggregate")
        return verbs.aggregate_field(
            self._db,
            self._collection_name,
            self._field_name,
            filter=filter,
            limit=limit,
            offset=offset,
        )

    def update(self, match_value: Any, fields: Document) -> None:
        """Update documents matching this field value."""
        self._require_capability("update")
        verbs.update_by_field(self._db, self._collection_name, self._field_name, match_value, fields)

    def upsert(self, docs: list[Document], match_field: str | list[str]) -> list[str]:
        """Upsert documents using the supplied match field or fields."""
        self._require_capability("upsert")
        return verbs.upsert_by_field(self._db, self._collection_name, match_field, docs)

    def delete(self, value: Any) -> int:
        """Delete documents where this field equals the provided value."""
        self._require_capability("delete")
        return verbs.delete_by_field(self._db, self._collection_name, self._field_name, value)


class CollectionNamespace:
    """Collection namespace built dynamically from a collection schema spec.

    Every collection-level method (``insert``, ``delete``, ``cascade``,
    ``count``, ``count_by_filter``, ``delete_by_filter``, ``update_by_filter``,
    ``truncate``, ``transition``, ``traversal``, ``ann_search``,
    ``get_vector``, ``get_vectors_by_file_ids``, ``upsert_vector``) is always
    bound. Capability gating is enforced at call time via
    :meth:`_require_capability`, which raises :class:`CapabilityError` when
    the verb is not declared in ``spec["capabilities"]``. Vectors-track
    helpers are gated on ``template_family`` / ``template_tier`` instead of
    capabilities and raise :class:`CapabilityError` for non-matching
    collections. Each field in ``spec["fields"]`` is wired as a
    :class:`FieldNamespace`.
    """

    def __init__(
        self,
        db: SafeDatabase,
        collection_name: str,
        spec: CollectionSpec,
        schema: dict[str, Any],
        registry: dict[str, Any] | None = None,
    ) -> None:
        self._db = db
        self._collection_name = collection_name
        self._spec = spec
        self._schema = schema
        self._registry = registry
        self._capabilities = set(cast("list[str]", spec.get("capabilities", [])))
        self._template_family = cast("str | None", spec.get("template_family"))
        self._template_tier = cast("str | None", spec.get("template_tier"))

        self.get = CollectionGetNamespace(db, collection_name)

        collection_operators = cast("dict[str, list[str]] | None", spec.get("operators"))
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

    def _require_capability(self, name: str) -> None:
        if name not in self._capabilities:
            raise CapabilityError(f"collection {self._collection_name!r} does not declare {name!r} capability")

    def _require_vectors_track(self, hot_only: bool = False) -> None:
        if self._template_family != "vectors_track":
            raise CapabilityError(f"collection {self._collection_name!r} is not a vectors_track collection")
        if hot_only and self._template_tier != "hot":
            raise CapabilityError(f"collection {self._collection_name!r} is not a hot vectors_track collection")

    def insert(self, docs: list[Document]) -> list[str]:
        """Insert documents into the collection."""
        self._require_capability("insert")
        return verbs.insert(self._db, self._collection_name, docs)

    def delete(self, ids: list[str]) -> None:
        """Delete documents by `_id`."""
        self._require_capability("delete")
        verbs.delete_by_ids(self._db, self._collection_name, ids)

    def count(self) -> int:
        """Count all documents in the collection."""
        self._require_capability("count")
        return verbs.count_all(self._db, self._collection_name)

    def count_by_filter(self, filter_dict: dict[str, Any]) -> int:
        """Count documents matching a multi-field equality filter."""
        self._require_capability("count")
        return verbs.count_by_filter(self._db, self._collection_name, filter_dict)

    def truncate(self) -> None:
        """Remove all documents from the collection."""
        self._require_capability("truncate")
        verbs.truncate(self._db, self._collection_name)

    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int:
        """Delete documents matching a multi-field equality filter."""
        self._require_capability("delete")
        return verbs.delete_by_filter(self._db, self._collection_name, filter_dict)

    def update_by_filter(self, filter_dict: dict[str, Any], fields: Document) -> None:
        """Update documents matching a multi-field equality filter."""
        self._require_capability("update")
        verbs.update_by_filter(self._db, self._collection_name, filter_dict, fields)

    def transition(self, ids: list[str], from_edge_target: str, to_edge_target: str) -> None:
        """Three-phase state transition per DD §3.7, ADR-003, and ERR 1579."""
        self._require_capability("transition")
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
                """
                UPSERT { _from: @fid, _to: @to }
                INSERT { _from: @fid, _to: @to }
                UPDATE {}
                IN @@ec
                """,
                bind_vars={"@ec": edge_col, "fid": doc_id, "to": to_edge_target},
            )

    def cascade(self, ids: list[str]) -> int:
        """Cascade delete across schema-declared edge targets."""
        self._require_capability("cascade")
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

    def ann_search(
        self,
        query_vector: list[float],
        limit: int,
        nprobe: int,
        *,
        filter: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Run ANN search on a constructed template collection."""
        self._require_capability("ann_search")
        return verbs.ann_search(
            self._db,
            self._collection_name,
            query_vector,
            limit,
            nprobe,
            filter=filter,
        )

    def get_vector(self, file_id: str) -> Document | None:
        """Get the latest vector document for a file from this template collection."""
        self._require_vectors_track()
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

    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[Document]:
        """Get vector documents for multiple files from this template collection."""
        self._require_vectors_track()
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

    def upsert_vector(
        self,
        file_id: str,
        model_suite_hash: str,
        embed_dim: int,
        vector: list[float],
        num_segments: int,
    ) -> None:
        """Upsert a hot vectors_track document plus its file_has_vectors edge."""
        self._require_vectors_track(hot_only=True)
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

    def traversal(
        self,
        start: str | dict[str, Any],
        edge: str,
        *,
        target_filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        """Traverse an edge in one of the DD-defined modes."""
        self._require_capability("traversal")
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
