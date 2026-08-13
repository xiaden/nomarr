"""PipelineRepository — CRUD for the ``pipeline_states`` table.

Uses ``pipeline_states`` table with ``(library_id, state_key)`` unique
constraint.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.dto.repo_dto import PipelineStateRow, SongRow
from nomarr.persistence.database.repo_helpers import _song_row_to_dto
from nomarr.persistence.models.pipeline_state import PipelineState
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_state import SongState
from nomarr.persistence.models.song_state_assignment import SongStateAssignment
from nomarr.persistence.sql.exceptions import map_persistence_exceptions

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session
    from sqlalchemy.schema import Table

_T: Table = PipelineState.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_SSA: Table = SongStateAssignment.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_SS: Table = SongState.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_S: Table = Song.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table


def _row_to_dto(row: Row) -> PipelineStateRow:
    """Convert a SQLAlchemy ``Row`` to a ``PipelineStateRow`` TypedDict."""
    m = row._mapping
    return PipelineStateRow(
        id=m["id"],
        library_id=m["library_id"],
        state_key=m["state_key"],
        state_data=m["state_data"],
        updated_at=m["updated_at"],
    )


class PipelineRepository:
    """Repository for the ``pipeline_states`` table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    def upsert_pipeline_state(self, library_id: int, state_key: str, state_data: dict[str, Any]) -> None:
        """Insert-or-update a pipeline state via ``ON CONFLICT``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                payload = {
                    "library_id": library_id,
                    "state_key": state_key,
                    "state_data": state_data,
                    "updated_at": int(time.time() * 1000),
                }
                insert_stmt = pg_insert(_T).values(**payload)
                stmt = insert_stmt.on_conflict_do_update(
                    constraint="uq_pipeline_states_lib_key",
                    set_={
                        "state_data": insert_stmt.excluded["state_data"],
                        "updated_at": insert_stmt.excluded["updated_at"],
                    },
                )
                self._session.execute(stmt)
            self._session.commit()

    def get_state(self, library_id: int, state_key: str) -> PipelineStateRow | None:
        """Fetch a pipeline state by ``(library_id, state_key)``."""
        with map_persistence_exceptions():
            stmt = select(_T).where(
                _T.c.library_id == library_id,
                _T.c.state_key == state_key,
            )
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_dto(row) if row else None

    def update_pipeline_state(self, library_id: int, state_key: str, state_data: dict[str, Any]) -> None:
        """Update ``state_data`` for a ``(library_id, state_key)`` pair."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = (
                    update(_T)
                    .where(
                        _T.c.library_id == library_id,
                        _T.c.state_key == state_key,
                    )
                    .values(
                        state_data=state_data,
                        updated_at=int(time.time() * 1000),
                    )
                )
                self._session.execute(stmt)
            self._session.commit()

    def delete_pipeline_state(self, library_id: int) -> int:
        """Delete all pipeline states for a library; return row count."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T).where(_T.c.library_id == library_id)
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    def list_libraries_in_pipeline_state(self, state_key: str, state_value: str) -> list[int]:
        """Return library ids whose pipeline state equals *state_value*.

        *state_key* is one of the four axis keys from ``PIPELINE_AXIS_FIELDS``
        (``scan_state``/``ml_state``/``calibration_state``/``tag_write_state``);
        each row stores its state as ``state_data`` shaped ``{"state": <pole_value>}``.
        Matching compares ``state_data["state"] == state_value`` on the Python
        side to avoid the PostgreSQL ``@>`` operator, which is not available on
        SQLite.  Works identically on both backends.
        """
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.state_key == state_key)
            result = self._session.execute(stmt)
            return [
                row._mapping["library_id"]
                for row in result.all()
                if row._mapping["state_data"].get("state") == state_value
            ]

    def count_pipeline_states(self) -> int:
        """Return total row count of ``pipeline_states``."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_T)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def list_song_docs_in_state(self, state: str, *, limit: int | None = None) -> list[SongRow]:
        """Return song rows that have been assigned the given song state.

        Traverses ``song_state_assignments`` → ``song_states`` to resolve
        the state name, then joins ``songs`` for the full row.
        """
        with map_persistence_exceptions():
            stmt = (
                select(_S)
                .join(_SSA, _S.c.id == _SSA.c.song_id)
                .join(_SS, _SS.c.id == _SSA.c.state_id)
                .where(_SS.c.name == state)
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_song_row_to_dto(r) for r in result.all()]

    def get_state_edges_for_songs(self, song_ids: list[int]) -> list[dict[str, Any]]:
        """Return pipeline-state dicts for libraries that own *song_ids*."""
        with map_persistence_exceptions():
            if not song_ids:
                return []
            lib_ids_stmt = select(distinct(_S.c.library_id)).where(_S.c.id.in_(song_ids))
            result = self._session.execute(lib_ids_stmt)
            library_ids = [row[0] for row in result.all()]
            if not library_ids:
                return []
            stmt = select(_T).where(_T.c.library_id.in_(library_ids))
            result = self._session.execute(stmt)
            return [dict(r._mapping) for r in result.all()]
