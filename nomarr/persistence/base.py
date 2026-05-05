"""Typed base classes for persistence collection declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class FieldMarker:
    """Annotation marker for Field and UniqueField."""

    unique: bool


@dataclass(frozen=True)
class Field[T]:
    """Non-unique field annotation wrapper and runtime positional field filter."""

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
        raise TypeError(f"{cls.__name__} is only for type annotations and cannot be instantiated.")

    def __class_getitem__(cls, item: object) -> object:
        return Annotated[item, FieldMarker(unique=cls._unique)]


class UniqueField[T](_FieldAnnotation):
    """Unique field annotation wrapper."""

    _unique: ClassVar[bool] = True


INBOUND: Literal["INBOUND"] = "INBOUND"
OUTBOUND: Literal["OUTBOUND"] = "OUTBOUND"
CASCADE: Literal["CASCADE"] = "CASCADE"
DETACH: Literal["DETACH"] = "DETACH"


class DocumentCollection:
    """Base for document collections. Implicit: _key, _id, _rev."""

    _key: UniqueField[str]
    _id: UniqueField[str]
    _rev: Field[str]

    _name: ClassVar[str]
    EDGES: ClassVar[list[EdgeDef]] = []


class EdgeCollection:
    """Base for edge collections. Implicit: _key, _id, _rev, _from, _to."""

    _key: UniqueField[str]
    _id: UniqueField[str]
    _rev: Field[str]
    _from: Field[str]
    _to: Field[str]

    _name: ClassVar[str]
    FROM_COLLECTION: ClassVar[type[DocumentCollection]]
    TO_COLLECTION: ClassVar[type[DocumentCollection]]


class VectorCollection:
    """Base for vector collections. Implicit: _key, _id, _rev."""

    _key: UniqueField[str]
    _id: UniqueField[str]
    _rev: Field[str]

    _name: ClassVar[str]
    VECTOR_TIER: ClassVar[Literal["hot", "cold"]]
    NAME_PATTERN: ClassVar[str]


class StateGraphCollection(DocumentCollection):
    """DocumentCollection with transition verb attached by builder."""


@dataclass(frozen=True)
class EdgeDef:
    """Typed edge declaration used by collection classes."""

    via: type[EdgeCollection]
    direction: Literal["INBOUND", "OUTBOUND"]
    target: type[DocumentCollection | VectorCollection]
    on_delete: Literal["CASCADE", "DETACH"]


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
]
