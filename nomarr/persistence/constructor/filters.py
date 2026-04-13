"""Filter builders for the schema-driven constructor."""

from __future__ import annotations

from typing import Any

from nomarr.persistence.schema import FilterDict, Op

AQL_OP_MAP = {
    Op.LT: "<",
    Op.GT: ">",
    Op.LTE: "<=",
    Op.GTE: ">=",
    Op.EQ: "==",
    Op.NEQ: "!=",
    Op.NOT: "!=",  # 'not' treated as != in filter context
}


def build_in_filter(field: str, values: list[Any], bind_prefix: str = "vals") -> tuple[str, dict[str, Any]]:
    """Build an AQL fragment + bind vars for the IN operator."""
    aql = f"FILTER doc[@field] IN @{bind_prefix}"
    return aql, {"field": field, bind_prefix: values}


def build_comparison_filter(field: str, filter_dict: FilterDict) -> tuple[str, dict[str, Any]]:
    """Build an AQL fragment + bind vars for range/comparison operators."""
    fragments: list[str] = []
    bind_vars: dict[str, Any] = {"field": field}

    for i, (operator_key, value) in enumerate(filter_dict.items()):
        bind_key = f"cmp_val_{i}"
        op = AQL_OP_MAP[operator_key]
        fragments.append(f"doc[@field] {op} @{bind_key}")
        bind_vars[bind_key] = value

    aql = " ".join(f"FILTER {fragment}" for fragment in fragments)
    return aql, bind_vars


def build_equality_filter(filter_dict: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build a single AQL FILTER clause for multi-field equality matching."""
    if not filter_dict:
        return "", {}

    fragments: list[str] = []
    bind_vars: dict[str, Any] = {}

    for index, (field_name, value) in enumerate(filter_dict.items()):
        field_bind_key = f"f{index}"
        value_bind_key = f"v{index}"
        fragments.append(f"doc[@{field_bind_key}] == @{value_bind_key}")
        bind_vars[field_bind_key] = field_name
        bind_vars[value_bind_key] = value

    return f"FILTER {' AND '.join(fragments)}", bind_vars


def build_like_filter(field: str, pattern: str) -> tuple[str, dict[str, Any]]:
    """Build an AQL fragment + bind vars for the LIKE operator."""
    return "FILTER LIKE(doc[@field], @like_pattern, true)", {"field": field, "like_pattern": pattern}
