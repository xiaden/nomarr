"""DTOs for global vector configuration.

Vector configuration is now global-only (per-library overrides removed).
All backbones share the same vector_group_size and vector_search_thoroughness.
"""

from __future__ import annotations

from typing import TypedDict


class VectorConfigResult(TypedDict):
    """Global vector configuration (no per-library override mechanism).

    All values are global defaults applied uniformly across backbones.
    ``is_group_size_inherited`` and ``is_thoroughness_inherited`` are
    removed — since there are no per-library overrides, inheritance is
    always-true by definition.
    """

    vector_group_size: int
    vector_search_thoroughness: int
