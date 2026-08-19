"""SongStateRepository — manages song ↔ state assignments.

Uses the ``song_state_assignments`` junction table (M:N between songs
and states) and the ``song_states`` lookup table.

Method signatures follow the Plan E contracts (downstream intent-facade
expectations), NOT the original plan-step signatures.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sqlalchemy import Table, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.constants.file_states import (
    ALL_STATE_VERTICES,
    STATE_HYDRATED,
    STATE_NOT_HYDRATED,
    STATE_PROCESSED,
)
from nomarr.helpers.dto.repo_dto import SongStateAssignmentRow, SongStateRow
from nomarr.persistence.models.song_state import SongState
from nomarr.persistence.models.song_state_assignment import SongStateAssignment
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import insert_one

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session

_A: Table = SongStateAssignment.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_S: Table = SongState.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table


def _assignment_row_to_dto(row: Row) -> SongStateAssignmentRow:
    """Convert a SQLAlchemy ``Row`` to a ``SongStateAssignmentRow``."""
    m = row._mapping
    return SongStateAssignmentRow(
        id=m["id"],
        song_id=m["song_id"],
        state_id=m["state_id"],
        created_at=m["created_at"],
    )


def _state_row_to_dto(row: Row) -> SongStateRow:
    """Convert a SQLAlchemy ``Row`` to a ``SongStateRow``."""
    m = row._mapping
    return SongStateRow(
        id=m["id"],
        name=m["name"],
        description=m["description"],
    )


class SongStateRepository:
    """Repository for ``song_states`` and ``song_state_assignments``."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    def get_song_states(self, song_id: int) -> set[str]:
        """Return all state names assigned to one song."""
        with map_persistence_exceptions():
            stmt = select(_S.c.name).join(_A, _S.c.id == _A.c.state_id).where(_A.c.song_id == song_id)
            result = self._session.execute(stmt)
            return {row[0] for row in result.all()}

    def get_song_states_for_songs(self, song_ids: list[int]) -> dict[int, set[str]]:
        """Return ``{song_id: {state_names}}`` for a batch of song ids."""
        with map_persistence_exceptions():
            if not song_ids:
                return {}
            stmt = select(_A.c.song_id, _S.c.name).join(_S, _S.c.id == _A.c.state_id).where(_A.c.song_id.in_(song_ids))
            result = self._session.execute(stmt)
            mapping: dict[int, set[str]] = {}
            for r in result.all():
                mapping.setdefault(r[0], set()).add(r[1])
            return mapping

    def list_songs_in_state(self, state: str, *, limit: int | None = None) -> list[int]:
        """Return song ids assigned to *state*."""
        with map_persistence_exceptions():
            stmt = select(_A.c.song_id).join(_S, _S.c.id == _A.c.state_id).where(_S.c.name == state)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    def count_songs_in_state(self, state: str) -> int:
        """Count songs assigned to *state*."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_A).join(_S, _S.c.id == _A.c.state_id).where(_S.c.name == state)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def assign_state(self, song_id: int, state: str) -> None:
        """Assign a state (by name) to a song.

        Resolves the state name to its ``state_id`` via the
        ``song_states`` lookup table, then inserts an assignment.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                # Resolve state name → id
                stmt = select(_S.c.id).where(_S.c.name == state)
                result = self._session.execute(stmt)
                row = result.fetchone()
                if row is None:
                    msg = f"Unknown song state: {state!r}"
                    raise ValueError(msg)
                state_id = row[0]

                payload = {
                    "song_id": song_id,
                    "state_id": state_id,
                    "created_at": int(time.time() * 1000),
                }
                insert_one(_A, payload, session=self._session)
            self._session.commit()

    def assign_states(self, song_ids: list[int], state: str) -> None:
        """Atomically and idempotently assign *state* to all *song_ids*.

        A single transaction prevents a duplicate assignment from leaving a
        batch partially applied.  Conflict-safe insertion also makes retries
        and duplicate song ids harmless.
        """
        with map_persistence_exceptions():
            if not song_ids:
                return

            with self._session.begin_nested():
                state_stmt = select(_S.c.id).where(_S.c.name == state)
                state_row = self._session.execute(state_stmt).fetchone()
                if state_row is None:
                    msg = f"Unknown song state: {state!r}"
                    raise ValueError(msg)

                unique_song_ids = list(dict.fromkeys(song_ids))
                now_ms = int(time.time() * 1000)
                rows = [
                    {"song_id": song_id, "state_id": state_row[0], "created_at": now_ms} for song_id in unique_song_ids
                ]
                self._session.execute(
                    pg_insert(_A).values(rows).on_conflict_do_nothing(index_elements=["song_id", "state_id"])
                )
            self._session.commit()

    def replace_state_for_songs(self, song_ids: list[int], state: str) -> None:
        """Atomically replace all state assignments for the given songs.

        The delete and insert share one transaction so a retry cannot leave a
        song without a state.  Existing assignments are ignored to make the
        operation idempotent after a partially completed retry.
        """
        with map_persistence_exceptions():
            if not song_ids:
                return

            with self._session.begin_nested():
                state_stmt = select(_S.c.id).where(_S.c.name == state)
                state_row = self._session.execute(state_stmt).fetchone()
                if state_row is None:
                    msg = f"Unknown song state: {state!r}"
                    raise ValueError(msg)

                unique_song_ids = list(dict.fromkeys(song_ids))
                self._session.execute(delete(_A).where(_A.c.song_id.in_(unique_song_ids)))
                assignment_rows = [
                    {
                        "song_id": song_id,
                        "state_id": state_row[0],
                        "created_at": int(time.time() * 1000),
                    }
                    for song_id in unique_song_ids
                ]
                self._session.execute(
                    pg_insert(_A).values(assignment_rows).on_conflict_do_nothing(index_elements=["song_id", "state_id"])
                )
            self._session.commit()

    def transition_to_hydrated(self, song_ids: list[int]) -> None:
        """Atomically transition songs to ``hydrated`` without dropping other axes.

        For every song in *song_ids* this removes any ``not_hydrated``
        assignment (only if present) and establishes ``hydrated``.  All other
        state axes (processed, scanned, calibrated, …) are left untouched — it
        deliberately does NOT use :meth:`replace_state_for_songs` (which
        wipes every axis).  Idempotent: re-running on already-hydrated songs
        yields the same final assignments (insert is conflict-safe).

        Set-based: one query resolves the two state ids, one delete clears
        ``not_hydrated``, one bulk insert establishes ``hydrated``.

        UoW-safe: never commits internally — the caller's unit of work owns
        the transaction.

        Args:
            song_ids: Songs to transition to ``hydrated``.

        """
        unique_song_ids = list(dict.fromkeys(song_ids))
        if not unique_song_ids:
            return

        # Hydration can be the first state operation after a database is
        # created.  Seed the two vertices this transition needs rather than
        # silently treating an empty lookup table as success.
        state_rows = [
            {"name": STATE_HYDRATED, "description": "Song metadata has been hydrated"},
            {"name": STATE_NOT_HYDRATED, "description": "Song metadata has not been hydrated"},
        ]
        self._session.execute(pg_insert(_S).values(state_rows).on_conflict_do_nothing(index_elements=["name"]))

        # Resolve both state names → ids in ONE query.
        state_stmt = select(_S.c.name, _S.c.id).where(_S.c.name.in_([STATE_HYDRATED, STATE_NOT_HYDRATED]))
        state_ids: dict[str, int] = {str(name): int(sid) for name, sid in self._session.execute(state_stmt)}
        hydrated_id = state_ids.get(STATE_HYDRATED)
        not_hydrated_id = state_ids.get(STATE_NOT_HYDRATED)

        # Drop not_hydrated membership only (other axes preserved).
        if not_hydrated_id is not None:
            self._session.execute(
                delete(_A).where(
                    _A.c.song_id.in_(unique_song_ids),
                    _A.c.state_id == not_hydrated_id,
                )
            )

        # Establish hydrated (conflict-safe ⇒ idempotent).
        if hydrated_id is not None:
            now_ms = int(time.time() * 1000)
            rows = [{"song_id": sid, "state_id": hydrated_id, "created_at": now_ms} for sid in unique_song_ids]
            self._session.execute(
                pg_insert(_A).values(rows).on_conflict_do_nothing(index_elements=["song_id", "state_id"])
            )

    def remove_states_for_songs(self, song_ids: list[int]) -> None:
        """Delete all state assignments for the given song ids."""
        with map_persistence_exceptions():
            if not song_ids:
                return
            with self._session.begin_nested():
                stmt = delete(_A).where(_A.c.song_id.in_(song_ids))
                self._session.execute(stmt)
            self._session.commit()

    def remove_state_for_songs(self, song_ids: list[int], state: str) -> None:
        """Delete one named state assignment from the given songs."""
        with map_persistence_exceptions():
            if not song_ids:
                return
            with self._session.begin_nested():
                state_ids = select(_S.c.id).where(_S.c.name == state)
                stmt = delete(_A).where(
                    _A.c.song_id.in_(song_ids),
                    _A.c.state_id.in_(state_ids),
                )
                self._session.execute(stmt)
            self._session.commit()

    def bootstrap_states(self, song_ids: list[int]) -> None:
        """Ensure the 16 canonical axis-pair state vertices exist.

        If ``song_states`` is empty, seeds the 16 vertices from
        ``ALL_STATE_VERTICES`` (bare axis names, one row per name with a
        description), then assigns the positive (``processed``) vertex to
        each song id in *song_ids*. If the table is already non-empty, this
        is a no-op.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                # Check if states already exist
                count_stmt = select(func.count()).select_from(_S)
                result = self._session.execute(count_stmt)
                if (result.scalar() or 0) > 0:
                    return

                descriptions = {
                    "processed": "Tags have been applied",
                    "not_processed": "Tags have not been applied",
                    "calibrated": "Tags have been calibrated",
                    "not_calibrated": "Tags have not been calibrated",
                    "written": "Tags written to file metadata",
                    "not_written": "Tags not written to file metadata",
                    "tags_current": "Tags are current for the song",
                    "tags_not_fresh": "Tags are not fresh for the song",
                    "hydrated": "Song metadata has been hydrated",
                    "not_hydrated": "Song metadata has not been hydrated",
                    "scanned": "Song has been scanned",
                    "not_scanned": "Song has not been scanned",
                    "vectors_extracted": "Embedding vectors have been extracted",
                    "not_vectors_extracted": "Embedding vectors have not been extracted",
                    "errored": "Processing error occurred",
                    "not_errored": "No processing error",
                }
                for name in ALL_STATE_VERTICES:
                    insert_one(_S, {"name": name, "description": descriptions[name]}, session=self._session)

                # Assign the positive vertex (STATE_PROCESSED) to each song.
                state_stmt = select(_S.c.id).where(_S.c.name == STATE_PROCESSED)
                state_result = self._session.execute(state_stmt)
                state_row = state_result.fetchone()
                if state_row is not None:
                    processed_state_id = state_row[0]
                    for song_id in song_ids:
                        payload = {
                            "song_id": song_id,
                            "state_id": processed_state_id,
                            "created_at": int(time.time() * 1000),
                        }
                        insert_one(_A, payload, session=self._session)
            self._session.commit()

    def count_for_song_and_state(self, song_id: int, state_tag_id: int) -> int:
        """Count assignments for a specific song + state-id combination."""
        with map_persistence_exceptions():
            stmt = (
                select(func.count())
                .select_from(_A)
                .where(
                    _A.c.song_id == song_id,
                    _A.c.state_id == state_tag_id,
                )
            )
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def ensure_song_state(self, song_id: int, state: str) -> None:
        """Assign *state* to a song only if it has no state assignment yet.

        Used during song upsert to initialize newly created songs with their
        default processing state.  Songs that already carry at least one state
        assignment are left untouched.
        """
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_A).where(_A.c.song_id == song_id)
            result = self._session.execute(stmt)
            if (result.scalar() or 0) > 0:
                return
            self.assign_state(song_id, state)

    def truncate_assignments(self) -> None:
        """Delete all rows from ``song_state_assignments``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_A))
            self._session.commit()
