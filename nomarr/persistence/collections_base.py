from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from typing import Any, ClassVar, cast

from nomarr.helpers.time_helper import internal_ms
from nomarr.persistence.accessors import CollectionDelete, CollectionGet, FieldAccessor
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base_types import (
    EdgeDef,
    Field,
    _normalize_field_criteria,
    collection_name_for_class,
)
from nomarr.persistence.constructor import verbs

Document = dict[str, Any]


class BaseCollection:
    """Abstract base for ArangoDB collection wrappers.

    Stores the `SafeDatabase` handle, collection name, a `_fields` registry of
    `FieldAccessor` instances, and pre-built `.get` and `.delete` callables.
    Subclasses register typed field accessors by calling `_field()` from their
    `__init__` methods.
    """

    def __init__(self, db: SafeDatabase, name: str) -> None:
        self._db = db
        self._name = name
        self._fields: dict[str, FieldAccessor] = {}
        self.get = CollectionGet(db, name, self._fields)
        self.delete = CollectionDelete(db, name)

    def _field(self, field_name: str, *, unique: bool = False) -> FieldAccessor:
        """Register a FieldAccessor for this collection. Call from subclass __init__."""
        accessor = FieldAccessor(self._db, self._name, field_name, unique=unique)
        self._fields[field_name] = accessor
        return accessor

    def insert(self, docs: list[Document]) -> list[str]:
        """Insert documents into the collection.

        Args:
            docs: Documents to insert.

        Returns:
            The `_key` values for the inserted documents.
        """
        return verbs.insert(self._db, self._name, docs)

    def count(self, *args: Field, **kwargs: Any) -> int:
        """Count documents matching the supplied field criteria.

        With no criteria, returns the total document count. With one criterion,
        delegates to a single-field count. With multiple criteria, delegates to
        a filter count.

        Args:
            *args: Positional field criteria.
            **kwargs: Keyword field criteria.

        Returns:
            The number of matching documents.
        """
        criteria = _normalize_field_criteria(args, kwargs)
        if not criteria:
            return verbs.count_all(self._db, self._name)
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            return verbs.count_by_field(self._db, self._name, field_name, value)
        return verbs.count_by_filter(self._db, self._name, criteria)

    def update(self, *args: Field, fields: Document, **kwargs: Any) -> None:
        """Update documents matching the supplied field criteria.

        Args:
            *args: Positional field criteria.
            fields: Field values to merge into matching documents.
            **kwargs: Keyword field criteria.

        Raises:
            ValueError: If no matching criterion is supplied.
        """
        criteria = _normalize_field_criteria(args, kwargs)
        if not criteria:
            raise ValueError("update() requires at least one criterion")
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            verbs.update_by_field(self._db, self._name, field_name, value, fields)
            return
        verbs.update_by_filter(self._db, self._name, criteria, fields)

    def upsert(self, *args: Field, fields: Document, **kwargs: Any) -> list[str]:
        """Upsert a single document matched by the supplied field criteria.

        Merges `fields` into the matched document, or into a newly created
        document when no match exists.

        Args:
            *args: Positional field criteria.
            fields: Field values to merge into the upserted document.
            **kwargs: Keyword field criteria.

        Returns:
            The `_key` values for the affected documents.

        Raises:
            ValueError: If no matching criterion is supplied.
        """
        criteria = _normalize_field_criteria(args, kwargs)
        if not criteria:
            raise ValueError("upsert() requires at least one criterion")
        doc = {**criteria, **fields}
        if len(criteria) == 1:
            field_name = next(iter(criteria))
            return verbs.upsert_by_field(self._db, self._name, field_name, [doc])
        return verbs.upsert_by_field(self._db, self._name, list(criteria), [doc])

    def upsert_batch(self, docs: list[Document], match_fields: str | list[str]) -> list[str]:
        """Upsert a batch of documents using the given match fields.

        No-ops when `docs` is empty.

        Args:
            docs: Documents to upsert.
            match_fields: Field name or names used as the uniqueness key.

        Returns:
            The `_key` values for the affected documents.
        """
        if not docs:
            return []
        return verbs.upsert_by_field(self._db, self._name, match_fields, docs)

    def update_many(self, docs: list[Document]) -> None:
        """Bulk-update documents in the collection by `_key`."""
        verbs.update_many_by_key(self._db, self._name, docs)

    def aggregate(
        self, field_name: str, *, filter: dict[str, Any] | None = None, limit: int | None = None, offset: int = 0
    ) -> list:
        """Return deduplicated values for a field.

        Args:
            field_name: Name of the field to aggregate.
            filter: Optional field filters to apply before aggregation.
            limit: Maximum number of values to return.
            offset: Number of values to skip before returning results.

        Returns:
            A deduplicated list of values for `field_name`.
        """
        return verbs.aggregate_field(self._db, self._name, field_name, filter=filter, limit=limit, offset=offset)

    def count_inbound_connections(
        self,
        edge_collection: str,
        *,
        filter_field: str,
        filter_values: list[Any],
        return_field: str = "_id",
        label: str = "value",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        """Count inbound single-hop edge connections for matching documents."""
        return verbs.count_inbound_connections(
            self._db,
            self._name,
            edge_collection,
            filter_field,
            filter_values,
            return_field=return_field,
            label=label,
            limit=limit,
            offset=offset,
        )

    def count_outbound_connections(
        self,
        edge_collection: str,
        *,
        filter_field: str,
        filter_values: list[Any],
        return_field: str = "_id",
        label: str = "value",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        """Count outbound single-hop edge connections for matching documents."""
        return verbs.count_outbound_connections(
            self._db,
            self._name,
            edge_collection,
            filter_field,
            filter_values,
            return_field=return_field,
            label=label,
            limit=limit,
            offset=offset,
        )

    def truncate(self) -> None:
        """Remove all documents from the collection."""
        verbs.truncate(self._db, self._name)


class DocumentCollection(BaseCollection):
    """Collection wrapper for ArangoDB document collections.

    Registers `_key`, `_id`, and `_rev` field accessors on construction,
    auto-attaches traversal callables declared in the class-level `EDGES`
    list, and receives its cascade-delete callable later from
    `Database._compile_all_cascades()` after all collections are instantiated.
    """

    EDGES: ClassVar[list[EdgeDef]] = []  # set at class level in collections.py

    def __init__(self, db: SafeDatabase, name: str) -> None:
        super().__init__(db, name)
        self._key = self._field("_key", unique=True)
        self._id = self._field("_id", unique=True)
        self._rev = self._field("_rev")
        # Auto-attach traversal callables from EDGES.
        # EDGES is the single source of truth for traversal relationships.
        # No manual self.traversal(...) assignments in collection __init__ bodies.
        for edge_def in self.__class__.EDGES:
            edge_attr = collection_name_for_class(edge_def.via)
            setattr(self, edge_attr, self.traversal(edge_attr, edge_def.direction))
        # Cascade callable compiled and injected externally by Database._compile_all_cascades()
        # after all collections are instantiated. Not set here.

    def _attach_cascade(self, fn: Callable[[list[str]], int]) -> None:
        """Inject the compiled cascade callable. Called by Database, not by __init__."""
        self.delete.cascade = fn

    def traversal(self, edge_collection: str, direction: str) -> Callable:
        """Build a traversal callable for a related edge collection.

        Args:
            edge_collection: Edge collection to traverse through.
            direction: Traversal direction to use.

        Returns:
            A callable that takes a starting document ID plus optional paging
            arguments and returns the matching documents.
        """
        db, name = self._db, self._name

        def traverse(start_id: str, *, limit: int | None = None, offset: int = 0) -> list[Document]:
            return verbs.traversal_by_id(db, name, start_id, edge_collection, direction, limit=limit, offset=offset)

        def traverse_by_ids(
            start_ids: list[str],
            *,
            limit: int | None = None,
            offset: int = 0,
            **kwargs: Any,
        ) -> list[dict[str, Any]]:
            include_edge = bool(kwargs.pop("include_edge", False))
            target_filter = {key: value for key, value in kwargs.items() if not key.endswith("_starts_with")}
            starts_with_filters = {key: value for key, value in kwargs.items() if key.endswith("_starts_with")}
            target_like_starts_with: tuple[str, str] | None = None
            if starts_with_filters:
                if len(starts_with_filters) != 1:
                    msg = "Traversal by_ids supports at most one *_starts_with filter"
                    raise ValueError(msg)
                starts_with_key, starts_with_value = next(iter(starts_with_filters.items()))
                if not isinstance(starts_with_value, str):
                    msg = "Traversal *_starts_with filters must use a string prefix"
                    raise ValueError(msg)
                target_like_starts_with = (starts_with_key.removesuffix("_starts_with"), starts_with_value)

            return verbs.traversal_by_ids(
                db,
                name,
                start_ids,
                edge_collection,
                direction,
                limit=limit,
                offset=offset,
                target_filter=target_filter or None,
                target_like_starts_with=target_like_starts_with,
                include_edge=include_edge,
            )

        traverse_with_batch = cast("Any", traverse)
        traverse_with_batch.by_ids = traverse_by_ids

        return traverse


class EdgeCollection(BaseCollection):
    """Collection wrapper for ArangoDB edge collections.

    Registers `_key`, `_id`, `_from`, and `_to` field accessors for working
    with edge documents.
    """

    def __init__(self, db: SafeDatabase, name: str) -> None:
        super().__init__(db, name)
        self._key = self._field("_key", unique=True)
        self._id = self._field("_id", unique=True)
        self._from = self._field("_from")
        self._to = self._field("_to")


class VectorCollection(BaseCollection):
    """Collection wrapper for embedding-vector collections.

    Subclasses declare `VECTOR_TIER` ("hot" or "cold") and `NAME_PATTERN`
    for naming. The base registers the shared vector document fields and
    exposes common vector persistence/retrieval verbs used by the dynamic
    hot/cold collection namespaces returned from ``Database.register()``.
    """

    VECTOR_TIER: ClassVar[str]  # "hot" or "cold"
    NAME_PATTERN: ClassVar[str]  # template string

    def __init__(self, db: SafeDatabase, name: str) -> None:
        super().__init__(db, name)
        self._key = self._field("_key", unique=True)
        self._id = self._field("_id", unique=True)
        self.file_id = self._field("file_id")
        self.model_suite_hash = self._field("model_suite_hash")
        self.embed_dim = self._field("embed_dim")
        self.vector = self._field("vector")
        self.vector_n = self._field("vector_n")
        self.num_segments = self._field("num_segments")
        self.created_at = self._field("created_at")

    @staticmethod
    def _make_vector_key(file_id: str, model_suite_hash: str) -> str:
        """Return the deterministic key for one persisted track vector."""
        return hashlib.sha1(f"{file_id}|{model_suite_hash}".encode()).hexdigest()

    @staticmethod
    def _normalize_vector(vector: list[float]) -> list[float]:
        """Return an L2-normalized copy of ``vector`` for cosine ANN search."""
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return list(vector)
        return [value / norm for value in vector]

    def upsert_vector(
        self,
        file_id: str,
        model_suite_hash: str,
        embed_dim: int,
        vector: list[float],
        num_segments: int,
    ) -> None:
        """Upsert a track vector document and maintain its ``file_has_vectors`` edge."""
        vector_key = self._make_vector_key(file_id, model_suite_hash)
        vector_doc: Document = {
            "_key": vector_key,
            "file_id": file_id,
            "model_suite_hash": model_suite_hash,
            "embed_dim": embed_dim,
            "vector": list(vector),
            "vector_n": self._normalize_vector(vector),
            "num_segments": num_segments,
            "created_at": internal_ms().value,
        }
        self.upsert(_key=vector_key, fields=vector_doc)
        verbs.upsert_file_has_vectors_edge(self._db, file_id, f"{self._name}/{vector_key}")

    def get_vector(self, file_id: str) -> Document | None:
        """Return the latest vector document stored for ``file_id``."""
        return verbs.get_vector(self._db, self._name, file_id)

    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[Document]:
        """Return vector documents for the supplied file IDs."""
        return verbs.get_vectors_by_file_ids(self._db, self._name, file_ids)

    def ann_search(
        self,
        vector: list[float],
        limit: int,
        nprobe: int = 10,
        *,
        filter: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Run approximate cosine search against this vector collection."""
        return verbs.ann_search(self._db, self._name, vector, limit, nprobe, filter=filter)

    def delete_by_file_id(self, file_id: str) -> int:
        """Delete all vector documents associated with ``file_id``."""
        return cast("int", self.file_id.delete(file_id))

    def delete_by_file_ids(self, file_ids: list[str]) -> int:
        """Delete all vector documents associated with each supplied file ID."""
        return sum(self.delete_by_file_id(file_id) for file_id in file_ids)

    def move_collection(self, dest: str) -> int:
        """Move this collection into ``dest`` using the vector-aware move verb."""
        return verbs.move_collection(self._db, self._name, dest)


class StateGraphCollection(DocumentCollection):
    """Document collection wrapper that also models a state-machine graph.

    Pairs the document collection with a companion edge collection to support
    atomic state transitions.
    """

    def __init__(self, db: SafeDatabase, name: str, edge_name: str) -> None:
        super().__init__(db, name)
        self._edge_name = edge_name

    def transition(self, file_ids: list[str], from_state: str, to_state: str) -> None:
        """Atomically transition files between states via the companion edge collection.

        Args:
            file_ids: File document IDs to transition.
            from_state: Expected current state.
            to_state: Destination state.
        """
        verbs.transition(self._db, self._edge_name, file_ids, from_state, to_state)
