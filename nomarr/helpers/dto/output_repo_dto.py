"""TypedDict DTOs for the OutputRepo return types.

These mirror the SQLAlchemy ``MlOutputStream`` and ``MlModelOutput``
model columns from Part A and provide type-safe return types for output
repository methods.  Import only from ``typing``.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class OutputStreamRecord(TypedDict):
    """Single canonical row from the ``ml_output_streams`` table.

    Represents the canonical ``{output_id, values}`` stream record with stable
    row/song/index/timestamp fields. ``ml_model_outputs`` remains a metadata
    table used only to enrich reads.
    """

    id: int
    song_id: int
    output_id: str
    output_index: int | None
    values: list[float]
    created_at: int


class ModelOutputRecord(TypedDict):
    """Single row from the ``ml_model_outputs`` table.

    Model-scoped metadata: no ``song_id``.  ``output_id`` is the stable natural
    identity (sha256 ``_output_key`` from the model registry).
    """

    id: int
    output_id: str
    model_id: str
    output_data: dict[str, Any]
    created_at: int
    # Extended fields from the ml_model_outputs table
    output_index: NotRequired[int | None]
    label: NotRequired[str | None]
    fully_labeled: NotRequired[bool]


__all__ = ["ModelOutputRecord", "OutputStreamRecord"]
