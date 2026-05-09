"""Base collection classes for the collection-first persistence layer.

This module provides the structural foundation for collection wrappers;
concrete classes in `nomarr.persistence.collections` subclass these bases.
The classes model collection families and delegate all AQL execution to
`nomarr.persistence.constructor.verbs`.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any, ClassVar, Protocol, cast

from nomarr.helpers.time_helper import internal_ms
from nomarr.persistence.accessors import CollectionDelete, CollectionGet, FieldAccessor
from nomarr.persistence.aql_validation import (
    validate_query_spec,
    validate_spec_template_contract,
    validate_template_bindings,
)
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base_types import EdgeDef, Field, collection_name_for_class
from nomarr.persistence.query_specs import (
    AggregateQuerySpec,
    PaginationSpec,
    QueryCriterion,
    QueryOperator,
    ReadQuerySpec,
    SortDirection,
    SortFieldSpec,
    WriteQuerySpec,
)
from nomarr.persistence.query_templates import QueryTemplateId

Document = dict[str, Any]


_UNBOUNDED_TEMPLATE_LIMIT = 2**31 - 1


class _ConstructorVerbsModule(Protocol):
    def update_by_field(self, *args: object, **kwargs: object) -> None: ...

    def update_by_filter(self, *args: object, **kwargs: object) -> None: ...

    def delete_by_field(self, *args: object, **kwargs: object) -> int: ...

    def delete_in_by_field(self, *args: object, **kwargs: object) -> int: ...

    def delete_by_filter(self, *args: object, **kwargs: object) -> int: ...

    def update_many_by_key(self, *args: object, **kwargs: object) -> None: ...

    def count_inbound_connections(self, *args: object, **kwargs: object) -> list[Document]: ...

    def count_outbound_connections(self, *args: object, **kwargs: object) -> list[Document]: ...

    def truncate(self, *args: object, **kwargs: object) -> None: ...

    def traversal_by_id(self, *args: object, **kwargs: object) -> list[Document]: ...

    def traversal_by_ids(self, *args: object, **kwargs: object) -> list[Document]: ...

    def transition(self, *args: object, **kwargs: object) -> None: ...

    def upsert_file_has_vectors_edge(self, *args: object, **kwargs: object) -> None: ...

    def ann_search(self, *args: object, **kwargs: object) -> list[Document]: ...

    def move_collection(self, *args: object, **kwargs: object) -> int: ...


def _constructor_verbs() -> _ConstructorVerbsModule:
    """Import constructor verbs lazily to avoid persistence init cycles."""
    from nomarr.persistence.constructor import verbs as constructor_verbs

    return cast("_ConstructorVerbsModule", constructor_verbs)


class BaseCollection:
    """Abstract base for ArangoDB collection wrappers.

    Stores the `SafeDatabase` handle, collection name, a `_fields` registry of
    `FieldAccessor` instances, and collection-level generic operations.
    Subclasses register typed field accessors by calling `_field()` from their
    `__init__` methods. Field accessors are compatibility adapters over this
    collection-owned surface.
    """

    COLLECTION_FAMILY: ClassVar[str] = "base"

    def __init__(self, db: SafeDatabase, name: str) -> None:
        self._db = db
        self._name = name
        self._fields: dict[str, FieldAccessor] = {}
        self.get = CollectionGet(self)
        self.delete = CollectionDelete(self)

    def _field(self, field_name: str, *, unique: bool = False) -> FieldAccessor:
        """Register a field accessor compatibility shim for this collection."""
        accessor = FieldAccessor(self, field_name, unique=unique)
        self._fields[field_name] = accessor
        return accessor

    def _query_collection_metadata(self) -> dict[str, object]:
        """Return minimal metadata for collection-first query-spec validation."""
        return {
            "collection_name": self._name,
            "collection_family": self.COLLECTION_FAMILY,
            "fields": {field_name: accessor._query_field_metadata() for field_name, accessor in self._fields.items()},
        }

    def _collection_get(
        self,
        *args: Field,
        criteria: Sequence[QueryCriterion | Mapping[str, object]] | None = None,
        query_spec: ReadQuerySpec | None = None,
        limit: int | None = None,
        offset: int = 0,
        force_many: bool = False,
        **kwargs: Any,
    ) -> Document | None | list[Document]:
        if query_spec is None:
            query_spec = ReadQuerySpec(
                collection_name=self._name,
                criteria=self._coerce_criteria(*args, criteria=criteria, **kwargs),
                pagination=PaginationSpec(limit=limit, offset=offset),
            )
        else:
            self._reject_mixed_query_inputs(
                query_spec=query_spec,
                args=args,
                criteria=criteria,
                kwargs=kwargs,
                limit=limit,
                offset=offset,
            )

        single_document = not force_many and self._returns_single_document(query_spec)
        bound_template = self._bind_template(
            query_spec,
            QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
            bind_vars={
                "@collection": self._name,
                "criteria": self._serialize_criteria(query_spec.criteria),
                "sort_field": query_spec.sort[0].field_name if query_spec.sort else None,
                "sort_direction": query_spec.sort[0].direction.value if query_spec.sort else None,
                "offset": query_spec.pagination.offset,
                "limit": 1 if single_document else self._template_limit(query_spec.pagination.limit),
            },
        )

        cursor = self._execute_bound_template(bound_template)
        if single_document:
            return cast("Document | None", next(cursor, None))
        return [cast("Document", row) for row in cursor]

    def insert(self, docs: list[Document]) -> list[str]:
        """Insert documents into the collection through a reviewed template."""
        payload = self._payload_union(docs)
        query_spec = WriteQuerySpec(collection_name=self._name, payload=payload)
        bound_template = self._bind_template(
            query_spec,
            QueryTemplateId.DOCUMENT_WRITE_INSERT_MANY,
            bind_vars={
                "@collection": self._name,
                "docs": docs,
            },
        )
        cursor = self._execute_bound_template(bound_template)
        return [cast("str", row) for row in cursor]

    def count(
        self,
        *args: Field,
        criteria: Sequence[QueryCriterion | Mapping[str, object]] | None = None,
        query_spec: AggregateQuerySpec | None = None,
        **kwargs: Any,
    ) -> int:
        """Count documents matching collection-first criteria or an aggregate spec."""
        if query_spec is None:
            query_spec = AggregateQuerySpec(
                collection_name=self._name,
                criteria=self._coerce_criteria(*args, criteria=criteria, **kwargs),
            )
        else:
            self._reject_mixed_query_inputs(query_spec=query_spec, args=args, criteria=criteria, kwargs=kwargs)
            if query_spec.aggregate_fields:
                raise ValueError("count() does not accept aggregate fields; use aggregate() instead")

        bound_template = self._bind_template(
            query_spec,
            QueryTemplateId.AGGREGATION_COUNT_BY_CRITERIA,
            bind_vars={
                "@collection": self._name,
                "criteria": self._serialize_criteria(query_spec.criteria),
            },
        )
        cursor = self._execute_bound_template(bound_template)
        return cast("int", next(cursor, 0))

    def update(
        self,
        *args: Field,
        fields: Document | None = None,
        criteria: Sequence[QueryCriterion | Mapping[str, object]] | None = None,
        query_spec: WriteQuerySpec | None = None,
        **kwargs: Any,
    ) -> None:
        """Update documents matched by validated collection-first equality criteria."""
        if query_spec is None:
            if fields is None:
                raise ValueError("update() requires fields= when query_spec is not supplied")
            query_spec = WriteQuerySpec(
                collection_name=self._name,
                criteria=self._coerce_criteria(*args, criteria=criteria, **kwargs),
                payload=fields,
            )
        else:
            self._reject_mixed_query_inputs(query_spec=query_spec, args=args, criteria=criteria, kwargs=kwargs)
            if fields is not None:
                raise ValueError("update() cannot combine fields= with query_spec=")

        if not query_spec.criteria:
            raise ValueError("update() requires at least one criterion")
        validate_query_spec(query_spec, {self._name: self})
        filter_dict = self._criteria_to_equality_filter(query_spec.criteria, operation_name="update")
        if len(filter_dict) == 1:
            field_name, value = next(iter(filter_dict.items()))
            _constructor_verbs().update_by_field(self._db, self._name, field_name, value, dict(query_spec.payload))
            return
        _constructor_verbs().update_by_filter(self._db, self._name, filter_dict, dict(query_spec.payload))

    def upsert(
        self,
        *args: Field,
        fields: Document | None = None,
        criteria: Sequence[QueryCriterion | Mapping[str, object]] | None = None,
        query_spec: WriteQuerySpec | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Upsert one document through the reviewed batch-upsert template."""
        if query_spec is None:
            if fields is None:
                raise ValueError("upsert() requires fields= when query_spec is not supplied")
            normalized_criteria = self._coerce_criteria(*args, criteria=criteria, **kwargs)
            if not normalized_criteria:
                raise ValueError("upsert() requires at least one criterion")
            query_spec = WriteQuerySpec(
                collection_name=self._name,
                criteria=normalized_criteria,
                payload=fields,
                match_fields=tuple(criterion.field_name for criterion in normalized_criteria),
            )
        else:
            self._reject_mixed_query_inputs(query_spec=query_spec, args=args, criteria=criteria, kwargs=kwargs)
            if fields is not None:
                raise ValueError("upsert() cannot combine fields= with query_spec=")
            if not query_spec.criteria:
                raise ValueError("upsert() requires at least one criterion")
            if not query_spec.match_fields:
                query_spec = WriteQuerySpec(
                    collection_name=query_spec.collection_name,
                    criteria=query_spec.criteria,
                    payload=query_spec.payload,
                    match_fields=tuple(criterion.field_name for criterion in query_spec.criteria),
                )

        doc = self._materialize_upsert_doc(query_spec)
        bound_template = self._bind_template(
            query_spec,
            QueryTemplateId.DOCUMENT_WRITE_UPSERT_MANY,
            bind_vars={
                "@collection": self._name,
                "docs": [doc],
                "match_fields": list(query_spec.match_fields),
            },
        )
        cursor = self._execute_bound_template(bound_template)
        return [cast("str", row) for row in cursor]

    def upsert_batch(self, docs: list[Document], match_fields: str | list[str]) -> list[str]:
        """Upsert a batch of documents through the reviewed batch-upsert template."""
        if not docs:
            return []

        normalized_match_fields = (match_fields,) if isinstance(match_fields, str) else tuple(match_fields)
        query_spec = WriteQuerySpec(
            collection_name=self._name,
            payload=self._payload_union(docs),
            match_fields=normalized_match_fields,
        )
        bound_template = self._bind_template(
            query_spec,
            QueryTemplateId.DOCUMENT_WRITE_UPSERT_MANY,
            bind_vars={
                "@collection": self._name,
                "docs": docs,
                "match_fields": list(normalized_match_fields),
            },
        )
        cursor = self._execute_bound_template(bound_template)
        return [cast("str", row) for row in cursor]

    def _collection_delete(
        self,
        *args: Field,
        criteria: Sequence[QueryCriterion | Mapping[str, object]] | None = None,
        query_spec: WriteQuerySpec | None = None,
        **kwargs: Any,
    ) -> int:
        if query_spec is None:
            query_spec = WriteQuerySpec(
                collection_name=self._name,
                criteria=self._coerce_criteria(*args, criteria=criteria, **kwargs),
            )
        else:
            self._reject_mixed_query_inputs(query_spec=query_spec, args=args, criteria=criteria, kwargs=kwargs)

        if query_spec.payload:
            raise ValueError("delete() does not accept a write payload")
        if query_spec.match_fields:
            raise ValueError("delete() does not accept match_fields")

        validate_query_spec(query_spec, {self._name: self})
        if not query_spec.criteria:
            self.truncate()
            return 0
        if len(query_spec.criteria) == 1:
            criterion = query_spec.criteria[0]
            if criterion.operator is QueryOperator.EQ:
                return _constructor_verbs().delete_by_field(self._db, self._name, criterion.field_name, criterion.value)
            if criterion.operator is QueryOperator.IN:
                return _constructor_verbs().delete_in_by_field(
                    self._db,
                    self._name,
                    criterion.field_name,
                    cast("list[Any]", criterion.value),
                )

        filter_dict = self._criteria_to_equality_filter(query_spec.criteria, operation_name="delete")
        return _constructor_verbs().delete_by_filter(self._db, self._name, filter_dict)

    def update_many(self, docs: list[Document]) -> None:
        """Bulk-update documents in the collection by `_key`."""
        _constructor_verbs().update_many_by_key(self._db, self._name, docs)

    def aggregate(
        self,
        field_name: str | None = None,
        *,
        filter: dict[str, Any] | None = None,
        criteria: Sequence[QueryCriterion | Mapping[str, object]] | None = None,
        query_spec: AggregateQuerySpec | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list:
        """Aggregate one field through the reviewed collection-first aggregate template."""
        if query_spec is None:
            if field_name is None:
                raise ValueError("aggregate() requires a field_name or query_spec=")
            query_spec = AggregateQuerySpec(
                collection_name=self._name,
                criteria=self._coerce_criteria(criteria=criteria, **(filter or {})),
                aggregate_fields=(field_name,),
                pagination=PaginationSpec(limit=limit, offset=offset),
            )
        else:
            self._reject_mixed_query_inputs(
                query_spec=query_spec,
                criteria=criteria,
                kwargs=filter or {},
                limit=limit,
                offset=offset,
            )
            if field_name is not None and query_spec.aggregate_fields and query_spec.aggregate_fields[0] != field_name:
                raise ValueError("aggregate() field_name does not match query_spec.aggregate_fields")

        if not query_spec.aggregate_fields:
            raise ValueError("aggregate() requires at least one aggregate field")

        bound_template = self._bind_template(
            query_spec,
            QueryTemplateId.AGGREGATION_FIELD_COUNTS,
            bind_vars={
                "@collection": self._name,
                "criteria": self._serialize_criteria(query_spec.criteria),
                "aggregate_field": query_spec.aggregate_fields[0],
                "offset": query_spec.pagination.offset,
                "limit": self._template_limit(query_spec.pagination.limit),
            },
        )
        cursor = self._execute_bound_template(bound_template)
        return list(cursor)

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
        return _constructor_verbs().count_inbound_connections(
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
        return _constructor_verbs().count_outbound_connections(
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
        _constructor_verbs().truncate(self._db, self._name)

    def _reject_mixed_query_inputs(
        self,
        *,
        query_spec: ReadQuerySpec | WriteQuerySpec | AggregateQuerySpec,
        args: tuple[Field, ...] = (),
        criteria: Sequence[QueryCriterion | Mapping[str, object]] | None = None,
        kwargs: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> None:
        if args or criteria is not None or (kwargs is not None and kwargs) or limit is not None or offset != 0:
            raise ValueError(
                f"{type(query_spec).__name__} cannot be combined with ad hoc collection criteria or pagination"
            )

    def _coerce_criteria(
        self,
        *args: Field,
        criteria: Sequence[QueryCriterion | Mapping[str, object]] | None = None,
        operator: QueryOperator = QueryOperator.EQ,
        **kwargs: Any,
    ) -> tuple[QueryCriterion, ...]:
        if criteria is not None:
            if args or kwargs:
                raise ValueError("criteria= cannot be combined with positional or keyword field criteria")
            return tuple(self._coerce_query_criterion(item) for item in criteria)

        normalized = [
            QueryCriterion(field_name=str(field.name), operator=operator, value=field.value) for field in args
        ]
        normalized.extend(
            QueryCriterion(field_name=str(field_name), operator=operator, value=value)
            for field_name, value in kwargs.items()
        )
        return tuple(normalized)

    @staticmethod
    def _coerce_query_criterion(value: QueryCriterion | Mapping[str, object]) -> QueryCriterion:
        if isinstance(value, QueryCriterion):
            return value
        return QueryCriterion(
            field_name=str(value["field_name"]),
            operator=QueryOperator(str(value["operator"])),
            value=value["value"],
        )

    @staticmethod
    def _serialize_criteria(criteria: Sequence[QueryCriterion]) -> list[dict[str, object]]:
        return [
            {
                "field_name": criterion.field_name,
                "operator": criterion.operator.value,
                "value": criterion.value,
            }
            for criterion in criteria
        ]

    @staticmethod
    def _payload_union(docs: Sequence[Mapping[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for doc in docs:
            for key, value in doc.items():
                payload.setdefault(key, value)
        return payload

    @staticmethod
    def _template_limit(limit: int | None) -> int:
        return _UNBOUNDED_TEMPLATE_LIMIT if limit is None else limit

    def _bind_template(
        self,
        query_spec: ReadQuerySpec | WriteQuerySpec | AggregateQuerySpec,
        template_id: QueryTemplateId,
        *,
        bind_vars: Mapping[str, object],
    ):
        validated_contract = validate_spec_template_contract(query_spec, template_id, {self._name: self})
        return validate_template_bindings(
            validated_contract.template_asset,
            bind_vars,
            collection_metadata=validated_contract.collection_metadata,
        )

    def _execute_bound_template(self, bound_template: Any):
        return self._db.aql.execute(bound_template.aql, bind_vars=dict(bound_template.bind_vars))

    def _returns_single_document(self, query_spec: ReadQuerySpec) -> bool:
        if query_spec.sort:
            return False
        if len(query_spec.criteria) != 1:
            return False
        if query_spec.pagination.limit is not None or query_spec.pagination.offset != 0:
            return False
        criterion = query_spec.criteria[0]
        if criterion.operator is not QueryOperator.EQ:
            return False
        field_accessor = self._fields.get(criterion.field_name)
        return field_accessor is not None and field_accessor._unique

    @staticmethod
    def _criteria_to_equality_filter(
        criteria: Sequence[QueryCriterion],
        *,
        operation_name: str,
    ) -> dict[str, object]:
        filter_dict: dict[str, object] = {}
        for criterion in criteria:
            if criterion.operator is not QueryOperator.EQ:
                raise ValueError(f"{operation_name}() only supports equality criteria until a reviewed template exists")
            filter_dict[criterion.field_name] = criterion.value
        return filter_dict

    def _materialize_upsert_doc(self, query_spec: WriteQuerySpec) -> Document:
        criteria_doc = self._criteria_to_equality_filter(query_spec.criteria, operation_name="upsert")
        doc = {**criteria_doc, **dict(query_spec.payload)}
        missing_match_fields = [field_name for field_name in query_spec.match_fields if field_name not in doc]
        if missing_match_fields:
            missing_list = ", ".join(sorted(missing_match_fields))
            raise ValueError(f"upsert() match fields must be present in the merged document: {missing_list}")
        return doc


class DocumentCollection(BaseCollection):
    """Collection wrapper for ArangoDB document collections.

    Registers `_key`, `_id`, and `_rev` field accessors on construction,
    auto-attaches traversal callables declared in the class-level `EDGES`
    list, and receives its cascade-delete callable later from
    `Database._compile_all_cascades()` after all collections are instantiated.
    """

    COLLECTION_FAMILY: ClassVar[str] = "document"
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
            return _constructor_verbs().traversal_by_id(
                db, name, start_id, edge_collection, direction, limit=limit, offset=offset
            )

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

            return _constructor_verbs().traversal_by_ids(
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

    COLLECTION_FAMILY: ClassVar[str] = "edge"

    def __init__(self, db: SafeDatabase, name: str) -> None:
        super().__init__(db, name)
        self._key = self._field("_key", unique=True)
        self._id = self._field("_id", unique=True)
        self._from = self._field("_from")
        self._to = self._field("_to")

    def replace_targets(self, from_ids: list[str], from_target: str, to_target: str) -> None:
        """Replace one edge target with another for the supplied source IDs."""
        _replace_edge_targets(
            self._db,
            self._name,
            from_ids,
            from_target,
            to_target,
        )


def _replace_edge_targets(
    db: SafeDatabase,
    edge_collection: str,
    from_ids: list[str],
    from_target: str,
    to_target: str,
) -> None:
    """Execute the normalized relationship-native edge-target replacement primitive."""
    if not from_ids:
        return

    _constructor_verbs().transition(db, edge_collection, from_ids, from_target, to_target)


class VectorCollection(BaseCollection):
    """Collection wrapper for embedding-vector collections.

    Subclasses declare `VECTOR_TIER` ("hot" or "cold") and `NAME_PATTERN`
    for naming. The base registers the shared vector document fields and
    exposes common vector persistence/retrieval verbs used by the dynamic
    hot/cold collection namespaces returned from ``Database.register()``.
    """

    COLLECTION_FAMILY: ClassVar[str] = "vector"
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
        """Compatibility shim retained for transitional callers after Phase 3 moved live ingestion into vector components."""
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
        _constructor_verbs().upsert_file_has_vectors_edge(self._db, file_id, f"{self._name}/{vector_key}")

    def get_vector(self, file_id: str) -> Document | None:
        """Compatibility shim over collection-first ``get(...)`` retained for transitional callers."""
        query_spec = ReadQuerySpec(
            collection_name=self._name,
            criteria=(QueryCriterion("file_id", QueryOperator.EQ, file_id),),
            sort=(SortFieldSpec("created_at", SortDirection.DESC),),
            pagination=PaginationSpec(limit=1),
        )
        return cast("Document | None", self.get(query_spec=query_spec))

    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[Document]:
        """Compatibility-only seam retained for transitional vector callers."""
        if not file_ids:
            return []
        return cast("list[Document]", self.get.in_(file_id=file_ids))

    def ann_search(
        self,
        vector: list[float],
        limit: int,
        nprobe: int = 10,
        *,
        filter: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Run approximate cosine search against this vector collection."""
        return _constructor_verbs().ann_search(self._db, self._name, vector, limit, nprobe, filter=filter)

    def move_collection(self, dest: str) -> int:
        """Move this collection into ``dest`` using the storage-native maintenance primitive."""
        return _constructor_verbs().move_collection(self._db, self._name, dest)


class StateGraphCollection(DocumentCollection):
    """Document collection wrapper that also models a state-machine graph.

    Pairs the document collection with a companion edge collection to support
    atomic state transitions.
    """

    COLLECTION_FAMILY: ClassVar[str] = "state_graph"

    def __init__(self, db: SafeDatabase, name: str, edge_name: str) -> None:
        super().__init__(db, name)
        self._edge_name = edge_name

    def transition(self, file_ids: list[str], from_state: str, to_state: str) -> None:
        """Compatibility-only seam over edge-level target replacement; state validation remains in components."""
        _replace_edge_targets(self._db, self._edge_name, file_ids, from_state, to_state)
