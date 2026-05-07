"""Typed base classes for persistence collection declarations."""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Literal,
    Protocol,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from nomarr.helpers.filter_types import AggResult, Op
from nomarr.persistence.arango_client import SafeDatabase

T = TypeVar("T")
type Document = dict[str, Any]
type FieldValue = "Field[Any]"

_ALWAYS_UNIQUE = frozenset({"_key", "_id"})
_CLASS_VAR_NAMES = frozenset(
    {"_name", "_db", "EDGES", "VECTOR_TIER", "NAME_PATTERN", "FROM_COLLECTION", "TO_COLLECTION"}
)
_SNAKE_CASE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_CASE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")
_VERBS_MODULE: Any | None = None


def _verbs() -> Any:
    """Lazily import the verbs module to avoid constructor package cycles."""
    global _VERBS_MODULE
    if _VERBS_MODULE is None:
        _VERBS_MODULE = importlib.import_module("nomarr.persistence.constructor.verbs")
    return _VERBS_MODULE


def _execute_aql(*args: Any, **kwargs: Any) -> Any:
    return _verbs()._execute_aql(*args, **kwargs)


def aggregate_field(*args: Any, **kwargs: Any) -> list[AggResult]:
    return cast("list[AggResult]", _verbs().aggregate_field(*args, **kwargs))


def collect_field(*args: Any, **kwargs: Any) -> list[Any]:
    return cast("list[Any]", _verbs().collect_field(*args, **kwargs))


def count_all(*args: Any, **kwargs: Any) -> int:
    return cast("int", _verbs().count_all(*args, **kwargs))


def count_by_field(*args: Any, **kwargs: Any) -> int:
    return cast("int", _verbs().count_by_field(*args, **kwargs))


def count_by_filter(*args: Any, **kwargs: Any) -> int:
    return cast("int", _verbs().count_by_filter(*args, **kwargs))


def delete_by_field(*args: Any, **kwargs: Any) -> int:
    return cast("int", _verbs().delete_by_field(*args, **kwargs))


def delete_by_filter(*args: Any, **kwargs: Any) -> int:
    return cast("int", _verbs().delete_by_filter(*args, **kwargs))


def delete_in_by_field(*args: Any, **kwargs: Any) -> int:
    return cast("int", _verbs().delete_in_by_field(*args, **kwargs))


def delete_unreferenced(*args: Any, **kwargs: Any) -> int:
    return cast("int", _verbs().delete_unreferenced(*args, **kwargs))


def get_in_by_field(*args: Any, **kwargs: Any) -> list[Document]:
    return cast("list[Document]", _verbs().get_in_by_field(*args, **kwargs))


def get_like_by_field(*args: Any, **kwargs: Any) -> list[Document]:
    return cast("list[Document]", _verbs().get_like_by_field(*args, **kwargs))


def get_many_by_field(*args: Any, **kwargs: Any) -> list[Document]:
    return cast("list[Document]", _verbs().get_many_by_field(*args, **kwargs))


def get_many_by_filter(*args: Any, **kwargs: Any) -> list[Document]:
    return cast("list[Document]", _verbs().get_many_by_filter(*args, **kwargs))


def get_one_by_field(*args: Any, **kwargs: Any) -> Document | None:
    return cast("Document | None", _verbs().get_one_by_field(*args, **kwargs))


def get_range_by_field(*args: Any, **kwargs: Any) -> list[Document]:
    return cast("list[Document]", _verbs().get_range_by_field(*args, **kwargs))


def traversal_by_id(*args: Any, **kwargs: Any) -> list[Document]:
    return cast("list[Document]", _verbs().traversal_by_id(*args, **kwargs))


def insert(*args: Any, **kwargs: Any) -> list[str]:
    return cast("list[str]", _verbs().insert(*args, **kwargs))


def transition_verb(*args: Any, **kwargs: Any) -> None:
    _verbs().transition(*args, **kwargs)


def truncate(*args: Any, **kwargs: Any) -> None:
    _verbs().truncate(*args, **kwargs)


def update_by_field(*args: Any, **kwargs: Any) -> None:
    _verbs().update_by_field(*args, **kwargs)


def update_by_filter(*args: Any, **kwargs: Any) -> None:
    _verbs().update_by_filter(*args, **kwargs)


def update_many_by_key(*args: Any, **kwargs: Any) -> None:
    _verbs().update_many_by_key(*args, **kwargs)


def upsert_by_field(*args: Any, **kwargs: Any) -> list[str]:
    return cast("list[str]", _verbs().upsert_by_field(*args, **kwargs))


def _resolve_owner(obj: object, owner: type[Any] | None) -> type[Any]:
    """Return the descriptor owner class for class or instance attribute access."""
    return cast("type[Any]", owner if owner is not None else type(obj))


@dataclass(frozen=True)
class FieldMarker:
    """Annotation marker for Field and UniqueField."""

    unique: bool


