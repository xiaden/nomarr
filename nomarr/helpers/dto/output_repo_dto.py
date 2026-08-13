"""TypedDict DTOs for the OutputRepo return types.

These mirror the SQLAlchemy ``MlOutputStream`` and ``MlModelOutput``
model columns from Part A and provide type-safe return types for output
repository methods.  Import only from ``typing``.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class OutputStreamRecord(TypedDict):
    """Single row from the ``ml_output_streams`` table."""

    id: int
    song_id: int
    model_id: str
    status: str
    created_at: int


class ModelOutputRecord(TypedDict):
    """Single row from the ``ml_model_outputs`` table."""

    id: int
    song_id: int
    model_id: str
    output_data: dict[str, Any]
    created_at: int
    # Extended fields from the ml_model_outputs table
    output_index: NotRequired[int | None]
    label: NotRequired[str | None]
    fully_labeled: NotRequired[bool]


__all__ = ["ModelOutputRecord", "OutputStreamRecord"]
