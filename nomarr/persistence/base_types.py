from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

CASCADE: Literal["CASCADE"] = "CASCADE"
DETACH: Literal["DETACH"] = "DETACH"
INBOUND: Literal["INBOUND"] = "INBOUND"
OUTBOUND: Literal["OUTBOUND"] = "OUTBOUND"

_SNAKE_CASE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_CASE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")


def _snake_case(name: str) -> str:
    s1 = _SNAKE_CASE_RE_1.sub(r"\1_\2", name)
    return _SNAKE_CASE_RE_2.sub(r"\1_\2", s1).lower()


def collection_name_for_class(cls: type) -> str:
    """Return the ArangoDB collection name for a collection class.

    Checks cls._name (if it is a non-empty string) first, then falls
    back to CamelCase -> snake_case of the class name.

    Lives in base_types so both cascade.py and collections_base.py can
    import it without a circular dependency.
    """
    declared = getattr(cls, "_name", None)
    if isinstance(declared, str) and declared:
        return declared
    return _snake_case(cls.__name__)


@dataclass(frozen=True)
class Field:
    """Positional field criterion used in collection verb calls.

    Example:
        db.library_files.get.in_(Field("path", paths))
        db.has_edge.count(Field("_from", file_id), Field("_to", state_id))

    Field[T] may still appear as a type annotation on FieldAccessor attributes
    to document the value type (e.g. ``path: FieldAccessor  # str, unique``),
    but it has no runtime effect and is not used for __init__ registration.
    """

    name: str
    value: Any

    @classmethod
    def __class_getitem__(cls, item: object) -> object:
        return item  # annotation sugar — no-op at runtime


class UniqueField:
    """Kept for import compatibility only. No runtime effect.

    Do not use in new collection class bodies. Annotate field attributes
    as FieldAccessor instead.
    """

    @classmethod
    def __class_getitem__(cls, item: object) -> object:
        return item


@dataclass(frozen=True)
class EdgeDef:
    via: type  # EdgeCollection subclass
    direction: Literal["INBOUND", "OUTBOUND"]
    target: type  # DocumentCollection or VectorCollection subclass
    on_delete: Literal["CASCADE", "DETACH"]


def _normalize_field_criteria(args: tuple, kwargs: dict) -> dict[str, Any]:
    """Normalize positional Field(...) args or keyword args into a plain dict.

    Rules:
    - Any number of positional Field(name, value) objects are accepted and merged.
    - Keyword args are accepted as-is (``field_name=value``).
    - Mixing positional and keyword raises ValueError.
    - Duplicate field names raise ValueError.
    """
    if args and kwargs:
        raise ValueError("Do not mix positional Field(...) and keyword criteria")
    if args:
        result: dict[str, Any] = {}
        for f in args:
            if f.name in result:
                raise ValueError(f"Duplicate field criterion for {f.name!r}")
            result[f.name] = f.value
        return result
    return dict(kwargs)