if TYPE_CHECKING:

    class _FieldGetProtocol(Protocol):
        def __call__(self, value: Any) -> Document | None: ...

        def many(self, value: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]: ...

        def in_(self, values: list[Any], *, limit: int | None = None, offset: int = 0) -> list[Document]: ...

        def gte(self, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]: ...

        def lte(self, threshold: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]: ...

        def like(self, pattern: str, *, limit: int | None = None, offset: int = 0) -> list[Document]: ...

    class _FieldDeleteProtocol(Protocol):
        def __call__(self, value: Any) -> int: ...

        def in_(self, values: list[Any]) -> int: ...

    class _FieldAnnotation[T]:
        """Static type for annotation-only field markers."""

        def __new__(cls) -> _FieldAnnotation[T]: ...

        @classmethod
        def __class_getitem__(cls, item: object) -> object: ...

    class Field[T]:
        """Static type for a declared collection field.

        In annotations, ``Field[T]`` marks a non-unique field on a collection
        class. Once the class is created, the annotation is replaced with a
        descriptor-backed accessor such as ``db.library_files.path``.

        The bound accessor exposes field-scoped verbs like ``get()``,
        ``delete()``, ``update()``, ``upsert()``, ``count()``, and ``collect()``.
        """

        name: str
        value: Any
        get: _FieldGetProtocol
        delete: _FieldDeleteProtocol

        def __init__(self, name: str, value: Any) -> None: ...

        @classmethod
        def __class_getitem__(cls, item: object) -> object: ...

        def insert(self, docs: list[Document]) -> list[str]: ...

        def update(self, value: Any, fields: Document) -> None: ...

        def upsert(self, value: Any, fields: Document) -> list[str]: ...

        def upsert_batch(self, docs: list[Document]) -> list[str]: ...

        def count(self, value: Any) -> int: ...

        def collect(self, *, limit: int | None = None, offset: int = 0) -> list[Any]: ...

    class UniqueField[T](Field[T], _FieldAnnotation[T]):
        """Static type for a field that uniquely identifies documents.

        A bare ``get(value)`` on the bound accessor returns at most one
        document, while the other field-scoped verbs behave the same as on
        ``Field[T]``.
        """
else:

    @dataclass(frozen=True)
    class Field[T]:
        """Declares a non-unique collection field and positional filter value.

        ``Field[T]`` serves two closely related roles:

        * in annotations on a ``DocumentCollection`` subclass, it marks a field
          that should be replaced with a descriptor-backed accessor at class
          creation time; and
        * in collection-level calls such as ``db.tags.get(Field("name",
          "genre"))``, it carries a positional field criterion.

        Bound field accessors expose field-scoped verbs like ``get()``,
        ``delete()``, ``update()``, ``upsert()``, ``count()``, and ``collect()``.
        """

        name: str
        value: Any

        _unique: ClassVar[bool] = False

        @classmethod
        def __class_getitem__(cls, item: object) -> object:
            return Annotated[item, FieldMarker(unique=cls._unique)]

    class _FieldAnnotation[T]:
        """Marker class that resolves subscriptions into ``Annotated`` types."""

        _unique: ClassVar[bool]

        def __new__(cls) -> _FieldAnnotation:
            msg = f"{cls.__name__} is only for type annotations and cannot be instantiated."
            raise TypeError(msg)

        def __class_getitem__(cls, item: object) -> object:
            return Annotated[item, FieldMarker(unique=cls._unique)]

    class UniqueField[T](_FieldAnnotation):
        """Declares a collection field whose values are expected to be unique.

        When accessed through a bound collection class, ``get(value)`` returns
        a single document or ``None`` instead of a list.
        """

        _unique: ClassVar[bool] = True


INBOUND: Literal["INBOUND"] = "INBOUND"
OUTBOUND: Literal["OUTBOUND"] = "OUTBOUND"
CASCADE: Literal["CASCADE"] = "CASCADE"
DETACH: Literal["DETACH"] = "DETACH"


def _snake_case(name: str) -> str:
    """Convert ``CamelCase`` class names to ``snake_case`` attribute names."""
    return _SNAKE_CASE_RE_2.sub(r"\1_\2", _SNAKE_CASE_RE_1.sub(r"\1_\2", name)).lower()


def _is_classvar(annotation: Any) -> bool:
    """Return whether an annotation is a ``ClassVar``."""
    return get_origin(annotation) is ClassVar


def _extract_field_marker(annotation: Any) -> tuple[Any, bool] | None:
    """Extract ``(python_type, unique)`` from ``Annotated[..., FieldMarker]``."""
    if _is_classvar(annotation) or get_origin(annotation) is not Annotated:
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
    """Normalize a single positional ``Field(name, value)`` or keyword criteria."""
    if len(args) > 1:
        msg = "Expected at most one positional Field(name, value) criterion"
        raise ValueError(msg)
    if args and kwargs:
        msg = "Do not mix positional Field(name, value) criteria with keyword criteria"
        raise ValueError(msg)
    if args:
        item = args[0]
        return {item.name: item.value}
    return dict(kwargs)


