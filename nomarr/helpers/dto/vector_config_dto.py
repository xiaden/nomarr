"""DTOs for per-library vector configuration."""

from __future__ import annotations

from typing import TypedDict


class VectorConfigResult(TypedDict):
    """Resolved vector configuration with inheritance info."""

    vector_group_size: int
    vector_search_thoroughness: int
    is_group_size_inherited: bool
    is_thoroughness_inherited: bool
