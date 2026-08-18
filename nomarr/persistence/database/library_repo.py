"""LibraryRepository — CRUD and domain queries for the ``libraries`` table.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
filtered queries. Pipeline-axis state reads delegate to ``PipelineRepository``,
which reads/writes the ``pipeline_states`` rows (Q3 contract) rather than any
``libraries`` columns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, select

from nomarr.helpers.constants.pipeline_states import PIPELINE_AXIS_FIELDS, PIPELINE_DEFAULTS
from nomarr.helpers.dto.repo_dto import LibraryRow
from nomarr.persistence.database.pipeline_repo import PipelineRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    select_by_key,
    update_by_field,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session

_T = cast("Table", Library.__table__)


def _row_to_dto(row: Row) -> LibraryRow:
    """Convert a SQLAlchemy ``Row`` to a ``LibraryRow`` TypedDict."""
    m = row._mapping
    return LibraryRow(
        id=m["id"],
        name=m["name"],
        path=m["path"],
        library_type=m["library_type"],
        auto_tag=m["auto_tag"],
        auto_curate=m["auto_curate"],
        watch_mode=m["watch_mode"],
        file_write_mode=m["file_write_mode"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


class LibraryRepository:
    """Repository for the ``libraries`` table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── basic CRUD ──────────────────────────────────────────────

    def add_library(self, payload: dict[str, Any]) -> int:
        """Insert a new library row and return its ``id``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                row = insert_one(_T, payload, session=self._session)
            self._session.commit()
            return int(row._mapping["id"])

    def get_library(self, library_id: int) -> LibraryRow | None:
        """Fetch a single library by primary key."""
        with map_persistence_exceptions():
            row = select_by_key(_T, library_id, session=self._session)
            return _row_to_dto(row) if row else None

    def get_library_by_name(self, name: str) -> LibraryRow | None:
        """Fetch a single library by its unique ``name`` field."""
        with map_persistence_exceptions():
            row = select_by_key(_T, name, session=self._session, key_col="name")
            return _row_to_dto(row) if row else None

    def list_libraries(self, *, enabled_only: bool = False) -> list[LibraryRow]:
        """Return all libraries, optionally filtering to enabled types only."""
        with map_persistence_exceptions():
            stmt = select(_T)
            if enabled_only:
                stmt = stmt.where(_T.c.library_type != "disabled")
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def list_library_keys(self) -> list[int]:
        """Return all library primary-key ids."""
        with map_persistence_exceptions():
            stmt = select(_T.c.id)
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    def update_library(self, library_id: int, fields: dict[str, Any]) -> None:
        """Update arbitrary fields on a library row."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                update_by_field(_T, "id", library_id, fields, session=self._session)
            self._session.commit()

    def delete_library(self, library_id: int) -> None:
        """Delete a library row by primary key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_T, library_id, session=self._session)
            self._session.commit()

    # ── pipeline axis helpers (row-backed via PipelineRepository) ───

    def get_pipeline_state(self, library_id: int) -> dict[str, str] | None:
        """Return the four pipeline-axis states as a dict, or ``None``.

        Reads from ``pipeline_states`` rows via :class:`PipelineRepository`
        (one row per axis key from ``PIPELINE_AXIS_FIELDS``, each row's
        ``state_data`` shaped ``{"state": <pole_value>}``). Returns ``None``
        when the library has no pipeline-state rows at all; otherwise returns
        all four axis keys, falling back to ``PIPELINE_DEFAULTS`` for any axis
        that has no row.
        """
        pipeline_repo = PipelineRepository(self._session)
        with map_persistence_exceptions():
            result: dict[str, str] = {}
            any_row = False
            for axis in PIPELINE_AXIS_FIELDS:
                row = pipeline_repo.get_state(library_id, axis)
                if row is None:
                    result[axis] = PIPELINE_DEFAULTS[axis]
                else:
                    any_row = True
                    result[axis] = row["state_data"].get("state", PIPELINE_DEFAULTS[axis])
            if not any_row:
                return None
            return result

    def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[int]:
        """Return ids of libraries whose *axis_field* state equals *axis_value*.

        Delegates to :meth:`PipelineRepository.list_libraries_in_pipeline_state`
        (``axis_field`` is the ``state_key``; matches ``state_data["state"] ==
        axis_value``), so the lookup is backed by ``pipeline_states`` rows rather
        than any ``libraries`` column.
        """
        with map_persistence_exceptions():
            return PipelineRepository(self._session).list_libraries_in_pipeline_state(axis_field, axis_value)

    # ── cascade delete (ORM) ────────────────────────────────────

    def remove_library(self, library_id: int) -> None:
        """Delete a library and all cascaded child data via FK ON DELETE CASCADE.

        Uses the ORM ``session.delete`` so that the identity map stays
        consistent; FK CASCADE handles files, folders, scans, pipeline
        states, etc.
        """
        from sqlalchemy import select as sa_select

        with map_persistence_exceptions():
            stmt = sa_select(Library).where(Library.id == library_id)
            result = self._session.execute(stmt)
            library = result.scalar_one_or_none()
            if library is None:
                return
            with self._session.begin_nested():
                self._session.delete(library)
            self._session.commit()
