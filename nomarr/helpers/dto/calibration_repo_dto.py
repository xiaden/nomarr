"""Repository-internal DTOs and typed join results for CalibrationRepo return types.

These mirror the SQLAlchemy ``CalibrationState`` and ``CalibrationHistory``
model columns from Part A and provide type-safe return types for
calibration repository methods.  Import only from ``typing``.
"""

from __future__ import annotations

from typing import Any, TypedDict


class CalibrationStateRecord(TypedDict):
    """Single row from the ``calibration_states`` table."""

    id: int
    model_id: str
    state_data: dict[str, Any]
    updated_at: int


class CalibrationHistoryRecord(TypedDict):
    """Single row from the ``calibration_history`` table."""

    id: int
    model_id: str
    event: str
    data: dict[str, Any]
    created_at: int


class CalibrationStateJoined(dict[str, Any]):
    """Repository-internal typed join result for ``list_states_with_models``.

    Carries the calibration state fields (``model_id``, ``state_data``,
    ``updated_at``) plus the model metadata needed to build a
    ``RegisteredModel``.  ``model_id`` is the stable model identity (equal to
    ``ml_models.id``); ``backbone_id`` is model metadata, not a calibration
    identity.  Integer row ids and the JSONB envelope stay repository-internal.

    This is a ``dict[str, Any]`` subclass rather than a ``TypedDict`` so that
    it is assignable to the ``dict[str, Any]`` parameter of
    ``calibration_state_from_joined_record`` (which ``ml.py`` calls) while the
    typed constructor still enforces the closed field set.
    """

    def __init__(
        self,
        *,
        model_id: str,
        state_data: dict[str, Any],
        updated_at: int,
        id: str,
        path: str,
        model_type: str,
        backbone_id: str,
        backbone: str,
        head_type: str,
        model_stem: str,
        output_count: int,
        fully_configured: int,
        is_known: int,
        source: str,
        head_release_date: str,
        embedder_release_date: str,
    ) -> None:
        super().__init__()
        self["model_id"] = model_id
        self["state_data"] = state_data
        self["updated_at"] = updated_at
        self["id"] = id
        self["path"] = path
        self["model_type"] = model_type
        self["backbone_id"] = backbone_id
        self["backbone"] = backbone
        self["head_type"] = head_type
        self["model_stem"] = model_stem
        self["output_count"] = output_count
        self["fully_configured"] = fully_configured
        self["is_known"] = is_known
        self["source"] = source
        self["head_release_date"] = head_release_date
        self["embedder_release_date"] = embedder_release_date


__all__ = [
    "CalibrationHistoryRecord",
    "CalibrationStateJoined",
    "CalibrationStateRecord",
]