def _require_single_criterion(*args: FieldValue, **kwargs: Any) -> tuple[str, Any]:
    """Require exactly one normalized criterion and return ``(field, value)``."""
    criteria = _normalize_field_criteria(*args, **kwargs)
    if len(criteria) != 1:
        msg = f"Expected exactly one field criterion, got {len(criteria)}"
        raise ValueError(msg)
    return next(iter(criteria.items()))


def _collection_name_for_class(cls: type[Any]) -> str:
    """Return the concrete collection name declared on a collection class."""
    declared_name = getattr(cls, "_name", None)
    if isinstance(declared_name, str) and declared_name:
        return declared_name
    return _snake_case(cls.__name__)


class _BoundGet:
    """Bound field-scoped read helper.

    Instances are created lazily when a field descriptor is accessed on a bound
    collection class such as ``db.library_files.path``.
    """

    def __init__(self, cls: type[Any], field_name: str, unique: bool) -> None:
        self._cls = cls
        self._field_name = field_name
        self._unique = unique

    def __call__(self, value: Any) -> Document | None | list[Document]:
        """Fetch documents matching this field value.

        For ``UniqueField`` accessors this returns a single document or
        ``None``. For ``Field`` accessors it delegates to ``many()`` and returns
        a list.
        """
        if self._unique:
            return get_one_by_field(
                cast("SafeDatabase", self._cls._db),
                cast("str", self._cls._name),
                self._field_name,
                value,
            )
        return self.many(value)

    def many(self, value: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return get_many_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            value,
            limit=limit,
            offset=offset,
        )

    def in_(self, values: list[Any], *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return get_in_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            values,
            limit=limit,
            offset=offset,
        )

    def gte(self, value: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return get_range_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            {Op.GTE: value},
            limit=limit,
            offset=offset,
        )

    def lte(self, value: Any, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return get_range_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            {Op.LTE: value},
            limit=limit,
            offset=offset,
        )

    def like(self, pattern: str, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return get_like_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            pattern,
            limit=limit,
            offset=offset,
        )


class _BoundFieldDelete:
    """Bound field-scoped delete helper.

    Instances are created lazily when a field descriptor is accessed on a bound
    collection class.
    """

    def __init__(self, cls: type[Any], field_name: str) -> None:
        self._cls = cls
        self._field_name = field_name

    def __call__(self, value: Any) -> int:
        """Delete all documents whose field matches ``value``.

        Returns:
            The number of documents deleted.
        """
        return delete_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            value,
        )

    def in_(self, values: list[Any]) -> int:
        return delete_in_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            values,
        )


class _BoundFieldAccessor:
    """Bound field accessor for a concrete collection class.

    The accessor is produced by the installed field descriptor and exposes both
    field-scoped verbs (``get`` and ``delete``) and convenience mutation helpers
    that implicitly target the accessor's field name.
    """

    def __init__(self, cls: type[Any], field_name: str, unique: bool) -> None:
        self._cls = cls
        self._field_name = field_name
        self._unique = unique
        self.get = _BoundGet(cls, field_name, unique)
        self.delete = _BoundFieldDelete(cls, field_name)

    def insert(self, docs: list[Document]) -> list[str]:
        return insert(cast("SafeDatabase", self._cls._db), cast("str", self._cls._name), docs)

    def update(self, value: Any, fields: Document) -> None:
        update_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            value,
            fields,
        )

    def upsert(self, value: Any, fields: Document) -> list[str]:
        doc = {self._field_name: value, **fields}
        return upsert_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            [doc],
        )

    def upsert_batch(self, docs: list[Document]) -> list[str]:
        return upsert_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            docs,
        )

    def count(self, value: Any) -> int:
        return count_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            value,
        )

    def collect(self, *, limit: int | None = None, offset: int = 0) -> list[Any]:
        return collect_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            self._field_name,
            limit=limit,
            offset=offset,
        )


class _FieldDescriptor:
    """Descriptor installed on collection classes for annotated fields."""

    def __init__(self, field_name: str, unique: bool) -> None:
        self._field_name = field_name
        self._unique = unique
        self._cache_attr = f"_bound_field_{field_name}"

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self._field_name = name
        self._cache_attr = f"_bound_field_{name}"

    def __get__(self, obj: object, owner: type[Any] | None = None) -> _BoundFieldAccessor:
        bound_owner = _resolve_owner(obj, owner)
        cached = bound_owner.__dict__.get(self._cache_attr)
        if isinstance(cached, _BoundFieldAccessor):
            return cached
        bound = _BoundFieldAccessor(bound_owner, self._field_name, self._unique)
        setattr(bound_owner, self._cache_attr, bound)
        return bound

    def __set__(self, obj: object, value: object) -> None:
        msg = f"Field descriptor '{self._field_name}' is read-only"
        raise AttributeError(msg)


