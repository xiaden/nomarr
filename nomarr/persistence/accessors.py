"""Thin field and collection accessors for collection-first persistence.

This module is intentionally side-effect free: it defines accessor classes only
and executes no queries at import time. The callables here are compatibility
adapters over collection-owned generic operations, with `FieldAccessor` wired
via `BaseCollection._field()` as the building block for legacy field access.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base_types import Field
from nomarr.persistence.query_specs import (
    AggregateQuerySpec,
    PaginationSpec,
    QueryCriterion,
    QueryOperator,
    ReadQuerySpec,
    WriteQuerySpec,
)

Document = dict[str, Any]
CriterionInput = QueryCriterion | Mapping[str, object]


def _field_query_criterion(field_name: str, operator: QueryOperator, value: object) -> QueryCriterion:
    """Build a normalized single-field criterion for compatibility shims."""
    return QueryCriterion(field_name=field_name, operator=operator, value=value)


def _build_field_read_query_spec(
    collection_name: str,
    *,
    field_name: str,
    operator: QueryOperator,
    value: object,
    limit: int | None = None,
    offset: int = 0,
) -> ReadQuerySpec:
    """Materialize the collection-first read spec used by field-first adapters."""
    return ReadQuerySpec(
        collection_name=collection_name,
        criteria=(_field_query_criterion(field_name, operator, value),),
        pagination=PaginationSpec(limit=limit, offset=offset),
    )


def _build_field_write_query_spec(
    collection_name: str,
    *,
    field_name: str,
    operator: QueryOperator,
    value: object,
    fields: Document | None = None,
) -> WriteQuerySpec:
    """Materialize the collection-first write spec used by field-first adapters."""
    if fields is None:
        return WriteQuerySpec(
            collection_name=collection_name,
            criteria=(_field_query_criterion(field_name, operator, value),),
        )
    return WriteQuerySpec(
        collection_name=collection_name,
        criteria=(_field_query_criterion(field_name, operator, value),),
        payload=fields,
    )


def _build_field_count_query_spec(collection_name: str, *, field_name: str, value: object) -> AggregateQuerySpec:
    """Materialize the collection-first count spec used by field-first adapters."""
    return AggregateQuerySpec(
        collection_name=collection_name,
        criteria=(_field_query_criterion(field_name, QueryOperator.EQ, value),),
    )


def _build_field_collect_query_spec(
    collection_name: str,
    *,
    field_name: str,
    limit: int | None = None,
    offset: int = 0,
) -> AggregateQuerySpec:
    """Materialize the collection-first aggregate spec used by field-first collect shims."""
    return AggregateQuerySpec(
        collection_name=collection_name,
        aggregate_fields=(field_name,),
        pagination=PaginationSpec(limit=limit, offset=offset),
    )


class SupportsCollectionFirstSurface(Protocol):
    """Protocol for collection-owned generic persistence operations."""

    _db: SafeDatabase
    _name: str

    def _collection_get(
        self,
        *args: Field,
        criteria: Sequence[CriterionInput] | None = None,
        query_spec: ReadQuerySpec | None = None,
        limit: int | None = None,
        offset: int = 0,
        force_many: bool = False,
        **kwargs: Any,
    ) -> Document | None | list[Document]: ...

    def _collection_delete(
        self,
        *args: Field,
        criteria: Sequence[CriterionInput] | None = None,
        query_spec: WriteQuerySpec | None = None,
        **kwargs: Any,
    ) -> int: ...

    def insert(self, docs: list[Document]) -> list[str]: ...

    def update(
        self,
        *args: Field,
        fields: Document | None = None,
        criteria: Sequence[CriterionInput] | None = None,
        query_spec: WriteQuerySpec | None = None,
        **kwargs: Any,
    ) -> None: ...

    def upsert(
        self,
        *args: Field,
        fields: Document | None = None,
        criteria: Sequence[CriterionInput] | None = None,
        query_spec: WriteQuerySpec | None = None,
        **kwargs: Any,
    ) -> list[str]: ...

    def upsert_batch(self, docs: list[Document], match_fields: str | list[str]) -> list[str]: ...

    def count(
        self,
        *args: Field,
        criteria: Sequence[CriterionInput] | None = None,
        query_spec: AggregateQuerySpec | None = None,
        **kwargs: Any,
    ) -> int: ...

    def aggregate(
        self,
        field_name: str | None = None,
        *,
        filter: dict[str, Any] | None = None,
        criteria: Sequence[CriterionInput] | None = None,
        query_spec: AggregateQuerySpec | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Any]: ...

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
    ) -> list[Document]: ...

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
    ) -> list[Document]: ...


class FieldGet:
    """Compatibility read shim for one collection field.

    This is an adapter over the collection-first generic surface. Only the
    normalized read capabilities intentionally remain here: equality, in-set,
    range, and pattern reads. Any new generic read capability belongs on the
    collection root first and may gain a field shim only through explicit design
    review.
    """

    def __init__(self, owner: SupportsCollectionFirstSurface, field: str, unique: bool) -> None:
        self._owner = owner
        self._db = owner._db
        self._collection = owner._name
        self._field = field
        self._unique = unique

    def __call__(self, value: Any) -> Document | None | list[Document]:
        return self._owner._collection_get(
            query_spec=_build_field_read_query_spec(
                self._collection,
                field_name=self._field,
                operator=QueryOperator.EQ,
                value=value,
            ),
        )

    def many(self, value: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return cast(
            "list[Document]",
            self._owner._collection_get(
                query_spec=_build_field_read_query_spec(
                    self._collection,
                    field_name=self._field,
                    operator=QueryOperator.EQ,
                    value=value,
                    limit=limit,
                    offset=offset,
                ),
                force_many=True,
            ),
        )

    def in_(self, values: list[Any], *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return cast(
            "list[Document]",
            self._owner._collection_get(
                query_spec=_build_field_read_query_spec(
                    self._collection,
                    field_name=self._field,
                    operator=QueryOperator.IN,
                    value=values,
                    limit=limit,
                    offset=offset,
                ),
                force_many=True,
            ),
        )

    def gte(self, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return cast(
            "list[Document]",
            self._owner._collection_get(
                query_spec=_build_field_read_query_spec(
                    self._collection,
                    field_name=self._field,
                    operator=QueryOperator.GTE,
                    value=threshold,
                    limit=limit,
                    offset=offset,
                ),
                force_many=True,
            ),
        )

    def lte(self, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return cast(
            "list[Document]",
            self._owner._collection_get(
                query_spec=_build_field_read_query_spec(
                    self._collection,
                    field_name=self._field,
                    operator=QueryOperator.LTE,
                    value=threshold,
                    limit=limit,
                    offset=offset,
                ),
                force_many=True,
            ),
        )

    def like(self, pattern: str, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return cast(
            "list[Document]",
            self._owner._collection_get(
                query_spec=_build_field_read_query_spec(
                    self._collection,
                    field_name=self._field,
                    operator=QueryOperator.LIKE,
                    value=pattern,
                    limit=limit,
                    offset=offset,
                ),
                force_many=True,
            ),
        )


class FieldDelete:
    """Compatibility delete shim for a single collection field.

    Only normalized single-field delete mappings remain here: equality and
    in-set delete. Broader delete semantics belong on the collection root.
    """

    def __init__(self, owner: SupportsCollectionFirstSurface, field: str) -> None:
        self._owner = owner
        self._db = owner._db
        self._collection = owner._name
        self._field = field

    def __call__(self, value: Any) -> int:
        return self._owner._collection_delete(
            query_spec=_build_field_write_query_spec(
                self._collection,
                field_name=self._field,
                operator=QueryOperator.EQ,
                value=value,
            ),
        )

    def in_(self, values: list[Any]) -> int:
        return self._owner._collection_delete(
            query_spec=_build_field_write_query_spec(
                self._collection,
                field_name=self._field,
                operator=QueryOperator.IN,
                value=values,
            ),
        )


class FieldAccessor:
    """Compatibility shim for one named field on a collection.

    Created in each collection's ``__init__`` via ``self._field(name, unique=...)``.
    The collection-first surface owns generic persistence behavior; this class
    only preserves the intentionally supported legacy field-first adapters:

    - ``get`` equality / in-set / range / pattern reads
    - single-field ``update`` and ``upsert``
    - single-field ``delete``
    - single-field ``count``
    - collect-like access to one aggregate field

    Do not grow this surface with new field-first helpers. New generic behavior
    belongs on the collection root first so downstream Parts C and D can reason
    about a single normative API.
    """

    def __init__(self, owner: SupportsCollectionFirstSurface, field: str, unique: bool = False) -> None:
        self._owner = owner
        self._db = owner._db
        self._collection = owner._name
        self._field = field
        self._unique = unique
        self.get = FieldGet(owner, field, unique)
        self.delete = FieldDelete(owner, field)

    def _query_field_metadata(self) -> dict[str, str | bool]:
        """Return minimal metadata for collection-first query-spec validation."""
        return {
            "name": self._field,
            "unique": self._unique,
        }

    def update(self, value: Any, fields: Document) -> None:
        """Single-field equality update shim; delegates to the collection-first ``update()`` root."""
        self._owner.update(
            query_spec=_build_field_write_query_spec(
                self._collection,
                field_name=self._field,
                operator=QueryOperator.EQ,
                value=value,
                fields=fields,
            ),
        )

    def upsert(self, value: Any, fields: Document) -> list[str]:
        """Single-field equality upsert shim; delegates to the collection-first ``upsert()`` root."""
        return self._owner.upsert(
            query_spec=_build_field_write_query_spec(
                self._collection,
                field_name=self._field,
                operator=QueryOperator.EQ,
                value=value,
                fields=fields,
            ),
        )

    def count(self, value: Any) -> int:
        """Single-field equality count shim; delegates to the collection-first ``count()`` root."""
        return self._owner.count(
            query_spec=_build_field_count_query_spec(
                self._collection,
                field_name=self._field,
                value=value,
            ),
        )

    def collect(self, *, limit: int | None = None, offset: int = 0) -> list[Any]:
        """Single-field aggregate collect shim; delegates to the collection-first ``aggregate()`` root and extracts the ``value`` key."""
        rows = self._owner.aggregate(
            query_spec=_build_field_collect_query_spec(
                self._collection,
                field_name=self._field,
                limit=limit,
                offset=offset,
            ),
        )
        return [row["value"] for row in rows if isinstance(row, dict) and "value" in row]


class CollectionGet:
    """Instance-bound collection read root that delegates into collection-owned logic."""

    def __init__(self, owner: SupportsCollectionFirstSurface) -> None:
        self._owner = owner
        self._db = owner._db
        self._collection = owner._name

    def _build_query_spec(
        self,
        criteria: Sequence[QueryCriterion],
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> ReadQuerySpec:
        return ReadQuerySpec(
            collection_name=self._collection,
            criteria=tuple(criteria),
            pagination=PaginationSpec(limit=limit, offset=offset),
        )

    def __call__(
        self,
        *args: Field,
        criteria: Sequence[CriterionInput] | None = None,
        query_spec: ReadQuerySpec | None = None,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> Document | None | list[Document]:
        """Delegate to the collection-first read root; returns a single document or list depending on criteria specificity."""
        return self._owner._collection_get(
            *args,
            criteria=criteria,
            query_spec=query_spec,
            limit=limit,
            offset=offset,
            **kwargs,
        )

    def many(
        self,
        *args: Field,
        criteria: Sequence[CriterionInput] | None = None,
        query_spec: ReadQuerySpec | None = None,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[Document]:
        return cast(
            "list[Document]",
            self._owner._collection_get(
                *args,
                criteria=criteria,
                query_spec=query_spec,
                limit=limit,
                offset=offset,
                force_many=True,
                **kwargs,
            ),
        )

    def in_(self, *args: Field, limit: int | None = None, offset: int = 0, **kwargs: Any) -> list[Document]:
        criterion = _coerce_single_operator_criterion(*args, operator=QueryOperator.IN, **kwargs)
        return cast(
            "list[Document]",
            self._owner._collection_get(
                query_spec=self._build_query_spec((criterion,), limit=limit, offset=offset),
                force_many=True,
            ),
        )

    def gte(self, field_name: str, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return cast(
            "list[Document]",
            self._owner._collection_get(
                query_spec=self._build_query_spec(
                    (QueryCriterion(field_name, QueryOperator.GTE, threshold),),
                    limit=limit,
                    offset=offset,
                ),
                force_many=True,
            ),
        )

    def lte(self, field_name: str, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return cast(
            "list[Document]",
            self._owner._collection_get(
                query_spec=self._build_query_spec(
                    (QueryCriterion(field_name, QueryOperator.LTE, threshold),),
                    limit=limit,
                    offset=offset,
                ),
                force_many=True,
            ),
        )

    def like(self, field_name: str, pattern: str, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return cast(
            "list[Document]",
            self._owner._collection_get(
                query_spec=self._build_query_spec(
                    (QueryCriterion(field_name, QueryOperator.LIKE, pattern),),
                    limit=limit,
                    offset=offset,
                ),
                force_many=True,
            ),
        )


class CollectionDelete:
    """Instance-bound collection delete root that delegates into collection-owned logic."""

    def __init__(self, owner: SupportsCollectionFirstSurface) -> None:
        self._owner = owner
        self._db = owner._db
        self._collection = owner._name
        self.cascade: Callable[[list[str]], int] | None = None  # injected by _attach_cascade()

    def _build_query_spec(self, criteria: Sequence[QueryCriterion]) -> WriteQuerySpec:
        return WriteQuerySpec(collection_name=self._collection, criteria=tuple(criteria))

    def __call__(
        self,
        *args: Field,
        criteria: Sequence[CriterionInput] | None = None,
        query_spec: WriteQuerySpec | None = None,
        **kwargs: Any,
    ) -> int:
        """Delegate to the collection-first delete root; returns the count of deleted documents."""
        return self._owner._collection_delete(*args, criteria=criteria, query_spec=query_spec, **kwargs)

    def in_(self, *args: Field, **kwargs: Any) -> int:
        criterion = _coerce_single_operator_criterion(*args, operator=QueryOperator.IN, **kwargs)
        return self._owner._collection_delete(query_spec=self._build_query_spec((criterion,)))

    def unreferenced(self, edge_collection: str) -> int:
        """Delete documents from this collection that have no inbound edges in ``edge_collection``."""
        from nomarr.persistence.constructor import verbs

        return verbs.delete_unreferenced(self._db, self._collection, edge_collection)


def _coerce_single_operator_criterion(
    *args: Field,
    operator: QueryOperator,
    **kwargs: Any,
) -> QueryCriterion:
    if len(args) > 1 or (args and kwargs):
        raise ValueError("exactly one criterion is required")
    if args:
        field_name = args[0].name
        value = args[0].value
    elif len(kwargs) == 1:
        field_name, value = next(iter(kwargs.items()))
    else:
        raise ValueError("exactly one criterion is required")
    return QueryCriterion(field_name=str(field_name), operator=operator, value=value)
