"""CalibrationRepo — CRUD for ``calibration_states`` and ``calibration_history``.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
upserts and joins.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, select, text, update

from nomarr.helpers.dto.calibration_repo_dto import (
    CalibrationHistoryRecord,
    CalibrationStateRecord,
)
from nomarr.persistence.models.calibration_history import CalibrationHistory
from nomarr.persistence.models.calibration_state import CalibrationState
from nomarr.persistence.models.ml_model import MlModel
from nomarr.persistence.sql.primitives import insert_one

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.ext.asyncio import AsyncSession

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

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── calibration state ───────────────────────────────────────

    async def get_state(self, model_id: str) -> CalibrationStateRecord | None:
        """Fetch the calibration state for a given model."""
        stmt = select(_T_STATE).where(_T_STATE.c.model_id == model_id)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return _row_to_state_record(row) if row else None

    async def set_state(self, model_id: str, state_data: dict[str, Any]) -> CalibrationStateRecord:
        """Upsert calibration state for a model.

        ``calibration_states`` has no unique constraint on ``model_id``, so
        this uses a select-then-insert-or-update pattern.
        """
        now = int(time.time())
        existing = await self.get_state(model_id)
        if existing is not None:
            stmt = (
                update(_T_STATE)
                .where(_T_STATE.c.id == existing["id"])
                .values(state_data=state_data, updated_at=now)
                .returning(_T_STATE)
            )
            result = await self._session.execute(stmt)
            await self._session.commit()
            row = result.fetchone()
            assert row is not None
            return _row_to_state_record(row)

        row = await insert_one(
            _T_STATE,
            {
                "model_id": model_id,
                "state_data": state_data,
                "updated_at": now,
            },
            session=self._session,
        )
        await self._session.commit()
        return _row_to_state_record(row)

    async def list_states(self) -> list[CalibrationStateRecord]:
        """Return all calibration state rows."""
        stmt = select(_T_STATE)
        result = await self._session.execute(stmt)
        return [_row_to_state_record(r) for r in result.all()]

    async def list_states_with_models(self) -> list[dict[str, Any]]:
        """Return calibration states joined with model metadata.

        Each dict includes ``backbone_id`` and ``model_id`` from the
        ``ml_models`` table.
        """
        cs = _T_STATE
        mm = MlModel.__table__
        stmt = select(
            cs.c.id,
            cs.c.model_id,
            cs.c.state_data,
            cs.c.updated_at,
            mm.c.backbone_id,
        ).select_from(cs.join(mm, cs.c.model_id == mm.c.id))
        result = await self._session.execute(stmt)
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

    async def delete_state(self, calibration_id: int) -> None:
        """Delete a single calibration state by its primary key."""
        stmt = delete(_T_STATE).where(_T_STATE.c.id == calibration_id)
        await self._session.execute(stmt)
        await self._session.commit()

    async def truncate_states(self) -> None:
        """Delete all rows from ``calibration_states`` (full reset)."""
        await self._session.execute(text("TRUNCATE TABLE calibration_states"))
        await self._session.commit()

    # ── calibration history ─────────────────────────────────────

    async def record_history(self, model_id: str, event: str, data: dict[str, Any]) -> CalibrationHistoryRecord:
        """Insert a calibration history event and return it."""
        now = int(time.time())
        row = await insert_one(
            _T_HISTORY,
            {
                "model_id": model_id,
                "event": event,
                "data": data,
                "created_at": now,
            },
            session=self._session,
        )
        await self._session.commit()
        return _row_to_history_record(row)

    async def get_history(self, model_id: str) -> list[CalibrationHistoryRecord]:
        """Return calibration history for a model, newest first."""
        stmt = select(_T_HISTORY).where(_T_HISTORY.c.model_id == model_id).order_by(_T_HISTORY.c.created_at.desc())
        result = await self._session.execute(stmt)
        return [_row_to_history_record(r) for r in result.all()]

    async def truncate_history(self) -> None:
        """Delete all rows from ``calibration_history`` (full reset)."""
        await self._session.execute(text("TRUNCATE TABLE calibration_history"))
        await self._session.commit()

    async def delete_history_for_model(self, model_id: str) -> None:
        """Delete all calibration history entries for a model."""
        stmt = delete(_T_HISTORY).where(_T_HISTORY.c.model_id == model_id)
        await self._session.execute(stmt)
        await self._session.commit()

    async def delete_history_entries(self, entry_ids: list[int]) -> None:
        """Delete calibration history entries by primary key list."""
        stmt = delete(_T_HISTORY).where(_T_HISTORY.c.id.in_(entry_ids))
        await self._session.execute(stmt)
        await self._session.commit()
