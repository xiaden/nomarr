"""Shared helpers for repository modules.

Contains utility functions used across multiple repository files to avoid
duplication.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from nomarr.helpers.dto.repo_dto import SongRow
from nomarr.persistence.sql.exceptions import map_persistence_exceptions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session


@contextmanager
def atomic_unit_of_work(session: scoped_session[Session]) -> Iterator[None]:
    """Run statements on *session* as a single atomic unit of work.

    All repository statements executed inside the ``with`` block share the
    existing scoped SQLAlchemy session and one outer transaction. The unit
    commits exactly once on success and rolls back the entire unit on any
    exception, so no partial writes can leak from a failed multi-statement
    intent (e.g. song hydration).

    Mirrors the repository conventions used across ``song_repo``,
    ``song_tag_repo``, ``tag_repo``, and ``song_state_repo``: an inner
    ``begin_nested()`` savepoint scopes the statements and
    ``map_persistence_exceptions`` translates SQLAlchemy errors into domain
    exceptions. On failure ``session.rollback()`` discards the whole unit.

    Facades and callers must NOT open their own transactions around this
    primitive; the unit owns the commit/rollback boundary.
    """
    try:
        with map_persistence_exceptions():
            with session.begin_nested():
                yield
            session.commit()
    except BaseException:
        session.rollback()
        raise


def _song_row_to_dto(row: Row) -> SongRow:
    """Convert a SQLAlchemy ``Row`` to a ``SongRow`` TypedDict."""
    m = row._mapping
    return SongRow(
        id=m["id"],
        library_id=m["library_id"],
        folder_id=m["folder_id"],
        path=m["path"],
        normalized_path=m["normalized_path"],
        file_size=m["file_size"],
        modified_time=m["modified_time"],
        duration_seconds=m["duration_seconds"],
        chromaprint=m["chromaprint"],
        needs_tagging=m["needs_tagging"],
        is_valid=m["is_valid"],
        tagged=m["tagged"],
        calibration_hash=m["calibration_hash"],
        write_claimed_by=m["write_claimed_by"],
        last_tagged_at=m["last_tagged_at"],
        scanned_at=m["scanned_at"],
        created_at=m["created_at"],
    )
