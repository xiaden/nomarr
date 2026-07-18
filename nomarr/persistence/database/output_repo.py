"""OutputRepo — CRUD for ``ml_model_outputs`` and ``ml_output_streams`` tables.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
filtered queries and deletes.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, select

from nomarr.helpers.dto.output_repo_dto import ModelOutputRecord, OutputStreamRecord
from nomarr.persistence.models.ml_model_output import MlModelOutput
from nomarr.persistence.models.ml_output_stream import MlOutputStream
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    select_by_key,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.ext.asyncio import AsyncSession

_T_OUTPUT = cast("Table", MlModelOutput.__table__)
_T_STREAM = cast("Table", MlOutputStream.__table__)


def _row_to_output_record(row: Row[Any]) -> ModelOutputRecord:
    """Convert a SQLAlchemy ``Row`` to a ``ModelOutputRecord`` TypedDict."""
    m = row._mapping
    return ModelOutputRecord(
        id=m["id"],
        file_id=m["file_id"],
        model_id=m["model_id"],
        output_data=m["output_data"],
        created_at=m["created_at"],
        # Extended fields from the ml_model_outputs table
        output_index=m.get("output_index"),
        label=m.get("label"),
        fully_labeled=bool(m.get("fully_labeled", 0)),
    )


def _row_to_stream_record(row: Row[Any]) -> OutputStreamRecord:
    """Convert a SQLAlchemy ``Row`` to an ``OutputStreamRecord`` TypedDict."""
    m = row._mapping
    return OutputStreamRecord(
        id=m["id"],
        file_id=m["file_id"],
        model_id=m["model_id"],
        status=m["status"],
        created_at=m["created_at"],
    )


class OutputRepo:
    """Repository for the ``ml_model_outputs`` and ``ml_output_streams`` tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── model outputs ───────────────────────────────────────────

    async def store_model_output(
        self,
        file_id: int,
        model_id: str,
        output_data: dict[str, Any],
        output_index: int | None = None,
        label: str | None = None,
        fully_labeled: bool = False,
    ) -> ModelOutputRecord:
        """Insert a model output row and return it.

        Optional *output_index*, *label*, and *fully_labeled* parameters
        mirror all extended model output columns.
        """
        async with map_persistence_exceptions():
            async with self._session.begin_nested():
                now = int(time.time())
                row = await insert_one(
                    _T_OUTPUT,
                    {
                        "file_id": file_id,
                        "model_id": model_id,
                        "output_data": output_data,
                        "created_at": now,
                        "output_index": output_index,
                        "label": label,
                        "fully_labeled": int(fully_labeled),
                    },
                    session=self._session,
                )
            await self._session.commit()
            return _row_to_output_record(row)

    async def get_output(self, output_id: int) -> ModelOutputRecord | None:
        """Fetch a single model output by primary key."""
        async with map_persistence_exceptions():
            row = await select_by_key(_T_OUTPUT, output_id, session=self._session)
            return _row_to_output_record(row) if row else None

    async def get_outputs_for_file(self, file_id: int) -> list[ModelOutputRecord]:
        """Return all model outputs for a given file."""
        async with map_persistence_exceptions():
            stmt = select(_T_OUTPUT).where(_T_OUTPUT.c.file_id == file_id)
            result = await self._session.execute(stmt)
            return [_row_to_output_record(r) for r in result.all()]

    async def list_model_outputs(self, model_id: str) -> list[ModelOutputRecord]:
        """Return all model outputs for a given model."""
        async with map_persistence_exceptions():
            stmt = select(_T_OUTPUT).where(_T_OUTPUT.c.model_id == model_id)
            result = await self._session.execute(stmt)
            return [_row_to_output_record(r) for r in result.all()]

    async def delete_outputs_for_model(self, model_id: str) -> int:
        """Delete all model outputs for a given model.  Returns count deleted."""
        async with map_persistence_exceptions():
            async with self._session.begin_nested():
                stmt = delete(_T_OUTPUT).where(_T_OUTPUT.c.model_id == model_id)
                result = await self._session.execute(stmt)
            await self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult.rowcount is int at runtime

    async def delete_outputs_for_file(self, file_id: int) -> int:
        """Delete all model outputs for a given file.  Returns count deleted."""
        async with map_persistence_exceptions():
            async with self._session.begin_nested():
                stmt = delete(_T_OUTPUT).where(_T_OUTPUT.c.file_id == file_id)
                result = await self._session.execute(stmt)
            await self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult.rowcount is int at runtime

    async def delete_output(self, output_id: int) -> None:
        """Delete a single model output by primary key."""
        async with map_persistence_exceptions():
            async with self._session.begin_nested():
                await delete_by_key(_T_OUTPUT, output_id, session=self._session)
            await self._session.commit()

    # ── output streams ──────────────────────────────────────────

    async def store_output_stream(self, file_id: int, model_id: str, status: str) -> OutputStreamRecord:
        """Insert an output stream row and return it."""
        async with map_persistence_exceptions():
            async with self._session.begin_nested():
                now = int(time.time())
                row = await insert_one(
                    _T_STREAM,
                    {
                        "file_id": file_id,
                        "model_id": model_id,
                        "status": status,
                        "created_at": now,
                    },
                    session=self._session,
                )
            await self._session.commit()
            return _row_to_stream_record(row)
