"""Build typed collection accessors from class-based collection definitions."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from typing import Annotated, Any, ClassVar, cast, get_args, get_origin, get_type_hints

from nomarr.helpers.filter_types import AggResult, Op
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base import (
    CASCADE,
    OUTBOUND,
    DocumentCollection,
    EdgeCollection,
    EdgeDef,
    FieldMarker,
    StateGraphCollection,
    VectorCollection,
)
from nomarr.persistence.base import (
    Field as FieldValue,
)
from nomarr.persistence.constructor.pagination import DEFAULT_LIMIT

from . import verbs

Document = dict[str, Any]
CollectionInstance = DocumentCollection | EdgeCollection | VectorCollection
_ALWAYS_UNIQUE = frozenset({"_key", "_id"})
_CLASS_VAR_NAMES = frozenset({"EDGES", "FROM_COLLECTION", "TO_COLLECTION", "VECTOR_TIER", "NAME_PATTERN", "_name"})
_SNAKE_CASE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_CASE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")


def _snake_case(name: str) -> str:
    """Convert ``CamelCase`` class names to ``snake_case`` attribute names."""
    return _SNAKE_CASE_RE_2.sub(r"\1_\2", _SNAKE_CASE_RE_1.sub(r"\1_\2", name)).lower()


def _collection_name_for_class(cls: type[object]) -> str:
    """Return the concrete collection name declared on a collection class."""
    declared_name = getattr(cls, "_name", None)
    if isinstance(declared_name, str) and declared_name:
        return declared_name
    return _snake_case(cls.__name__)


def _iter_subclasses(base_cls: type[object]) -> set[type[object]]:
    """Yield all recursive subclasses of ``base_cls``."""
    discovered: set[type[object]] = set()
    pending = list(base_cls.__subclasses__())
    while pending:
        subclass = pending.pop()
        if subclass in discovered:
            continue
        discovered.add(subclass)
        pending.extend(subclass.__subclasses__())
    return discovered


def _is_concrete_collection_class(cls: type[object]) -> bool:
    """Return whether ``cls`` represents a physical Arango collection.

    ``StateGraphCollection`` is an abstract typed base used only to attach the
    state transition verb. Vector collection classes without a concrete
    ``_name`` are runtime templates whose real Arango collection names are
    registered dynamically (for example ``vectors_track_hot__{backbone}__{lib}``).
    Neither category should be compiled into static cascade AQL target sets.
    """

    if cls is StateGraphCollection:
        return False
    if issubclass(cls, VectorCollection):
        declared_name = getattr(cls, "_name", None)
        return isinstance(declared_name, str) and bool(declared_name)
    return True


def _is_classvar(annotation: Any) -> bool:
    """Return whether an annotation is a ``ClassVar``."""
    return get_origin(annotation) is ClassVar


def _extract_field_marker(annotation: Any) -> tuple[Any, bool] | None:
    """Extract ``(python_type, unique)`` from an ``Annotated[..., FieldMarker]`` type."""
    if _is_classvar(annotation):
        return None

    if get_origin(annotation) is not Annotated:
        return None

    args = get_args(annotation)
    if not args:
        return None

    python_type = args[0]
    marker = next((meta for meta in args[1:] if isinstance(meta, FieldMarker)), None)
    if marker is None:
        return None

    return python_type, marker.unique


def _normalize_field_criteria(*args: FieldValue, **kwargs: Any) -> dict[str, Any]:
    """Normalize positional ``Field(name, value)`` items plus keyword filters."""
    criteria: dict[str, Any] = {}
    for item in args:
        criteria[item.name] = item.value
    criteria.update(kwargs)
    return criteria


def _require_single_criterion(*args: FieldValue, **kwargs: Any) -> tuple[str, Any]:
    """Require exactly one field criterion and return it."""
    criteria = _normalize_field_criteria(*args, **kwargs)
    if len(criteria) != 1:
        msg = f"Expected exactly one field criterion, got {len(criteria)}"
        raise ValueError(msg)
    return next(iter(criteria.items()))


def _make_vector_key(file_id: str, model_suite_hash: str) -> str:
    """Build the deterministic key used by vectors_track hot/cold collections."""
    return hashlib.sha1(f"{file_id}|{model_suite_hash}".encode()).hexdigest()


class _GetVerb:
    """Callable helper that exposes ``get`` plus comparison/list modifiers."""

    def __init__(self, accessor: FieldAccessor) -> None:
        self._accessor = accessor

    def __call__(self, value: Any) -> Document | None | list[Document]:
        if self._accessor.unique:
            return verbs.get_one_by_field(
                self._accessor.db,
                self._accessor.collection_name,
                self._accessor.field_name,
                value,
            )
        return self.many(value)

    def many(
        self,
        value: Any,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        return verbs.get_many_by_field(
            self._accessor.db,
            self._accessor.collection_name,
            self._accessor.field_name,
            value,
            limit=limit,
            offset=offset,
        )

    def in_(
        self,
        values: list[Any],
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        return verbs.get_in_by_field(
            self._accessor.db,
            self._accessor.collection_name,
            self._accessor.field_name,
            values,
            limit=limit,
            offset=offset,
        )

    def gte(
        self,
        value: Any,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        return verbs.get_range_by_field(
            self._accessor.db,
            self._accessor.collection_name,
            self._accessor.field_name,
            {Op.GTE: value},
            limit=limit,
            offset=offset,
        )

    def lte(
        self,
        value: Any,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        return verbs.get_range_by_field(
            self._accessor.db,
            self._accessor.collection_name,
            self._accessor.field_name,
            {Op.LTE: value},
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
        return verbs.get_like_by_field(
            self._accessor.db,
            self._accessor.collection_name,
            self._accessor.field_name,
            pattern,
            limit=limit,
            offset=offset,
        )


class _DeleteVerb:
    """Callable helper that exposes ``delete`` plus bulk modifiers."""

    def __init__(self, accessor: FieldAccessor) -> None:
        self._accessor = accessor
        self.cascade: Callable[..., int] | None = None

    def __call__(self, value: Any) -> int:
        return verbs.delete_by_field(
            self._accessor.db,
            self._accessor.collection_name,
            self._accessor.field_name,
            value,
        )

    def in_(self, values: list[Any]) -> int:
        return verbs.delete_in_by_field(
            self._accessor.db,
            self._accessor.collection_name,
            self._accessor.field_name,
            values,
        )


class FieldAccessor:
    """Attached by Builder to collection instances. Provides flat verb API."""

    def __init__(
        self,
        db: SafeDatabase,
        collection_name: str,
        field_name: str,
        python_type: Any,
        unique: bool,
    ) -> None:
        """Bind a field accessor to a specific field on a collection.

        Args:
            db: ArangoDB database handle.
            collection_name: Name of the ArangoDB collection.
            field_name: Name of the field this accessor targets.
            python_type: Python type of the field (from annotations).
            unique: Whether the field has a uniqueness constraint.
        """
        self.db = db
        self.collection_name = collection_name
        self.field_name = field_name
        self.python_type = python_type
        self.unique = unique

        self.get = _GetVerb(self)
        self.delete = _DeleteVerb(self)

    def insert(self, docs: list[Document]) -> list[str]:
        """Insert documents into the owning collection."""
        return verbs.insert(self.db, self.collection_name, docs)

    def update(self, value: Any, fields: Document) -> None:
        """Update documents where this field equals ``value``."""
        verbs.update_by_field(self.db, self.collection_name, self.field_name, value, fields)

    def upsert(self, value: Any, fields: Document) -> list[str]:
        """Upsert a single document using this field as the match key."""
        doc = {self.field_name: value, **fields}
        return verbs.upsert_by_field(self.db, self.collection_name, self.field_name, [doc])

    def upsert_batch(self, docs: list[Document]) -> list[str]:
        """Upsert multiple documents using this field as the match key.

        Each doc must already contain the bound field. Issues a single AQL query
        regardless of batch size.
        """
        return verbs.upsert_by_field(self.db, self.collection_name, self.field_name, docs)

    def count(self, value: Any) -> int:
        """Count documents where this field equals ``value``."""
        return verbs.count_by_field(self.db, self.collection_name, self.field_name, value)

    def collect(self, *, limit: int | None = None, offset: int = 0) -> list[Any]:
        """Return all distinct values of this field across the collection."""
        return verbs.collect_field(self.db, self.collection_name, self.field_name, limit=limit, offset=offset)


class _CollectionGetVerb:
    """Collection-level callable helper that exposes ``get`` plus flat modifiers."""

    def __init__(self, db: SafeDatabase, collection: CollectionInstance) -> None:
        self._db = db
        self._collection = collection
        self._collection_name = cast("str", collection._name)

    def __call__(
        self,
        *args: FieldValue,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> Document | None | list[Document]:
        criteria = _normalize_field_criteria(*args, **kwargs)
        if not criteria:
            msg = "get() requires at least one field criterion"
            raise ValueError(msg)
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            accessor = getattr(self._collection, field_name, None)
            if isinstance(accessor, FieldAccessor):
                if limit is None and offset == 0:
                    return accessor.get(value)
                return accessor.get.many(value, limit=limit, offset=offset)
            return verbs.get_many_by_field(
                self._db,
                self._collection_name,
                field_name,
                value,
                limit=limit,
                offset=offset,
            )
        return verbs.get_many_by_filter(
            self._db,
            self._collection_name,
            criteria,
            limit=limit,
            offset=offset,
        )

    def many(
        self,
        *args: FieldValue,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[Document]:
        criteria = _normalize_field_criteria(*args, **kwargs)
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            accessor = getattr(self._collection, field_name, None)
            if isinstance(accessor, FieldAccessor):
                return accessor.get.many(value, limit=limit, offset=offset)
            return verbs.get_many_by_field(
                self._db,
                self._collection_name,
                field_name,
                value,
                limit=limit,
                offset=offset,
            )
        return verbs.get_many_by_filter(
            self._db,
            self._collection_name,
            criteria,
            limit=limit,
            offset=offset,
        )

    def in_(
        self,
        *args: FieldValue,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[Document]:
        field_name, values = _require_single_criterion(*args, **kwargs)
        accessor = getattr(self._collection, field_name, None)
        if isinstance(accessor, FieldAccessor):
            return accessor.get.in_(cast("list[Any]", values), limit=limit, offset=offset)
        return verbs.get_in_by_field(
            self._db,
            self._collection_name,
            field_name,
            cast("list[Any]", values),
            limit=limit,
            offset=offset,
        )

    def gte(
        self,
        field_name: str,
        threshold: Any,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        accessor = getattr(self._collection, field_name, None)
        if isinstance(accessor, FieldAccessor):
            return accessor.get.gte(threshold, limit=limit, offset=offset)
        return verbs.get_range_by_field(
            self._db,
            self._collection_name,
            field_name,
            {Op.GTE: threshold},
            limit=limit,
            offset=offset,
        )

    def lte(
        self,
        field_name: str,
        threshold: Any,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        accessor = getattr(self._collection, field_name, None)
        if isinstance(accessor, FieldAccessor):
            return accessor.get.lte(threshold, limit=limit, offset=offset)
        return verbs.get_range_by_field(
            self._db,
            self._collection_name,
            field_name,
            {Op.LTE: threshold},
            limit=limit,
            offset=offset,
        )

    def like(
        self,
        field_name: str,
        pattern: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        accessor = getattr(self._collection, field_name, None)
        if isinstance(accessor, FieldAccessor):
            return accessor.get.like(pattern, limit=limit, offset=offset)
        return verbs.get_like_by_field(
            self._db,
            self._collection_name,
            field_name,
            pattern,
            limit=limit,
            offset=offset,
        )


class _CollectionDeleteVerb:
    """Collection-level delete helper with optional cascade attachment."""

    def __init__(self, db: SafeDatabase, collection_name: str) -> None:
        self._db = db
        self._collection_name = collection_name
        self.cascade: Callable[..., int] | None = None

    def __call__(self, *args: FieldValue, **kwargs: Any) -> int:
        criteria = _normalize_field_criteria(*args, **kwargs)
        if not criteria:
            verbs.truncate(self._db, self._collection_name)
            return 0
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            return verbs.delete_by_field(self._db, self._collection_name, field_name, value)
        return verbs.delete_by_filter(self._db, self._collection_name, criteria)

    def in_(self, *args: FieldValue, **kwargs: Any) -> int:
        """Delete all documents where a single field's value is IN the provided list."""
        field_name, values = _require_single_criterion(*args, **kwargs)
        return verbs.delete_in_by_field(self._db, self._collection_name, field_name, cast("list[Any]", values))

    def unreferenced(self, edge_collection: str) -> int:
        """Delete documents in this collection that have no inbound edges in ``edge_collection``."""
        return verbs.delete_unreferenced(self._db, self._collection_name, edge_collection)


