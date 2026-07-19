"""CalibrationRepo — CRUD for ``calibration_states`` and ``calibration_history``.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
upserts and joins.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, select, update
from sqlalchemy.orm import Session, scoped_session

from nomarr.helpers.dto.calibration_repo_dto import (
    CalibrationHistoryRecord,
    CalibrationStateRecord,
)
from nomarr.persistence.models.calibration_history import CalibrationHistory
from nomarr.persistence.models.calibration_state import CalibrationState
from nomarr.persistence.models.ml_model import MlModel
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import insert_one

if TYPE_CHECKING:
    from sqlalchemy.engine import Row

_T_STATE = cast("Table", CalibrationState.__table__)
_T_HISTORY = cast("Table", CalibrationHistory.__table__)


def _row_to_state_record(row: Row[Any]) -> CalibrationStateRecord:
    """Convert a SQLAlchemy ``Row`` to a ``CalibrationStateRecord`` TypedDict."""
    m = row._mapping
    return CalibrationStateRecord(
        id=m["id"],
        model_id=m["model_id"],
        state_data=m["state_data"],
        updated_at=m["updated_at"],
    )


def _row_to_history_record(row: Row[Any]) -> CalibrationHistoryRecord:
    """Convert a SQLAlchemy ``Row`` to a ``CalibrationHistoryRecord`` TypedDict."""
    m = row._mapping
    return CalibrationHistoryRecord(
        id=m["id"],
        model_id=m["model_id"],
        event=m["event"],
        data=m["data"],
        created_at=m["created_at"],
    )


class CalibrationRepo:
    """Repository for the ``calibration_states`` and ``calibration_history`` tables."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── calibration state ───────────────────────────────────────

    def get_state(self, model_id: str) -> CalibrationStateRecord | None:
        """Fetch the calibration state for a given model."""
        with map_persistence_exceptions():
            stmt = select(_T_STATE).where(_T_STATE.c.model_id == model_id)
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_state_record(row) if row else None

    def set_state(self, model_id: str, state_data: dict[str, Any]) -> CalibrationStateRecord:
        """Upsert calibration state for a model.

        ``calibration_states`` has no unique constraint on ``model_id``, so
        this uses a select-then-insert-or-update pattern.
        """
        with map_persistence_exceptions():
            now = int(time.time())
            existing = self.get_state(model_id)
            if existing is not None:
                with self._session.begin_nested():
                    stmt = (
                        update(_T_STATE)
                        .where(_T_STATE.c.id == existing["id"])
                        .values(state_data=state_data, updated_at=now)
                        .returning(_T_STATE)
                    )
                    result = self._session.execute(stmt)
                    row = result.fetchone()
                self._session.commit()
                assert row is not None
                return _row_to_state_record(row)

            with self._session.begin_nested():
                row = insert_one(
                    _T_STATE,
                    {
                        "model_id": model_id,
                        "state_data": state_data,
                        "updated_at": now,
                    },
                    session=self._session,
                )
            self._session.commit()
            return _row_to_state_record(row)

    def list_states(self) -> list[CalibrationStateRecord]:
        """Return all calibration state rows."""
        with map_persistence_exceptions():
            stmt = select(_T_STATE)
            result = self._session.execute(stmt)
            return [_row_to_state_record(r) for r in result.all()]

    def list_states_with_models(self) -> list[dict[str, Any]]:
        """Return calibration states joined with model metadata.

        Each dict includes ``backbone_id`` and ``model_id`` from the
        ``ml_models`` table.
        """
        with map_persistence_exceptions():
            cs = _T_STATE
            mm = MlModel.__table__
            stmt = select(
                cs.c.id,
                cs.c.model_id,
                cs.c.state_data,
                cs.c.updated_at,
                mm.c.backbone_id,
            ).select_from(cs.join(mm, cs.c.model_id == mm.c.id))
            result = self._session.execute(stmt)
            return [
                {
                    "id": r._mapping["id"],
                    "model_id": r._mapping["model_id"],
                    "state_data": r._mapping["state_data"],
                    "updated_at": r._mapping["updated_at"],
                    "backbone_id": r._mapping["backbone_id"],
                }
                for r in result.all()
            ]

    def delete_state(self, calibration_id: int) -> None:
        """Delete a single calibration state by its primary key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T_STATE).where(_T_STATE.c.id == calibration_id)
                self._session.execute(stmt)
            self._session.commit()

    def truncate_states(self) -> None:
        """Delete all rows from ``calibration_states`` (full reset)."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T_STATE))
            self._session.commit()

    # ── calibration history ─────────────────────────────────────

    def record_history(self, model_id: str, event: str, data: dict[str, Any]) -> CalibrationHistoryRecord:
        """Insert a calibration history event and return it."""
        with map_persistence_exceptions():
            now = int(time.time())
            with self._session.begin_nested():
                row = insert_one(
                    _T_HISTORY,
                    {
                        "model_id": model_id,
                        "event": event,
                        "data": data,
                        "created_at": now,
                    },
                    session=self._session,
                )
            self._session.commit()
            return _row_to_history_record(row)

    def get_history(self, model_id: str) -> list[CalibrationHistoryRecord]:
        """Return calibration history for a model, newest first."""
        with map_persistence_exceptions():
            stmt = select(_T_HISTORY).where(_T_HISTORY.c.model_id == model_id).order_by(_T_HISTORY.c.created_at.desc())
            result = self._session.execute(stmt)
            return [_row_to_history_record(r) for r in result.all()]

    def truncate_history(self) -> None:
        """Delete all rows from ``calibration_history`` (full reset)."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T_HISTORY))
            self._session.commit()

    def delete_history_for_model(self, model_id: str) -> None:
        """Delete all calibration history entries for a model."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T_HISTORY).where(_T_HISTORY.c.model_id == model_id)
                self._session.execute(stmt)
            self._session.commit()

    def delete_history_entries(self, entry_ids: list[int]) -> None:
        """Delete calibration history entries by primary key list."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T_HISTORY).where(_T_HISTORY.c.id.in_(entry_ids))
                self._session.execute(stmt)
            self._session.commit()
