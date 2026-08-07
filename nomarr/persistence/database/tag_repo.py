"""TagRepository — CRUD and domain queries for tags.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
JOINs, filtered queries, and batch operations.

File-tag junction operations live in ``FileTagRepository``
(``file_tag_repo.py``).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select

from nomarr.helpers.dto.repo_dto import TagRow
from nomarr.persistence.models.file_tag import SongTag
from nomarr.persistence.models.tag import Tag
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    select_by_key,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session
    from sqlalchemy.schema import Table

_T: Table = Tag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_FT: Table = SongTag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table


def _tag_row_to_dto(row: Row) -> TagRow:
    """Convert a SQLAlchemy ``Row`` to a ``TagRow`` TypedDict."""
    m = row._mapping
    return TagRow(
        id=m["id"],
        name=m["name"],
        value=m["value"],
        namespace=m["namespace"],
        parent_tag_id=m["parent_tag_id"],
        source=m["source"],
        confidence=m["confidence"],
        tier=m["tier"],
        created_at=m["created_at"],
    )


class TagRepository:
    """Repository for the ``tags`` table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── core CRUD ───────────────────────────────────────────────

    def get_tag(self, tag_id: int) -> TagRow | None:
        """Fetch a single tag by primary key."""
        with map_persistence_exceptions():
            row = select_by_key(_T, tag_id, session=self._session)
            return _tag_row_to_dto(row) if row else None

    def get_tag_by_name(self, name: str, namespace: str) -> TagRow | None:
        """Fetch a tag by ``name`` AND ``namespace``."""
        with map_persistence_exceptions():
            stmt = select(_T).where(
                _T.c.name == name,
                _T.c.namespace == namespace,
            )
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _tag_row_to_dto(row) if row else None

    def get_or_create_tag(self, name: str, value: str, namespace: str) -> int:
        """Return the id of an existing tag or insert a new one."""
        with map_persistence_exceptions():
            stmt = select(_T.c.id).where(
                _T.c.name == name,
                _T.c.value == value,
                _T.c.namespace == namespace,
            )
            result = self._session.execute(stmt)
            row = result.fetchone()
            if row is not None:
                return int(row[0])
            with self._session.begin_nested():
                payload = {
                    "name": name,
                    "value": value,
                    "namespace": namespace,
                    "source": "nomarr",
                    "created_at": int(time.time() * 1000),
                }
                inserted = insert_one(_T, payload, session=self._session)
            self._session.commit()
            return int(inserted._mapping["id"])

    def create_tag(self, payload: dict[str, Any]) -> int:
        """Insert a new tag row and return its ``id``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                row = insert_one(_T, payload, session=self._session)
            self._session.commit()
            return int(row._mapping["id"])

    def delete_tag(self, tag_id: int) -> None:
        """Delete a tag by primary key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_T, tag_id, session=self._session)
            self._session.commit()

    # ── orphan management ───────────────────────────────────────

    def get_orphaned_tag_ids(self) -> list[int]:
        """Return tag ids that have no file-tag assignments."""
        with map_persistence_exceptions():
            stmt = select(_T.c.id).outerjoin(_FT, _T.c.id == _FT.c.tag_id).where(_FT.c.id.is_(None))
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    def cleanup_orphaned_tags(self) -> int:
        """Delete tags with no file assignments; return the count deleted."""
        with map_persistence_exceptions():
            orphaned = self.get_orphaned_tag_ids()
            if not orphaned:
                return 0
            with self._session.begin_nested():
                stmt = delete(_T).where(_T.c.id.in_(orphaned))
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    # ── tag listing ─────────────────────────────────────────────

    def list_tags(
        self,
        *,
        name: str | None = None,
        value: Any = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TagRow]:
        """Return tags with optional name/value filters and pagination."""
        with map_persistence_exceptions():
            stmt = select(_T)
            if name is not None:
                stmt = stmt.where(_T.c.name == name)
            if value is not None:
                stmt = stmt.where(_T.c.value == value)
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    def count_tags(self) -> int:
        """Return total row count of ``tags``."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_T)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    # ── search ──────────────────────────────────────────────────

    def get_tag_value_frequencies(self, tag_name: str, *, limit: int) -> list[tuple[str, int]]:
        """Return ``(value, count)`` pairs for a given tag name, grouped."""
        with map_persistence_exceptions():
            stmt = (
                select(_T.c.value, func.count().label("cnt"))
                .where(_T.c.name == tag_name)
                .group_by(_T.c.value)
                .order_by(func.count().desc())
                .limit(limit)
            )
            result = self._session.execute(stmt)
            return [(row[0], row[1]) for row in result.all()]

    def get_tag_value_frequencies_batch(
        self,
        tag_names: list[str],
        *,
        limit: int,
    ) -> dict[str, list[tuple[str, int]]]:
        """Return ``(value, count)`` pairs for multiple tag names in a single query.

        Groups by ``(name, value)`` and returns a dict mapping each tag name
        to its list of ``(value, count)`` tuples, ordered by count descending.
        """
        with map_persistence_exceptions():
            if not tag_names:
                return {}
            stmt = (
                select(_T.c.name, _T.c.value, func.count().label("cnt"))
                .where(_T.c.name.in_(tag_names))
                .group_by(_T.c.name, _T.c.value)
                .order_by(_T.c.name, func.count().desc())
            )
            result = self._session.execute(stmt)
            grouped: dict[str, list[tuple[str, int]]] = {name: [] for name in tag_names}
            for row in result.all():
                name, value, cnt = row[0], row[1], row[2]
                if name in grouped:
                    grouped[name].append((value, cnt))
            # Apply per-name limit (SQL LIMIT was global, not per-group)
            return {name: pairs[:limit] for name, pairs in grouped.items()}

    # ── Plan E facade support ───────────────────────────────────

    def list_all_tag_names(self, *, limit: int | None = None) -> list[str]:
        """Return distinct tag names."""
        with map_persistence_exceptions():
            stmt = select(_T.c.name).distinct()
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    def count_tags_filtered(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
    ) -> int:
        """Count tags with optional name and search filters."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_T)
            if name is not None:
                stmt = stmt.where(_T.c.name == name)
            if search is not None:
                stmt = stmt.where(_T.c.name.ilike(f"%{search}%"))
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def list_tags_with_song_count(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return tags with their file-assignment count."""
        with map_persistence_exceptions():
            stmt = select(
                _T.c.id,
                _T.c.name,
                _T.c.value,
                _T.c.namespace,
                _T.c.source,
                _T.c.confidence,
                _T.c.tier,
                _T.c.created_at,
                _T.c.parent_tag_id,
                func.count(_FT.c.file_id).label("song_count"),
            ).outerjoin(_FT, _T.c.id == _FT.c.tag_id)
            if name is not None:
                stmt = stmt.where(_T.c.name == name)
            if search is not None:
                stmt = stmt.where(_T.c.name.ilike(f"%{search}%"))
            stmt = stmt.group_by(
                _T.c.id,
                _T.c.name,
                _T.c.value,
                _T.c.namespace,
                _T.c.source,
                _T.c.confidence,
                _T.c.tier,
                _T.c.created_at,
                _T.c.parent_tag_id,
            )
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "value": r[2],
                    "namespace": r[3],
                    "source": r[4],
                    "confidence": r[5],
                    "tier": r[6],
                    "created_at": r[7],
                    "parent_tag_id": r[8],
                    "song_count": r[9],
                }
                for r in result.all()
            ]

    # ── maintenance ─────────────────────────────────────────────

    def truncate_tags(self) -> None:
        """Delete all rows from ``tags``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T))
            self._session.commit()

    def delete_tags_by_ids(self, tag_ids: list[int]) -> int:
        """Delete tags by their primary keys; return the count deleted."""
        with map_persistence_exceptions():
            if not tag_ids:
                return 0
            with self._session.begin_nested():
                stmt = delete(_T).where(_T.c.id.in_(tag_ids))
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime
