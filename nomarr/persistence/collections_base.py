from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

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
    for naming, and this base registers `_key`, `_id`, `file_id`, and
    `vector` field accessors.
    """

    VECTOR_TIER: ClassVar[str]  # "hot" or "cold"
    NAME_PATTERN: ClassVar[str]  # template string

    def __init__(self, db: SafeDatabase, name: str) -> None:
        super().__init__(db, name)
        self._key = self._field("_key", unique=True)
        self._id = self._field("_id", unique=True)
        self.file_id = self._field("file_id")
        self.vector = self._field("vector")


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
