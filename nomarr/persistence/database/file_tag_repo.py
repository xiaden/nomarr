"""FileTagRepository — file ↔ tag junction operations.

Manages the ``file_tags`` junction table that links library files to tags.
Split from ``TagRepository`` to keep each repo focused on a single table
group (see persistence.md size guidelines).
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, scoped_session
from sqlalchemy.schema import Table

from nomarr.helpers.dto.repo_dto import LibraryFileRow, TagRow
from nomarr.persistence.database.repo_helpers import _file_row_to_dto
from nomarr.persistence.models.file_tag import FileTag
from nomarr.persistence.models.library_file import LibraryFile
from nomarr.persistence.models.tag import Tag
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import insert_one

_T: Table = Tag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_FT: Table = FileTag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_LF: Table = LibraryFile.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table


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


class FileTagRepository:
    """Repository for the ``file_tags`` junction table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── file-tag associations ───────────────────────────────────

    def get_tags_for_file(self, file_id: int) -> list[TagRow]:
        """Return all tags assigned to a file via the ``file_tags`` junction."""
        with map_persistence_exceptions():
            stmt = select(_T).join(_FT, _T.c.id == _FT.c.tag_id).where(_FT.c.file_id == file_id)
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    def assign_tag_to_file(
        self,
        file_id: int,
        tag_id: int,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> None:
        """Insert a row into ``file_tags`` linking *file_id* to *tag_id*."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                payload = {
                    "file_id": file_id,
                    "tag_id": tag_id,
                    "confidence": confidence,
                    "source": source or "nomarr",
                    "created_at": int(time.time() * 1000),
                }
                insert_one(_FT, payload, session=self._session)
            self._session.commit()

    def remove_tag_from_file(self, file_id: int, tag_id: int) -> None:
        """Delete the junction row for a specific file + tag pair."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_FT).where(
                    _FT.c.file_id == file_id,
                    _FT.c.tag_id == tag_id,
                )
                self._session.execute(stmt)
            self._session.commit()

    def replace_file_tags(self, file_id: int, tags: list[dict[str, Any]]) -> None:
        """Delete all existing tag assignments for a file and insert new ones."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_FT).where(_FT.c.file_id == file_id))
                if tags:
                    now_ms = int(time.time() * 1000)
                    rows = [
                        {
                            "file_id": file_id,
                            "tag_id": t["tag_id"],
                            "confidence": t.get("confidence", 1.0),
                            "source": t.get("source", "nomarr"),
                            "created_at": now_ms,
                        }
                        for t in tags
                    ]
                    self._session.execute(pg_insert(_FT).values(rows))
            self._session.commit()

    def get_files_for_tag(self, tag_id: int, limit: int | None = None) -> list[LibraryFileRow]:
        """Return files assigned to a tag via JOIN."""
        with map_persistence_exceptions():
            stmt = select(_LF).join(_FT, _LF.c.id == _FT.c.file_id).where(_FT.c.tag_id == tag_id)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_file_row_to_dto(r) for r in result.all()]

    def list_file_ids_for_tag(
        self,
        tag_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[int]:
        """Return file ids assigned to a tag with pagination."""
        with map_persistence_exceptions():
            stmt = select(_FT.c.file_id).where(_FT.c.tag_id == tag_id)
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    # ── batch queries ───────────────────────────────────────────

    def get_tags_for_files_batch(
        self,
        file_ids: list[int],
        *,
        name_starts_with: str | None = None,
        include_edge: bool = False,
    ) -> list[dict[str, Any]]:
        """Return tag assignments for a batch of file ids.

        Each dict contains ``file_id``, ``tag_id``, ``tag_name``,
        ``tag_value``, ``namespace``, ``parent_tag_id``, ``tier``,
        ``created_at``, ``confidence``, and ``source``.
        """
        with map_persistence_exceptions():
            if not file_ids:
                return []
            stmt = (
                select(
                    _FT.c.file_id,
                    _FT.c.tag_id,
                    _T.c.name,
                    _T.c.value,
                    _T.c.namespace,
                    _T.c.parent_tag_id,
                    _T.c.tier,
                    _T.c.created_at,
                    _FT.c.confidence,
                    _FT.c.source,
                )
                .join(_T, _T.c.id == _FT.c.tag_id)
                .where(_FT.c.file_id.in_(file_ids))
            )
            if name_starts_with is not None:
                stmt = stmt.where(_T.c.name.like(name_starts_with + "%"))
            result = self._session.execute(stmt)
            return [
                {
                    "file_id": r[0],
                    "tag_id": r[1],
                    "tag_name": r[2],
                    "tag_value": r[3],
                    "namespace": r[4],
                    "parent_tag_id": r[5],
                    "tier": r[6],
                    "created_at": r[7],
                    "confidence": r[8],
                    "source": r[9],
                }
                for r in result.all()
            ]

    def get_song_tags(self, file_id: int, nomarr_only: bool = False) -> list[TagRow]:
        """Return tags for a file, optionally filtered to ``nom:`` namespace."""
        with map_persistence_exceptions():
            stmt = select(_T).join(_FT, _T.c.id == _FT.c.tag_id).where(_FT.c.file_id == file_id)
            if nomarr_only:
                stmt = stmt.where(_T.c.namespace == "nom")
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    # ── search ──────────────────────────────────────────────────

    def search_files_by_tag(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return files that have a tag with exact *tag_key* name and *value*."""
        with map_persistence_exceptions():
            stmt = (
                select(_LF)
                .join(_FT, _LF.c.id == _FT.c.file_id)
                .join(_T, _T.c.id == _FT.c.tag_id)
                .where(_T.c.name == tag_key, _T.c.value == value)
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_file_row_to_dto(r) for r in result.all()]

    def search_files_by_tag_contains(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return files whose tag value contains *value* (ILIKE)."""
        with map_persistence_exceptions():
            stmt = (
                select(_LF)
                .join(_FT, _LF.c.id == _FT.c.file_id)
                .join(_T, _T.c.id == _FT.c.tag_id)
                .where(
                    _T.c.name == tag_key,
                    _T.c.value.ilike(f"%{value}%"),
                )
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_file_row_to_dto(r) for r in result.all()]

    def search_files_by_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return files whose tag value matches an ILIKE *pattern*."""
        with map_persistence_exceptions():
            stmt = (
                select(_LF)
                .join(_FT, _LF.c.id == _FT.c.file_id)
                .join(_T, _T.c.id == _FT.c.tag_id)
                .where(
                    _T.c.name == tag_name,
                    _T.c.value.ilike(pattern),
                )
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_file_row_to_dto(r) for r in result.all()]

    def replace_tag_references(
        self,
        source_tag_id: int,
        target_tag_id: int,
        *,
        file_ids: list[int] | None = None,
    ) -> None:
        """Re-point file-tag assignments from *source_tag_id* to *target_tag_id*."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = update(_FT).where(_FT.c.tag_id == source_tag_id)
                if file_ids is not None:
                    stmt = stmt.where(_FT.c.file_id.in_(file_ids))
                stmt = stmt.values(tag_id=target_tag_id)
                self._session.execute(stmt)
            self._session.commit()

    # ── Plan E facade support ───────────────────────────────────

    def get_genre_tags_for_files(self, file_ids: list[int]) -> list[TagRow]:
        """Return genre tags assigned to the given file ids."""
        with map_persistence_exceptions():
            if not file_ids:
                return []
            stmt = (
                select(_T)
                .join(_FT, _T.c.id == _FT.c.tag_id)
                .where(
                    _FT.c.file_id.in_(file_ids),
                    _T.c.name == "genre",
                )
            )
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    # ── maintenance ─────────────────────────────────────────────

    def truncate_file_tag_assignments(self) -> None:
        """Delete all rows from ``file_tags``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_FT))
            self._session.commit()

    def count_songs_for_tag(self, tag_id: int) -> int:
        """Count file-tag assignments for a specific tag."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_FT).where(_FT.c.tag_id == tag_id)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def count_files_by_tag(self, tag_key: str, target_value: str) -> int:
        """Count distinct files assigned to tags matching *tag_key* and *target_value*."""
        with map_persistence_exceptions():
            stmt = (
                select(func.count(func.distinct(_FT.c.file_id)))
                .join(_T, _T.c.id == _FT.c.tag_id)
                .where(
                    _T.c.name == tag_key,
                    _T.c.value == target_value,
                )
            )
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def get_file_tag_edges_for_tags(
        self,
        tag_ids: list[int],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return file-tag edge rows for the given tag ids.

        Each dict contains ``file_id``, ``tag_id``, ``confidence``, and ``source``.
        """
        with map_persistence_exceptions():
            if not tag_ids:
                return []
            stmt = select(
                _FT.c.file_id,
                _FT.c.tag_id,
                _FT.c.confidence,
                _FT.c.source,
            ).where(_FT.c.tag_id.in_(tag_ids))
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [
                {
                    "file_id": r[0],
                    "tag_id": r[1],
                    "confidence": r[2],
                    "source": r[3],
                }
                for r in result.all()
            ]
