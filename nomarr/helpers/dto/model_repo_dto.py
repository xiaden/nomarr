"""TypedDict DTOs for the ModelRepo return types.

These mirror the SQLAlchemy ``MlModel`` model columns from Part A and
provide type-safe return types for model repository methods.  Import
only from ``typing``.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class ModelRecord(TypedDict):
    """Single row from the ``ml_models`` table."""

    id: str
    model_type: str
    backbone_id: str
    enabled: int
    created_at: int
    updated_at: int
    # Extended fields from the ml_models table
    path: NotRequired[str]
    backbone: NotRequired[str]
    head_type: NotRequired[str]
    model_stem: NotRequired[str]
    output_count: NotRequired[int]
    fully_configured: NotRequired[int]
    is_known: NotRequired[int]
    source: NotRequired[str]
    head_release_date: NotRequired[str]
    embedder_release_date: NotRequired[str]
    registered_at: NotRequired[int | None]


__all__ = ["ModelRecord"]
