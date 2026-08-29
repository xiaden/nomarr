"""OutputRepo — CRUD for ``ml_model_outputs`` and ``ml_output_streams`` tables.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
filtered queries and deletes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, select

from nomarr.helpers.dto.output_repo_dto import ModelOutputRecord, OutputStreamRecord
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.models.ml_model_output import MlModelOutput
from nomarr.persistence.models.ml_output_stream import MlOutputStream
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import (
    insert_one,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session

_T_OUTPUT = cast("Table", MlModelOutput.__table__)
_T_STREAM = cast("Table", MlOutputStream.__table__)


def _row_to_output_record(row: Row[Any]) -> ModelOutputRecord:
    """Convert a SQLAlchemy ``Row`` to a ``ModelOutputRecord`` TypedDict."""
    m = row._mapping
    return ModelOutputRecord(
        id=m["id"],
        output_id=m["output_id"],
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
        song_id=m["song_id"],
        output_id=m["output_id"],
        output_index=m["output_index"],
        values=list(m["values"]),
        created_at=m["created_at"],
    )


class OutputRepo:
    """Repository for the ``ml_model_outputs`` and ``ml_output_streams`` tables."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── model outputs ───────────────────────────────────────────

    def store_model_output(
        self,
        model_id: str,
        output_id: str,
        output_data: dict[str, Any],
        output_index: int | None = None,
        label: str | None = None,
        fully_labeled: bool = False,
    ) -> ModelOutputRecord:
        """Insert or update one model output row keyed by stable ``output_id`` and return it.

        Optional *output_index*, *label*, and *fully_labeled* parameters
        mirror all extended model output columns.  Select-then-upsert runs
        inside a SAVEPOINT and a single commit; the registry is a
        single-writer flow (startup registration + user label edits).
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                now = now_ms().value
                values = {
                    "model_id": model_id,
                    "output_id": output_id,
                    "output_data": output_data,
                    "created_at": now,
                    "output_index": output_index,
                    "label": label,
                    "fully_labeled": int(fully_labeled),
                }
                existing = self._session.execute(select(_T_OUTPUT).where(_T_OUTPUT.c.output_id == output_id)).first()
                if existing is None:
                    row = insert_one(_T_OUTPUT, values, session=self._session)
                else:
                    self._session.execute(_T_OUTPUT.update().where(_T_OUTPUT.c.output_id == output_id).values(**values))
                    row = self._session.execute(select(_T_OUTPUT).where(_T_OUTPUT.c.output_id == output_id)).first()
                    assert row is not None
            self._session.commit()
            return _row_to_output_record(row)

    def get_output(self, output_id: str) -> ModelOutputRecord | None:
        """Fetch a single model output by stable output identity."""
        with map_persistence_exceptions():
            row = self._session.execute(select(_T_OUTPUT).where(_T_OUTPUT.c.output_id == output_id)).first()
            return _row_to_output_record(row) if row else None

    def list_model_outputs(self, model_id: str) -> list[ModelOutputRecord]:
        """Return all model outputs for a given model, ordered by output_index."""
        with map_persistence_exceptions():
            stmt = (
                select(_T_OUTPUT)
                .where(_T_OUTPUT.c.model_id == model_id)
                .order_by(_T_OUTPUT.c.output_index.asc().nulls_last())
            )
            result = self._session.execute(stmt)
            return [_row_to_output_record(r) for r in result.all()]

    def delete_outputs_for_model(self, model_id: str) -> list[str]:
        """Delete all model outputs for a given model and return their stable output_ids."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                rows = self._session.execute(
                    select(_T_OUTPUT.c.output_id).where(_T_OUTPUT.c.model_id == model_id)
                ).all()
                output_ids = [row[0] for row in rows]
                if output_ids:
                    self._session.execute(delete(_T_OUTPUT).where(_T_OUTPUT.c.model_id == model_id))
            self._session.commit()
            return output_ids

    def delete_output(self, output_id: str) -> None:
        """Delete a single model output by stable output identity."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T_OUTPUT).where(_T_OUTPUT.c.output_id == output_id))
            self._session.commit()

    # ── output streams ──────────────────────────────────────────

    def store_output_stream(
        self,
        song_id: int,
        *,
        output_id: str,
        values: list[float],
        output_index: int | None = None,
    ) -> OutputStreamRecord:
        """Insert one canonical output stream row and return it."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                now = now_ms().value
                row = insert_one(
                    _T_STREAM,
                    {
                        "song_id": song_id,
                        "output_id": output_id,
                        "output_index": output_index,
                        "values": values,
                        "created_at": now,
                    },
                    session=self._session,
                )
            self._session.commit()
            return _row_to_stream_record(row)

    def list_output_streams_for_song(self, song_id: int) -> list[OutputStreamRecord]:
        """Return all canonical output streams for a given song."""
        with map_persistence_exceptions():
            stmt = select(_T_STREAM).where(_T_STREAM.c.song_id == song_id)
            result = self._session.execute(stmt)
            return [_row_to_stream_record(r) for r in result.all()]

    def delete_output_streams_for_song(self, song_id: int) -> int:
        """Delete all canonical output streams for a given song.  Returns count deleted."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T_STREAM).where(_T_STREAM.c.song_id == song_id)
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult.rowcount is int at runtime