class _BoundEdgeTraversal:
    """Bound graph-traversal helper installed from ``EDGES`` metadata."""

    def __init__(self, cls: type[Any], edge_def: EdgeDef) -> None:
        self._cls = cls
        self._edge_def = edge_def

    def __call__(self, start_id: str, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        return traversal_by_id(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            start_id,
            _collection_name_for_class(self._edge_def.via),
            self._edge_def.direction,
            limit=limit,
            offset=offset,
        )


class _EdgeDescriptor:
    """Descriptor installed on collection classes for declared graph edges."""

    def __init__(self, edge_name: str, edge_def: EdgeDef) -> None:
        self._edge_name = edge_name
        self._edge_def = edge_def
        self._cache_attr = f"_bound_edge_{edge_name}"

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self._edge_name = name
        self._cache_attr = f"_bound_edge_{name}"

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _BoundEdgeTraversal:
        bound_owner = _resolve_owner(obj, owner)
        cached = bound_owner.__dict__.get(self._cache_attr)
        if isinstance(cached, _BoundEdgeTraversal):
            return cached
        bound = _BoundEdgeTraversal(bound_owner, self._edge_def)
        setattr(bound_owner, self._cache_attr, bound)
        return bound

    def __set__(self, obj: object, value: object) -> None:
        msg = f"Edge descriptor '{self._edge_name}' is read-only"
        raise AttributeError(msg)


class _BoundCollectionGet:
    """Bound collection-scoped read helper.

    Supports collection-wide reads as well as criteria expressed either through
    ``Field`` positional values or keyword arguments.
    """

    def __init__(self, cls: type[Any]) -> None:
        self._cls = cls

    def __call__(
        self,
        *args: FieldValue,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> Document | None | list[Document]:
        """Fetch documents matching the supplied criteria.

        With no criteria this returns the collection contents. With exactly one
        criterion it reuses the bound field accessor when available so unique
        fields can return a single document. Multiple criteria always return a
        list.
        """
        criteria = _normalize_field_criteria(*args, **kwargs)
        if not criteria:
            return get_many_by_filter(
                cast("SafeDatabase", self._cls._db),
                cast("str", self._cls._name),
                {},
                limit=limit,
                offset=offset,
            )
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            accessor = getattr(self._cls, field_name, None)
            if isinstance(accessor, _BoundFieldAccessor):
                if limit is None and offset == 0:
                    return accessor.get(value)
                return accessor.get.many(value, limit=limit, offset=offset)
            return get_many_by_field(
                cast("SafeDatabase", self._cls._db),
                cast("str", self._cls._name),
                field_name,
                value,
                limit=limit,
                offset=offset,
            )
        return get_many_by_filter(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
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
        if not criteria:
            return get_many_by_filter(
                cast("SafeDatabase", self._cls._db),
                cast("str", self._cls._name),
                {},
                limit=limit,
                offset=offset,
            )
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            accessor = getattr(self._cls, field_name, None)
            if isinstance(accessor, _BoundFieldAccessor):
                return accessor.get.many(value, limit=limit, offset=offset)
            return get_many_by_field(
                cast("SafeDatabase", self._cls._db),
                cast("str", self._cls._name),
                field_name,
                value,
                limit=limit,
                offset=offset,
            )
        return get_many_by_filter(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
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
        accessor = getattr(self._cls, field_name, None)
        if isinstance(accessor, _BoundFieldAccessor):
            return accessor.get.in_(cast("list[Any]", values), limit=limit, offset=offset)
        return get_in_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
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
        accessor = getattr(self._cls, field_name, None)
        if isinstance(accessor, _BoundFieldAccessor):
            return accessor.get.gte(threshold, limit=limit, offset=offset)
        return get_range_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
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
        accessor = getattr(self._cls, field_name, None)
        if isinstance(accessor, _BoundFieldAccessor):
            return accessor.get.lte(threshold, limit=limit, offset=offset)
        return get_range_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
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
        accessor = getattr(self._cls, field_name, None)
        if isinstance(accessor, _BoundFieldAccessor):
            return accessor.get.like(pattern, limit=limit, offset=offset)
        return get_like_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            field_name,
            pattern,
            limit=limit,
            offset=offset,
        )


class _BoundCollectionDelete:
    """Bound collection-scoped delete helper.

    Deletion may be filtered by field criteria, may target a field ``IN`` list
    through ``in_()``, and may expose a compiled ``cascade`` callable when the
    collection declares outbound cascade edges.
    """

    def __init__(self, cls: type[Any]) -> None:
        self._cls = cls

    @property
    def cascade(self) -> Callable[[list[str]], int] | None:
        return getattr(self._cls, "_cascade_delete_fn", None)

    def __call__(self, *args: FieldValue, **kwargs: Any) -> int:
        """Delete documents matching the supplied criteria.

        With no criteria this truncates the collection and returns ``0``. With
        one or more criteria it deletes matching documents and returns the
        delete count reported by the underlying AQL helper.
        """
        criteria = _normalize_field_criteria(*args, **kwargs)
        if not criteria:
            truncate(cast("SafeDatabase", self._cls._db), cast("str", self._cls._name))
            return 0
        if len(criteria) == 1:
            field_name, value = next(iter(criteria.items()))
            return delete_by_field(
                cast("SafeDatabase", self._cls._db),
                cast("str", self._cls._name),
                field_name,
                value,
            )
        return delete_by_filter(cast("SafeDatabase", self._cls._db), cast("str", self._cls._name), criteria)

    def in_(self, *args: FieldValue, **kwargs: Any) -> int:
        field_name, values = _require_single_criterion(*args, **kwargs)
        return delete_in_by_field(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            field_name,
            cast("list[Any]", values),
        )

    def unreferenced(self, edge_collection: str) -> int:
        return delete_unreferenced(
            cast("SafeDatabase", self._cls._db),
            cast("str", self._cls._name),
            edge_collection,
        )


class _BoundTransition:
    """Bound transition callable for state-graph collections."""

    def __init__(self, cls: type[StateGraphCollection]) -> None:
        self._cls = cls

    def __call__(self, file_ids: list[str], from_state: str, to_state: str) -> None:
        edge_defs = getattr(self._cls, "EDGES", [])
        if not edge_defs:
            msg = f"{self._cls.__name__} has no EDGES defined for transition()"
            raise ValueError(msg)
        edge_name = _snake_case(edge_defs[0].via.__name__)
        transition_verb(cast("SafeDatabase", self._cls._db), edge_name, file_ids, from_state, to_state)


class _InsertCallable(Protocol):
    def __call__(self, docs: list[Document]) -> list[str]: ...


class _CountCallable(Protocol):
    def __call__(self, *args: FieldValue, **kwargs: Any) -> int: ...


class _UpdateCallable(Protocol):
    def __call__(self, *args: FieldValue, fields: Document, **kwargs: Any) -> None: ...


class _UpsertCallable(Protocol):
    def __call__(self, *args: FieldValue, fields: Document, **kwargs: Any) -> list[str]: ...


class _UpsertBatchCallable(Protocol):
    def __call__(self, docs: list[Document], match_fields: str | list[str]) -> list[str]: ...


class _UpdateManyCallable(Protocol):
    def __call__(self, docs: list[Document]) -> None: ...


class _AggregateCallable(Protocol):
    def __call__(
        self,
        field_name: str,
        *,
        filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AggResult]: ...


class _TruncateCallable(Protocol):
    def __call__(self) -> None: ...


class BaseGet:
    """Descriptor that binds collection-scoped read helpers on access."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _BoundCollectionGet: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _BoundCollectionGet: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _BoundCollectionGet:
        """Return a collection-scoped read helper bound to the owner class."""
        bound_owner = _resolve_owner(obj, owner)
        return _BoundCollectionGet(bound_owner)


class BaseDelete:
    """Descriptor that binds collection-scoped delete helpers on access."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _BoundCollectionDelete: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _BoundCollectionDelete: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _BoundCollectionDelete:
        """Return a collection-scoped delete helper bound to the owner class."""
        bound_owner = _resolve_owner(obj, owner)
        return _BoundCollectionDelete(bound_owner)


class BaseInsert:
    """Descriptor that binds the collection ``insert`` verb on access."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _InsertCallable: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _InsertCallable: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _InsertCallable:
        """Return an ``insert(docs)`` callable bound to the owner class."""
        bound_owner = _resolve_owner(obj, owner)

        def insert_docs(docs: list[Document]) -> list[str]:
            return insert(cast("SafeDatabase", bound_owner._db), cast("str", bound_owner._name), docs)

        return insert_docs


class BaseCount:
    """Descriptor that binds the collection ``count`` verb on access."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _CountCallable: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _CountCallable: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _CountCallable:
        """Return a ``count`` callable bound to the owner class."""
        bound_owner = _resolve_owner(obj, owner)

        def count(*args: FieldValue, **kwargs: Any) -> int:
            criteria = _normalize_field_criteria(*args, **kwargs)
            if not criteria:
                return count_all(cast("SafeDatabase", bound_owner._db), cast("str", bound_owner._name))
            if len(criteria) == 1:
                field_name, value = next(iter(criteria.items()))
                return count_by_field(
                    cast("SafeDatabase", bound_owner._db),
                    cast("str", bound_owner._name),
                    field_name,
                    value,
                )
            return count_by_filter(cast("SafeDatabase", bound_owner._db), cast("str", bound_owner._name), criteria)

        return count


class BaseUpdate:
    """Descriptor that binds the collection ``update`` verb on access."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _UpdateCallable: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _UpdateCallable: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _UpdateCallable:
        """Return an ``update`` callable bound to the owner class."""
        bound_owner = _resolve_owner(obj, owner)

        def update(*args: FieldValue, fields: Document, **kwargs: Any) -> None:
            criteria = _normalize_field_criteria(*args, **kwargs)
            if not criteria:
                msg = "update() requires at least one field criterion"
                raise ValueError(msg)
            if len(criteria) == 1:
                field_name, value = next(iter(criteria.items()))
                update_by_field(
                    cast("SafeDatabase", bound_owner._db),
                    cast("str", bound_owner._name),
                    field_name,
                    value,
                    fields,
                )
                return
            update_by_filter(cast("SafeDatabase", bound_owner._db), cast("str", bound_owner._name), criteria, fields)

        return update


class BaseUpsert:
    """Descriptor that binds the collection ``upsert`` verb on access."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _UpsertCallable: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _UpsertCallable: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _UpsertCallable:
        """Return an ``upsert`` callable bound to the owner class."""
        bound_owner = _resolve_owner(obj, owner)

        def upsert(*args: FieldValue, fields: Document, **kwargs: Any) -> list[str]:
            criteria = _normalize_field_criteria(*args, **kwargs)
            if not criteria:
                msg = "upsert() requires at least one field criterion"
                raise ValueError(msg)
            doc = {**criteria, **fields}
            if len(criteria) == 1:
                field_name = next(iter(criteria))
                return upsert_by_field(
                    cast("SafeDatabase", bound_owner._db),
                    cast("str", bound_owner._name),
                    field_name,
                    [doc],
                )
            return upsert_by_field(
                cast("SafeDatabase", bound_owner._db),
                cast("str", bound_owner._name),
                list(criteria),
                [doc],
            )

        return upsert


class BaseUpsertBatch:
    """Collection-level descriptor for ``upsert_batch``."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _UpsertBatchCallable: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _UpsertBatchCallable: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _UpsertBatchCallable:
        bound_owner = _resolve_owner(obj, owner)

        def upsert_batch(docs: list[Document], match_fields: str | list[str]) -> list[str]:
            if not docs:
                return []
            return upsert_by_field(
                cast("SafeDatabase", bound_owner._db), cast("str", bound_owner._name), match_fields, docs
            )

        return upsert_batch


class BaseUpdateMany:
    """Collection-level descriptor for ``update_many``."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _UpdateManyCallable: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _UpdateManyCallable: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _UpdateManyCallable:
        bound_owner = _resolve_owner(obj, owner)
        return lambda docs: update_many_by_key(
            cast("SafeDatabase", bound_owner._db), cast("str", bound_owner._name), docs
        )


class BaseAggregate:
    """Collection-level descriptor for ``aggregate``."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _AggregateCallable: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _AggregateCallable: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _AggregateCallable:
        bound_owner = _resolve_owner(obj, owner)

        def aggregate(
            field_name: str,
            *,
            filter: dict[str, Any] | None = None,
            limit: int | None = None,
            offset: int = 0,
        ) -> list[AggResult]:
            return aggregate_field(
                cast("SafeDatabase", bound_owner._db),
                cast("str", bound_owner._name),
                field_name,
                filter=filter,
                limit=limit,
                offset=offset,
            )

        return aggregate


class BaseTruncate:
    """Descriptor that binds the collection ``truncate`` verb on access."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _TruncateCallable: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _TruncateCallable: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _TruncateCallable:
        """Return a ``truncate()`` callable bound to the owner class."""
        bound_owner = _resolve_owner(obj, owner)

        def truncate_collection() -> None:
            truncate(cast("SafeDatabase", bound_owner._db), cast("str", bound_owner._name))

        return truncate_collection


class BaseTransition:
    """Collection-level descriptor for ``transition``."""

    @overload
    def __get__(self, obj: None, owner: type[Any] | None = None) -> _BoundTransition: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> _BoundTransition: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> _BoundTransition:
        bound_owner = _resolve_owner(obj, owner)
        return _BoundTransition(cast("type[StateGraphCollection]", bound_owner))


def _iter_recursive_subclasses(base_cls: type[Any]) -> set[type[Any]]:
    """Return all recursive subclasses of ``base_cls``."""
    discovered: set[type[Any]] = set()
    pending = list(base_cls.__subclasses__())
    while pending:
        subclass = pending.pop()
        if subclass in discovered:
            continue
        discovered.add(subclass)
        pending.extend(subclass.__subclasses__())
    return discovered


def _is_concrete_collection_class(cls: type[Any]) -> bool:
    """Return whether ``cls`` represents a physical Arango collection."""
    if cls is StateGraphCollection:
        return False
    if issubclass(cls, VectorCollection):
        declared_name = getattr(cls, "_name", None)
        return isinstance(declared_name, str) and bool(declared_name)
    return True


def _iter_concrete_subclasses(base_cls: type[Any]) -> Iterator[type[Any]]:
    """Yield recursive subclasses of ``base_cls`` that map to physical collections."""
    for cls in _iter_recursive_subclasses(base_cls):
        if _is_concrete_collection_class(cls):
            yield cls


def _has_cascade_edges(cls: type[Any]) -> bool:
    """Return whether ``cls`` declares outbound cascade edges."""
    return any(edge.on_delete == CASCADE and edge.direction == OUTBOUND for edge in getattr(cls, "EDGES", []))


def _cascade_edge_names_for_root(root_cls: type[Any]) -> list[str]:
    """Collect all cascade edge collection names reachable from ``root_cls``."""
    names: list[str] = []
    seen: set[type[Any]] = set()

    def visit(collection_cls: type[Any]) -> None:
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


def _compile_cascade_query(
    owner_cls: type[Any],
    collection_name: str,
    cascade_defs: list[EdgeDef],
    extra_target_names: list[str] | None = None,
) -> str:
    """Compile the static cascade-delete AQL template for one collection class."""
    cascade_edge_names = _cascade_edge_names_for_root(owner_cls)
    all_edge_names = sorted(_collection_name_for_class(cls) for cls in _iter_concrete_subclasses(EdgeCollection))
    target_collection_names = sorted(
        {
            _collection_name_for_class(cls)
            for cls in set(_iter_concrete_subclasses(DocumentCollection))
            | set(_iter_concrete_subclasses(VectorCollection))
        }
        - {collection_name}
    )
    if extra_target_names:
        target_collection_names = sorted((set(target_collection_names) | set(extra_target_names)) - {collection_name})

    if not cascade_edge_names:
        cascade_edge_names = [_collection_name_for_class(edge.via) for edge in cascade_defs]
    if not all_edge_names:
        all_edge_names = cascade_edge_names[:]

    cascade_edges_clause = ", ".join(cascade_edge_names)
    all_edges_clause = ", ".join(all_edge_names)

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


def _compile_and_attach_cascade(
    cls: type[DocumentCollection],
    extra_vector_names: list[str] | None = None,
) -> None:
    """Compile cascade AQL for ``cls`` and attach the callable to the class."""
    cascade_defs = [edge for edge in cls.EDGES if edge.on_delete == CASCADE and edge.direction == OUTBOUND]
    if not cascade_defs:
        return

    compiled_aql = _compile_cascade_query(
        owner_cls=cls,
        collection_name=cls._name,
        cascade_defs=cascade_defs,
        extra_target_names=extra_vector_names,
    )
    cls._cascade_aql = compiled_aql

    def cascade_delete(ids: list[str]) -> int:
        if not isinstance(ids, list) or not ids:
            msg = "cascade delete requires a non-empty list of document ids"
            raise ValueError(msg)
        list(_execute_aql(cls._db, compiled_aql, bind_vars={"starts": ids}))
        return len(ids)

    cls._cascade_delete_fn = cascade_delete


def bind_all_collections(safe_db: SafeDatabase) -> None:
    """Bind a shared database handle to all collection classes.

    This initializes the descriptor-based persistence API for the current
    process by assigning ``safe_db`` to the collection base classes' shared
    ``_db`` class variable. It also compiles and attaches cascade delete
    callables for every concrete document collection that declares outbound
    cascade edges.

    Args:
        safe_db: The process-wide safe ArangoDB handle used by collection
            descriptors and bound verbs.
    """
    DocumentCollection._db = safe_db
    EdgeCollection._db = safe_db
    VectorCollection._db = safe_db

    for cls in _iter_concrete_subclasses(DocumentCollection):
        document_cls = cast("type[DocumentCollection]", cls)
        _install_edge_descriptors(document_cls)
        if _has_cascade_edges(document_cls):
            _compile_and_attach_cascade(document_cls)


def reattach_vector_cascades(registered_names: list[str]) -> None:
    """Recompile cascades for collections that target dynamic vector collections."""
    for cls in _iter_concrete_subclasses(DocumentCollection):
        document_cls = cast("type[DocumentCollection]", cls)
        if not _has_cascade_edges(document_cls):
            continue
        edges = [edge for edge in document_cls.EDGES if edge.on_delete == CASCADE and edge.direction == OUTBOUND]
        if any(issubclass(edge.target, VectorCollection) for edge in edges):
            _compile_and_attach_cascade(document_cls, extra_vector_names=registered_names)


def _install_field_descriptors(cls: type[Any]) -> None:
    """Install ``_FieldDescriptor`` objects for annotated schema fields on ``cls``."""
    try:
        annotations = get_type_hints(cls, include_extras=True)
    except Exception:
        annotations = getattr(cls, "__annotations__", {})
    for field_name, annotation in annotations.items():
        if field_name in _CLASS_VAR_NAMES or _is_classvar(annotation):
            continue
        if isinstance(cls.__dict__.get(field_name), _FieldDescriptor):
            continue
        extracted = _extract_field_marker(annotation)
        if extracted is None:
            continue
        _, unique = extracted
        setattr(cls, field_name, _FieldDescriptor(field_name, unique or field_name in _ALWAYS_UNIQUE))


def _install_edge_descriptors(cls: type[Any]) -> None:
    """Install ``_EdgeDescriptor`` objects declared in ``cls.EDGES``."""
    for edge_def in getattr(cls, "EDGES", []):
        edge_name = _collection_name_for_class(edge_def.via)
        if isinstance(cls.__dict__.get(edge_name), _EdgeDescriptor):
            continue
        setattr(cls, edge_name, _EdgeDescriptor(edge_name, edge_def))


class _CollectionMeta(type):
    """Metaclass that preserves runtime lookup semantics for dynamic class attrs.

    Collection classes gain field and edge descriptors dynamically at import time or
    during database registration. Exposing a metaclass ``__getattr__`` gives static
    type checkers a fallback for those late-bound class attributes without changing
    normal runtime attribute resolution.
    """

    def __getattr__(cls, name: str) -> Any:
        raise AttributeError(name)


def _finalize_collection_subclass(cls: type[Any], *, derive_name: bool = True) -> None:
    """Install collection descriptors and derive the physical name when needed."""
    if derive_name and "_name" not in cls.__dict__:
        cls._name = _snake_case(cls.__name__)
    _install_field_descriptors(cls)
    _install_edge_descriptors(cls)


class _DescriptorCollection(metaclass=_CollectionMeta):
    """Shared descriptor-backed collection base.

    This internal base centralizes the class-bound verb descriptors and shared
    database/name state used by all concrete collection families.
    """

    _db: ClassVar[SafeDatabase] = cast("SafeDatabase", None)
    _name: ClassVar[str]

    get = BaseGet()
    delete = BaseDelete()
    insert = BaseInsert()
    count = BaseCount()
    update = BaseUpdate()
    upsert = BaseUpsert()
    upsert_batch = BaseUpsertBatch()
    update_many = BaseUpdateMany()
    aggregate = BaseAggregate()
    truncate = BaseTruncate()


class DocumentCollection(_DescriptorCollection):
    """Base class for descriptor-backed document collections.

    Subclasses declare fields using ``Field[T]`` and ``UniqueField[T]`` class
    annotations. ``__init_subclass__`` converts those annotations into bound
    field descriptors, derives ``_name`` from the class name when needed, and
    exposes collection-level verb descriptors such as ``get``, ``insert``,
    ``update``, ``upsert``, ``delete``, ``count``, and ``truncate``.

    The actual ArangoDB connection is shared through the class variable
    ``_db`` and is assigned once at startup by ``bind_all_collections()``.
    """

    _key: UniqueField[str]
    _id: UniqueField[str]
    _rev: Field[str]

    EDGES: ClassVar[list[EdgeDef]] = []
    _cascade_aql: ClassVar[str | None] = None
    _cascade_delete_fn: ClassVar[Callable[[list[str]], int] | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _finalize_collection_subclass(cls)


class EdgeCollection(_DescriptorCollection):
    """Base for edge collections. Implicit: ``_key``, ``_id``, ``_rev``, ``_from``, ``_to``."""

    _key: UniqueField[str]
    _id: UniqueField[str]
    _rev: Field[str]
    _from: Field[str]
    _to: Field[str]

    FROM_COLLECTION: ClassVar[type[DocumentCollection]]
    TO_COLLECTION: ClassVar[type[DocumentCollection]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _finalize_collection_subclass(cls)


class VectorCollection(_DescriptorCollection):
    """Base for vector collections. Implicit: ``_key``, ``_id``, ``_rev``."""

    _key: UniqueField[str]
    _id: UniqueField[str]
    _rev: Field[str]

    VECTOR_TIER: ClassVar[Literal["hot", "cold"]]
    NAME_PATTERN: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "NAME_PATTERN" in cls.__dict__ and "_name" not in cls.__dict__:
            _finalize_collection_subclass(cls, derive_name=False)
            return
        _finalize_collection_subclass(cls)


class StateGraphCollection(DocumentCollection):
    """DocumentCollection with transition verb attached by descriptor."""

    transition = BaseTransition()


@dataclass(frozen=True)
class EdgeDef:
    """Typed edge declaration used by collection classes."""

    via: type[EdgeCollection]
    direction: Literal["INBOUND", "OUTBOUND"]
    target: type[DocumentCollection | VectorCollection]
    on_delete: Literal["CASCADE", "DETACH"]


_install_field_descriptors(DocumentCollection)
_install_field_descriptors(EdgeCollection)
_install_field_descriptors(VectorCollection)

FieldAccessor = _BoundFieldAccessor


__all__ = [
    "CASCADE",
    "DETACH",
    "INBOUND",
    "OUTBOUND",
    "DocumentCollection",
    "EdgeCollection",
    "EdgeDef",
    "Field",
    "FieldMarker",
    "StateGraphCollection",
    "UniqueField",
    "VectorCollection",
    "bind_all_collections",
    "reattach_vector_cascades",
]
