"""PipelineRepository — CRUD for the ``pipeline_states`` table.

Uses ``pipeline_states`` table with ``(library_id, state_key)`` unique
constraint.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, delete, distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.constants.file_states import STATE_NOT_HYDRATED
from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_DEFAULTS,
    SCAN_IN_PROGRESS,
    SCAN_STATE_FIELD,
    WRITE_IN_PROGRESS,
    WRITE_STATE_FIELD,
)
from nomarr.helpers.dto.repo_dto import PipelineStateRow, SongRow
from nomarr.helpers.exceptions import LibraryOperationConflict
from nomarr.persistence.database.repo_helpers import _song_row_to_dto
from nomarr.persistence.models.library import Library
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
_L: Table = Library.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
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

    def admit_scan(self, library_id: int) -> dict[str, str]:
        """Atomically admit a scan when tag writing is not active.

        The parent library row is locked as the serialization boundary, even
        when no pipeline-state rows exist yet. The scan axis is then evaluated
        and transitioned in the same short transaction, so concurrent scan and
        tag-write admission for one library cannot both pass their predicates.
        Raises :class:`LibraryOperationConflict` when tag writing is active.
        """
        return self._admit(library_id, operation="scan")

    def admit_tag_write(self, library_id: int) -> dict[str, str]:
        """Atomically admit tag writing when all library predicates hold.

        Admission serializes on the parent library row and rejects while a scan
        or another tag write is active, or while any song in the library remains
        in ``not_hydrated``. The predicate check and transition to
        ``tag_write_state=write_in_progress`` commit together. Rejection raises
        :class:`LibraryOperationConflict` with the current lifecycle states and
        hydration-debt count.
        """
        return self._admit(library_id, operation="tag_write")

    def assert_hydration_allowed(self, library_id: int) -> None:
        """Lock lifecycle state and reject hydration while writing is active.

        Locks the parent library and lifecycle rows before checking the write
        axis. The caller's hydration mutation can therefore share this lock
        boundary; an active tag write raises :class:`LibraryOperationConflict`.
        """
        self._assert_axis_available(library_id, operation="hydration", require_clear=WRITE_STATE_FIELD)

    def assert_physical_write_allowed(self, library_id: int) -> None:
        """Lock lifecycle state and reject physical writes while scanning.

        Locks the parent library and lifecycle rows before checking the scan
        axis. A physical tag write is rejected with
        :class:`LibraryOperationConflict` while scanning is active.
        """
        self._assert_axis_available(library_id, operation="physical_write", require_clear=SCAN_STATE_FIELD)

    def _assert_axis_available(self, library_id: int, *, operation: str, require_clear: str) -> None:
        with map_persistence_exceptions(), self._session.begin_nested():
            # Lock the parent row so the guard shares the admission boundary even
            # when no pipeline-state rows exist yet.  The surrounding repository
            # intent retains this lock through its mutation commit.
            self._session.execute(select(_L.c.id).where(_L.c.id == library_id).with_for_update()).scalar_one()
            rows = self._session.execute(
                select(_T.c.state_key, _T.c.state_data).where(_T.c.library_id == library_id).with_for_update()
            ).all()
            values = PIPELINE_DEFAULTS.copy()
            for row in rows:
                values[row._mapping["state_key"]] = (row._mapping["state_data"] or {}).get(
                    "state", values[row._mapping["state_key"]]
                )
            blocked_value = WRITE_IN_PROGRESS if require_clear == WRITE_STATE_FIELD else SCAN_IN_PROGRESS
            if values[require_clear] != blocked_value:
                return
            raise LibraryOperationConflict(
                operation,
                scan_state=values[SCAN_STATE_FIELD],
                tag_write_state=values[WRITE_STATE_FIELD],
            )

    def _admit(self, library_id: int, *, operation: str) -> dict[str, str]:
        """Evaluate and transition one lifecycle axis in a short transaction."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                # The parent library row is the common serialization boundary even
                # before either lifecycle axis has materialized a pipeline row.
                self._session.execute(select(_L.c.id).where(_L.c.id == library_id).with_for_update()).all()
                rows = self._session.execute(
                    select(_T.c.state_key, _T.c.state_data).where(_T.c.library_id == library_id).with_for_update()
                ).all()
                values = PIPELINE_DEFAULTS.copy()
                for row in rows:
                    values[row._mapping["state_key"]] = (row._mapping["state_data"] or {}).get(
                        "state", values[row._mapping["state_key"]]
                    )
                not_hydrated_count = 0
                if operation == "scan":
                    allowed = values[WRITE_STATE_FIELD] != WRITE_IN_PROGRESS
                    target_axis, target_value = SCAN_STATE_FIELD, SCAN_IN_PROGRESS
                else:
                    not_hydrated_count = int(
                        self._session.execute(
                            select(func.count(distinct(_S.c.id)))
                            .select_from(
                                _S.join(_SSA, _S.c.id == _SSA.c.song_id).join(_SS, _SS.c.id == _SSA.c.state_id)
                            )
                            .where(_S.c.library_id == library_id, _SS.c.name == STATE_NOT_HYDRATED)
                        ).scalar()
                        or 0
                    )
                    allowed = (
                        values[SCAN_STATE_FIELD] != SCAN_IN_PROGRESS
                        and values[WRITE_STATE_FIELD] != WRITE_IN_PROGRESS
                        and not_hydrated_count == 0
                    )
                    target_axis, target_value = WRITE_STATE_FIELD, WRITE_IN_PROGRESS
                if not allowed:
                    raise LibraryOperationConflict(
                        operation,
                        scan_state=values[SCAN_STATE_FIELD],
                        tag_write_state=values[WRITE_STATE_FIELD],
                        not_hydrated_count=not_hydrated_count,
                    )
                payload = {
                    "library_id": library_id,
                    "state_key": target_axis,
                    "state_data": {"state": target_value},
                    "updated_at": int(time.time() * 1000),
                }
                insert_stmt = pg_insert(_T).values(**payload)
                self._session.execute(
                    insert_stmt.on_conflict_do_update(
                        constraint="uq_pipeline_states_lib_key",
                        set_={
                            "state_data": insert_stmt.excluded["state_data"],
                            "updated_at": insert_stmt.excluded["updated_at"],
                        },
                    )
                )
            self._session.commit()
            return values | {target_axis: target_value}

    def count_songs_in_state(self, library_id: int, state: str) -> int:
        """Count songs in one state for a library inside persistence."""
        stmt = (
            select(func.count(distinct(_S.c.id)))
            .select_from(
                _S.join(_L, _S.c.library_id == _L.c.id)
                .join(_SSA, _S.c.id == _SSA.c.song_id)
                .join(_SS, _SS.c.id == _SSA.c.state_id)
            )
            .where(_S.c.library_id == library_id, _SS.c.name == state)
        )
        with map_persistence_exceptions():
            return int(self._session.execute(stmt).scalar() or 0)

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
        Missing rows use the same default state as higher-level reads. Matching
        compares ``state_data["state"] == state_value`` on the Python side to
        avoid the PostgreSQL ``@>`` operator, which is not available on SQLite.
        Works identically on both backends.
        """
        with map_persistence_exceptions():
            stmt = select(_L.c.id, _T.c.state_data).select_from(
                _L.outerjoin(
                    _T,
                    and_(_T.c.library_id == _L.c.id, _T.c.state_key == state_key),
                )
            )
            result = self._session.execute(stmt)
            return [
                row._mapping["id"]
                for row in result.all()
                if (row._mapping["state_data"] or {}).get("state", PIPELINE_DEFAULTS[state_key]) == state_value
            ]

    def count_pipeline_states(self) -> int:
        """Return total row count of ``pipeline_states``."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_T)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def list_song_docs_in_state(
        self,
        state: str,
        *,
        limit: int | None = None,
        library_id: int | None = None,
        order_by_activity: bool = False,
    ) -> list[SongRow]:
        """Return song rows that have been assigned the given song state.

        Traverses ``song_state_assignments`` → ``song_states`` to resolve
        the state name, then joins ``songs`` for the full row. When requested,
        rows are ordered by the latest scan/tag activity before applying the
        limit so a bounded result still contains the newest songs. The
        ``greatest`` expression is PostgreSQL-specific, matching this repo's
        supported database.
        """
        with map_persistence_exceptions():
            stmt = (
                select(_S)
                .join(_SSA, _S.c.id == _SSA.c.song_id)
                .join(_SS, _SS.c.id == _SSA.c.state_id)
                .where(_SS.c.name == state)
            )
            if library_id is not None:
                stmt = stmt.where(_S.c.library_id == library_id)
            if order_by_activity:
                activity_at = func.greatest(
                    func.coalesce(_S.c.scanned_at, 0),
                    func.coalesce(_S.c.last_tagged_at, 0),
                )
                stmt = stmt.order_by(activity_at.desc(), _S.c.id.desc())
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
