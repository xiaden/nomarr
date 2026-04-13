"""Filter operator types for the persistence constructor.

These types are used across all layers (components, workflows, services)
to build filter expressions for collection queries.  They live in helpers
so that every layer can import them without violating dependency rules.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict


class Op(StrEnum):
    """Comparison operators for the .in() FilterDict overload."""

    LT = "lt"
    GT = "gt"
    LTE = "lte"
    GTE = "gte"
    EQ = "eq"
    NEQ = "neq"
    NOT = "not"


# Type aliases for filter type system
FilterValue = int | float | bool | str
FilterDict = dict[Op, FilterValue]


class AggResult(TypedDict):
    """Return type for aggregate verb."""

    value: str
    count: int