class _TraversalVerb:
    """Callable traversal helper with ``by_ids`` support."""

    def __init__(self, db: SafeDatabase, edge_name: str, direction: str) -> None:
        self._db = db
        self._edge_name = edge_name
        self._direction = direction

    def __call__(self, doc_id: str, limit: int | None = DEFAULT_LIMIT) -> list[Document]:
        return verbs.traversal_by_id(
            self._db,
            "",
            doc_id,
            self._edge_name,
            self._direction,
            limit=limit,
        )

    def by_ids(
        self,
        ids: list[str],
        limit: int | None = DEFAULT_LIMIT,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        target_filter = {name: value for name, value in filters.items() if not name.endswith("_starts_with")}
        starts_with_item = next(
            ((name[: -len("_starts_with")], value) for name, value in filters.items() if name.endswith("_starts_with")),
            None,
        )
        results = verbs.traversal_by_ids(
            self._db,
            "",
            ids,
            self._edge_name,
            self._direction,
            target_filter=target_filter or None,
            target_like_starts_with=starts_with_item,
        )
        if limit is None:
            return results
        return results[:limit]


class Builder:
    """Build typed collection instances from class annotations."""

    def __init__(self, db: SafeDatabase) -> None:
        """Initialize the builder with a database handle.

        Validates the CASCADE edge graph for acyclicity on construction.

        Args:
            db: ArangoDB database handle.
        """
        self._db = db
        self._cascade_wired: list[tuple[CollectionInstance, str, list[EdgeDef]]] = []
        self._validate_cascade_dag()

    def construct(self, collection: CollectionInstance) -> None:
        """Read annotations from MRO, build FieldAccessors, and attach verbs."""
        collection_name = getattr(collection, "_name", "") or _collection_name_for_class(type(collection))
        type(collection)._name = collection_name
        cast("Any", collection)._name = collection_name

        annotations: dict[str, Any] = {}
        for cls in reversed(type(collection).__mro__):
            if cls is object:
                continue
            annotations.update(get_type_hints(cls, include_extras=True))

        for field_name, field_type in annotations.items():
            if field_name in _CLASS_VAR_NAMES or _is_classvar(field_type):
                continue

            extracted = _extract_field_marker(field_type)
            if extracted is None:
                continue

            python_type, unique = extracted
            accessor = FieldAccessor(
                db=self._db,
                collection_name=collection_name,
                field_name=field_name,
                python_type=python_type,
                unique=unique or field_name in _ALWAYS_UNIQUE,
            )
            setattr(collection, field_name, accessor)

        self._attach_base_verbs(collection)

        for edge_def in getattr(type(collection), "EDGES", []):
            self._attach_traversal(collection, edge_def)

        cascade_defs = [
            edge
            for edge in getattr(type(collection), "EDGES", [])
            if edge.on_delete == CASCADE and edge.direction == OUTBOUND
        ]
        if cascade_defs:
            self._attach_cascade(collection, cascade_defs)

        if isinstance(collection, StateGraphCollection):
            self._attach_state_graph(collection)

    def _attach_base_verbs(self, collection: CollectionInstance) -> None:
        """Attach collection-level verbs that are not tied to one field."""
        collection_name = cast("str", collection._name)
        collection_obj = cast("Any", collection)

        collection_obj.insert = lambda docs: verbs.insert(self._db, collection_name, docs)
        collection_obj.get = self._build_get_callable(collection)
        collection_obj.delete = _CollectionDeleteVerb(self._db, collection_name)
        collection_obj.count = self._build_count_callable(collection_name)
        collection_obj.update = self._build_update_callable(collection_name)
        collection_obj.upsert = self._build_upsert_callable(collection_name)
        collection_obj.upsert_batch = self._build_upsert_batch_callable(collection_name)
        collection_obj.update_many = lambda docs: verbs.update_many_by_key(self._db, collection_name, docs)
        collection_obj.aggregate = self._build_aggregate_callable(collection_name)
        collection_obj.truncate = lambda: verbs.truncate(self._db, collection_name)

        if isinstance(collection, VectorCollection):
            collection_obj.ann_search = lambda query_vector, limit, nprobe, *, filter=None: verbs.ann_search(
                self._db,
                collection_name,
                query_vector,
                limit,
                nprobe,
                filter=filter,
            )
            collection_obj.get_vector = lambda file_id: verbs.get_vector(self._db, collection_name, file_id)
            if collection.VECTOR_TIER == "hot":
                collection_obj.upsert_vector = self._build_upsert_vector_callable(collection_name)
                collection_obj.move_collection = lambda dest: verbs.move_collection(self._db, collection_name, dest)

    def _attach_traversal(self, collection: CollectionInstance, edge_def: EdgeDef) -> None:
        """Attach a traversal callable named after the edge collection class."""
        edge_name = _collection_name_for_class(edge_def.via)
        traversal = _TraversalVerb(self._db, edge_name, edge_def.direction)
        setattr(collection, _snake_case(edge_def.via.__name__), traversal)

    def _bind_cascade_delete(
        self,
        collection: CollectionInstance,
        compiled_query: str,
    ) -> None:
        """Bind a compiled cascade-delete closure onto a wired collection instance.

        Attaches ``cascade_delete`` to ``collection.delete.cascade`` and, if
        present, to the ``delete.cascade`` attribute of ``_key`` and ``_id``
        field accessors so all deletion entry-points share the same compiled AQL.
        The attached ``cascade_delete(ids: list[str]) -> int`` closure accepts a
        non-empty list of document ``_id`` strings, executes the precompiled AQL
        via ``@starts``, and returns the number of root documents deleted.

        Args:
            collection: The already-constructed collection instance to mutate.
            compiled_query: A static AQL template string produced by
                :meth:`_compile_cascade_query`.  Bound once and reused for all
                subsequent cascade-delete calls on this collection.

        Returns:
            None.
        """
        delete_verb = cast("_CollectionDeleteVerb", cast("Any", collection).delete)

        def cascade_delete(ids: list[str]) -> int:
            if not isinstance(ids, list) or not ids:
                raise ValueError("cascade delete requires a non-empty list of document ids")
            list(verbs._execute_aql(self._db, compiled_query, bind_vars={"starts": ids}))
            return len(ids)

        delete_verb.cascade = cascade_delete

        for attr_name in ("_key", "_id"):
            field_accessor = getattr(collection, attr_name, None)
            if isinstance(field_accessor, FieldAccessor):
                field_accessor.delete.cascade = cascade_delete

    def _attach_cascade(self, collection: CollectionInstance, cascade_defs: list[EdgeDef]) -> None:
        """Attach ``collection.delete.cascade`` using a precompiled static AQL string."""
        collection_name = cast("str", collection._name)
        compiled_query = self._compile_cascade_query(type(collection), collection_name, cascade_defs)
        self._bind_cascade_delete(collection, compiled_query)
        self._cascade_wired.append((collection, collection_name, cascade_defs))

    def reattach_vector_cascades(self, registered_names: list[str]) -> None:
        """Recompile and hot-swap cascades that target dynamic vector collections.

        Args:
            registered_names: Current list of all registered dynamic vector
                collection names. Passed as ``extra_target_names`` when
                recompiling cascade queries.

        Returns:
            None.
        """
        for collection, collection_name, cascade_defs in self._cascade_wired:
            if not any(issubclass(edge_def.target, VectorCollection) for edge_def in cascade_defs):
                continue
            compiled_query = self._compile_cascade_query(
                type(collection),
                collection_name,
                cascade_defs,
                extra_target_names=registered_names,
            )
            self._bind_cascade_delete(collection, compiled_query)

    def _attach_state_graph(self, collection: StateGraphCollection) -> None:
        """Attach ``transition`` for state-graph collections."""
        edge_defs = getattr(type(collection), "EDGES", [])
        if not edge_defs:
            return

        edge_name = _collection_name_for_class(edge_defs[0].via)
        cast("Any", collection).transition = lambda file_ids, from_state, to_state: verbs.transition(
            self._db, edge_name, file_ids, from_state, to_state
        )

    def _build_get_callable(self, collection: CollectionInstance) -> _CollectionGetVerb:
        """Build a collection-level get callable using flat field criteria."""
        return _CollectionGetVerb(self._db, collection)

    def _build_count_callable(self, collection_name: str) -> Callable[..., int]:
        """Build a collection-level count callable."""

        def count(*args: FieldValue, **kwargs: Any) -> int:
            criteria = _normalize_field_criteria(*args, **kwargs)
            if not criteria:
                return verbs.count_all(self._db, collection_name)
            if len(criteria) == 1:
                field_name, value = next(iter(criteria.items()))
                return verbs.count_by_field(self._db, collection_name, field_name, value)
            return verbs.count_by_filter(self._db, collection_name, criteria)

        return count

    def _build_update_callable(self, collection_name: str) -> Callable[..., None]:
        """Build a collection-level update callable using flat keyword criteria."""

        def update(*args: FieldValue, fields: Document, **kwargs: Any) -> None:
            criteria = _normalize_field_criteria(*args, **kwargs)
            if not criteria:
                msg = "update() requires at least one field criterion"
                raise ValueError(msg)
            if len(criteria) == 1:
                field_name, value = next(iter(criteria.items()))
                verbs.update_by_field(self._db, collection_name, field_name, value, fields)
                return
            verbs.update_by_filter(self._db, collection_name, criteria, fields)

        return update

    def _build_upsert_callable(self, collection_name: str) -> Callable[..., list[str]]:
        """Build a collection-level upsert callable using flat keyword criteria."""

        def upsert(*args: FieldValue, fields: Document, **kwargs: Any) -> list[str]:
            criteria = _normalize_field_criteria(*args, **kwargs)
            if not criteria:
                msg = "upsert() requires at least one field criterion"
                raise ValueError(msg)
            doc = {**criteria, **fields}
            if len(criteria) == 1:
                field_name = next(iter(criteria))
                return verbs.upsert_by_field(self._db, collection_name, field_name, [doc])
            return verbs.upsert_by_field(self._db, collection_name, list(criteria), [doc])

        return upsert

    def _build_upsert_batch_callable(self, collection_name: str) -> Callable[..., list[str]]:
        """Build a collection-level upsert_batch callable for bulk upserts."""

        def upsert_batch(docs: list[Document], match_fields: str | list[str]) -> list[str]:
            if not docs:
                return []
            return verbs.upsert_by_field(self._db, collection_name, match_fields, docs)

        return upsert_batch

    def _build_aggregate_callable(self, collection_name: str) -> Callable[..., list[AggResult]]:
        """Build a collection-level aggregate callable."""

        def aggregate(
            field_name: str,
            *,
            filter: dict[str, Any] | None = None,
            limit: int | None = None,
            offset: int = 0,
        ) -> list[AggResult]:
            return verbs.aggregate_field(
                self._db,
                collection_name,
                field_name,
                filter=filter,
                limit=limit,
                offset=offset,
            )

        return aggregate

    def _build_upsert_vector_callable(self, collection_name: str) -> Callable[..., None]:
        """Build the hot-tier ``upsert_vector`` callable."""

        def upsert_vector(
            file_id: str,
            model_suite_hash: str,
            embed_dim: int,
            vector: list[float],
            num_segments: int,
        ) -> None:
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
                "created_at": now_ms().value,
            }
            verbs.upsert_by_field(self._db, collection_name, "_key", [doc])
            verbs.upsert_file_has_vectors_edge(self._db, file_id, f"{collection_name}/{_key}")

        return upsert_vector

    def _compile_cascade_query(
        self,
        owner_cls: type[CollectionInstance],
        collection_name: str,
        cascade_defs: list[EdgeDef],
        extra_target_names: list[str] | None = None,
    ) -> str:
        """Compile a static cascade-delete AQL template for one collection class.

        Args:
            owner_cls: Root collection class whose reachable cascade edges define
                the delete traversal.
            collection_name: ArangoDB collection name for the root documents
                being deleted.
            cascade_defs: Edge definitions declared for the root collection and
                used as a fallback when reachable cascade edge names have not
                been precomputed.
            extra_target_names: Additional runtime collection names to include in
                the delete target set. Used to cover dynamic vector collections
                registered after construction.

        Returns:
            The compiled AQL query string.  Bind variable ``@starts`` must be a
            non-empty list of root document ``_id`` strings.  The query deletes
            every root document in ``@starts``, any reachable orphaned descendant
            documents, and all relevant edge documents.
        """
        cascade_edge_names = self._cascade_edge_names_for_root(owner_cls)
        all_edge_names = sorted(
            [
                _collection_name_for_class(cast("type[object]", cls))
                for cls in _iter_subclasses(EdgeCollection)
                if _is_concrete_collection_class(cast("type[object]", cls))
            ]
        )
        target_collection_names = sorted(
            {
                _collection_name_for_class(cast("type[object]", cls))
                for cls in _iter_subclasses(DocumentCollection) | _iter_subclasses(VectorCollection)
                if _is_concrete_collection_class(cast("type[object]", cls))
            }
            - {collection_name}
        )
        if extra_target_names:
            target_collection_names = sorted(set(target_collection_names) | set(extra_target_names) - {collection_name})

        if not cascade_edge_names:
            cascade_edge_names = [_collection_name_for_class(edge.via) for edge in cascade_defs]
        if not all_edge_names:
            all_edge_names = cascade_edge_names[:]

        cascade_edges_clause = ", ".join(cascade_edge_names)
        all_edges_clause = ", ".join(all_edge_names)

        # Phase 1: Pure read — collect all ids up front into LET subqueries so that
        # no collection is read after any write has begun (avoids ERR 1579).
        lines = [
            "LET subgraph = (",
            "    FOR start_id IN @starts",
            f"        FOR v IN 1..100 OUTBOUND start_id {cascade_edges_clause}",
            '            OPTIONS {bfs: true, uniqueVertices: "global"}',
            "            RETURN v",
            ")",
            "LET subgraph_ids = UNIQUE(FOR doc IN subgraph RETURN doc._id)",
            "LET orphan_ids = (",
            "    FOR candidate IN subgraph",
            "        LET external_inbound = (",
            f"            FOR parent IN 1..1 INBOUND candidate._id {all_edges_clause}",
            "                FILTER parent._id NOT IN @starts AND parent._id NOT IN subgraph_ids",
            "                LIMIT 1",
            "                RETURN 1",
            "        )",
            "        FILTER LENGTH(external_inbound) == 0",
            "        RETURN candidate._id",
            ")",
        ]

        for idx, edge_name in enumerate(cascade_edge_names):
            var = f"edge_keys_{idx}"
            lines.extend(
                [
                    f"LET {var} = (",
                    f"    FOR e IN {edge_name}",
                    "        FILTER e._from IN @starts OR e._from IN orphan_ids OR e._to IN orphan_ids OR e._to IN @starts",
                    "        RETURN e._key",
                    ")",
                ]
            )

        # Phase 2: Pure write — all collections read above are now fully materialised.
        for idx, target_collection_name in enumerate(target_collection_names):
            var = f"orphan_id_{idx}"
            lines.extend(
                [
                    f'FOR {var} IN orphan_ids FILTER STARTS_WITH({var}, "{target_collection_name}/")',
                    f"    REMOVE PARSE_IDENTIFIER({var}).key IN {target_collection_name}",
                ]
            )

        for idx, edge_name in enumerate(cascade_edge_names):
            var = f"edge_keys_{idx}"
            lines.extend(
                [
                    f"FOR key_{idx} IN {var}",
                    f"    REMOVE key_{idx} IN {edge_name}",
                ]
            )

        lines.extend(
            [
                "FOR start_id IN @starts",
                f"    REMOVE PARSE_IDENTIFIER(start_id).key IN {collection_name}",
                "RETURN 1",
            ]
        )
        return "\n".join(lines)

    def _cascade_edge_names_for_root(self, root_cls: type[CollectionInstance]) -> list[str]:
        """Collect all cascade edge collection names reachable from ``root_cls``."""
        names: list[str] = []
        seen: set[type[object]] = set()

        def visit(collection_cls: type[object]) -> None:
            if collection_cls in seen:
                return
            seen.add(collection_cls)
            for edge_def in getattr(collection_cls, "EDGES", []):
                if edge_def.on_delete != CASCADE or edge_def.direction != OUTBOUND:
                    continue
                edge_name = _collection_name_for_class(edge_def.via)
                if edge_name not in names:
                    names.append(edge_name)
                visit(edge_def.target)

        visit(root_cls)
        return names

    def _validate_cascade_dag(self) -> None:
        """Validate that the CASCADE edge graph across collection classes is acyclic."""
        graph: dict[type[object], list[type[object]]] = {}
        roots = {
            cls
            for cls in _iter_subclasses(DocumentCollection) | _iter_subclasses(VectorCollection)
            if _is_concrete_collection_class(cast("type[object]", cls))
        }
        for collection_cls in roots:
            graph[collection_cls] = [
                edge_def.target
                for edge_def in getattr(collection_cls, "EDGES", [])
                if edge_def.on_delete == CASCADE and edge_def.direction == OUTBOUND
            ]

        visiting: set[type[object]] = set()
        visited: set[type[object]] = set()

        def visit(node: type[object]) -> None:
            if node in visited:
                return
            if node in visiting:
                msg = f"CASCADE edges must form a DAG; cycle detected at {_collection_name_for_class(node)}"
                raise ValueError(msg)

            visiting.add(node)
            for target in graph.get(node, []):
                visit(target)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
