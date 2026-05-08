from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nomarr.helpers.filter_types import Op
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base_types import Field, _normalize_field_criteria
from nomarr.persistence.constructor import verbs

Document = dict[str, Any]


class FieldGet:
    def __init__(self, db: SafeDatabase, collection: str, field: str, unique: bool) -> None:
        self._db = db
        self._collection = collection
        self._field = field
        self._unique = unique

    def __call__(self, value: Any) -> Document | None | list[Document]:
        if self._unique:
            return verbs.get_one_by_field(self._db, self._collection, self._field, value)
        return verbs.get_many_by_field(self._db, self._collection, self._field, value)

    def many(self, value: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return verbs.get_many_by_field(self._db, self._collection, self._field, value, limit=limit, offset=offset)

    def in_(self, values: list[Any], *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return verbs.get_in_by_field(self._db, self._collection, self._field, values, limit=limit, offset=offset)

    def gte(self, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return verbs.get_range_by_field(
            self._db,
            self._collection,
            self._field,
            {Op.GTE: threshold},
            limit=limit,
            offset=offset,
        )

    def lte(self, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return verbs.get_range_by_field(
            self._db,
            self._collection,
            self._field,
            {Op.LTE: threshold},
            limit=limit,
            offset=offset,
        )

    def like(self, pattern: str, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return verbs.get_like_by_field(self._db, self._collection, self._field, pattern, limit=limit, offset=offset)


class FieldDelete:
    def __init__(self, db: SafeDatabase, collection: str, field: str) -> None:
        self._db = db
        self._collection = collection
        self._field = field

    def __call__(self, value: Any) -> int:
        return verbs.delete_by_field(self._db, self._collection, self._field, value)

    def in_(self, values: list[Any]) -> int:
        return verbs.delete_in_by_field(self._db, self._collection, self._field, values)


class FieldAccessor:
    """Instance-bound accessor for a single named field on a collection.

    Created in each collection's __init__ via self._field("name", unique=True/False).
    Annotate collection attributes as FieldAccessor, not Field[T] or UniqueField[T].
    """

    def __init__(self, db: SafeDatabase, collection: str, field: str, unique: bool = False) -> None:
        self._db = db
        self._collection = collection
        self._field = field
        self._unique = unique
        self.get = FieldGet(db, collection, field, unique)
        self.delete = FieldDelete(db, collection, field)

    def insert(self, docs: list[Document]) -> list[str]:
        return verbs.insert(self._db, self._collection, docs)

    def update(self, value: Any, fields: Document) -> None:
        verbs.update_by_field(self._db, self._collection, self._field, value, fields)

    def upsert(self, value: Any, fields: Document) -> list[str]:
        doc = {self._field: value, **fields}
        return verbs.upsert_by_field(self._db, self._collection, self._field, [doc])

    def upsert_batch(self, docs: list[Document]) -> list[str]:
        return verbs.upsert_by_field(self._db, self._collection, self._field, docs)

    def count(self, value: Any) -> int:
        return verbs.count_by_field(self._db, self._collection, self._field, value)

    def collect(self, *, limit: int | None = None, offset: int = 0) -> list[Any]:
        return verbs.collect_field(self._db, self._collection, self._field, limit=limit, offset=offset)


class CollectionGet:
    def __init__(self, db: SafeDatabase, collection: str, field_accessors: dict[str, FieldAccessor]) -> None:
        self._db = db
        self._collection = collection
        self._fields = field_accessors  # live dict reference — populated by _field() calls

    def __call__(
        self,
        *args: Field,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> Document | None | list[Document]:
        criteria = _normalize_field_criteria(args, kwargs)
        if not criteria:
            return verbs.get_many_by_filter(self._db, self._collection, {}, limit=limit, offset=offset)
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            accessor = self._fields.get(field_name)
            if accessor is not None:
                if limit is None and offset == 0:
                    return accessor.get(value)
                return accessor.get.many(value, limit=limit, offset=offset)
            return verbs.get_many_by_field(self._db, self._collection, field_name, value, limit=limit, offset=offset)
        return verbs.get_many_by_filter(self._db, self._collection, criteria, limit=limit, offset=offset)

    def many(self, *args: Field, limit: int | None = None, offset: int = 0, **kwargs: Any) -> list[Document]:
        criteria = _normalize_field_criteria(args, kwargs)
        if not criteria:
            return verbs.get_many_by_filter(self._db, self._collection, {}, limit=limit, offset=offset)
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            accessor = self._fields.get(field_name)
            if accessor is not None:
                return accessor.get.many(value, limit=limit, offset=offset)
            return verbs.get_many_by_field(self._db, self._collection, field_name, value, limit=limit, offset=offset)
        return verbs.get_many_by_filter(self._db, self._collection, criteria, limit=limit, offset=offset)

    def in_(self, *args: Field, limit: int | None = None, offset: int = 0, **kwargs: Any) -> list[Document]:
        criteria = _normalize_field_criteria(args, kwargs)
        if len(criteria) != 1:
            raise ValueError("get.in_() requires exactly one criterion")
        field_name, values = next(iter(criteria.items()))
        accessor = self._fields.get(field_name)
        if accessor is not None:
            return accessor.get.in_(values, limit=limit, offset=offset)
        return verbs.get_in_by_field(self._db, self._collection, field_name, values, limit=limit, offset=offset)

    def gte(self, field_name: str, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        accessor = self._fields.get(field_name)
        if accessor is not None:
            return accessor.get.gte(threshold, limit=limit, offset=offset)
        return verbs.get_range_by_field(
            self._db,
            self._collection,
            field_name,
            {Op.GTE: threshold},
            limit=limit,
            offset=offset,
        )

    def lte(self, field_name: str, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        accessor = self._fields.get(field_name)
        if accessor is not None:
            return accessor.get.lte(threshold, limit=limit, offset=offset)
        return verbs.get_range_by_field(
            self._db,
            self._collection,
            field_name,
            {Op.LTE: threshold},
            limit=limit,
            offset=offset,
        )

    def like(self, field_name: str, pattern: str, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        accessor = self._fields.get(field_name)
        if accessor is not None:
            return accessor.get.like(pattern, limit=limit, offset=offset)
        return verbs.get_like_by_field(self._db, self._collection, field_name, pattern, limit=limit, offset=offset)


class CollectionDelete:
    def __init__(self, db: SafeDatabase, collection: str) -> None:
        self._db = db
        self._collection = collection
        self.cascade: Callable[[list[str]], int] | None = None  # injected by _attach_cascade()

    def __call__(self, *args: Field, **kwargs: Any) -> int:
        criteria = _normalize_field_criteria(args, kwargs)
        if not criteria:
            verbs.truncate(self._db, self._collection)
            return 0
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            return verbs.delete_by_field(self._db, self._collection, field_name, value)
        return verbs.delete_by_filter(self._db, self._collection, criteria)

    def in_(self, *args: Field, **kwargs: Any) -> int:
        criteria = _normalize_field_criteria(args, kwargs)
        if len(criteria) != 1:
            raise ValueError("delete.in_() requires exactly one criterion")
        field_name, values = next(iter(criteria.items()))
        return verbs.delete_in_by_field(self._db, self._collection, field_name, values)

    def unreferenced(self, edge_collection: str) -> int:
        return verbs.delete_unreferenced(self._db, self._collection, edge_collection)
