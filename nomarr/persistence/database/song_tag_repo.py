"""SongTagRepository — song ↔ tag junction operations.

Manages the ``song_tags`` junction table that links songs to tags.
Split from ``TagRepository`` to keep each repo focused on a single table
group (see persistence.md size guidelines).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, and_, case, cast, delete, exists, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.dto.repo_dto import NumericSongTagMatchRow, SongRow
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import insert_one

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session
    from sqlalchemy.schema import Table


def _escape_like_search(value: str) -> str:
    """Escape LIKE metacharacters in a literal search value."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_T: Table = Tag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_ST: Table = SongTag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_S: Table = Song.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table


def _tag_row_to_dto(row: Row) -> dict[str, Any]:
    """Map a joined tag+song_tags row to identity fields plus edge metadata.

    Reads only identity columns from ``tags`` (id, namespace, name, value) and
    confidence/source/timestamps from the ``song_tags`` edge — never from the
    removed ``tags`` metadata columns.
    """
    m = row._mapping
    return {
        "id": m["id"],
        "namespace": m["namespace"],
        "name": m["name"],
        "value": m["value"],
        "confidence": m["confidence"],
        "source": m["source"],
        "created_at": m["created_at"],
    }


def _row_to_dto(row: Row) -> SongRow:
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


def _numeric_match_row_to_dto(row: Row) -> NumericSongTagMatchRow:
    """Convert a SQLAlchemy ``Row`` to a ``NumericSongTagMatchRow`` TypedDict."""
    m = row._mapping
    return NumericSongTagMatchRow(
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
        matched_tag=m["matched_tag"],
        distance=m["distance"],
    )


#: Regex for a numeric text value: optional sign, int/decimal, optional exponent.
#: Mirrors the acceptance rules of ``is_numeric_tag_value`` (int/float, non-bool)
#: as applied to string-typed ``tags.value``.
_NUMERIC_TEXT_RE = r"^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$"


class SongTagRepository:
    """Repository for the ``song_tags`` junction table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── song-tag associations ───────────────────────────────────

    def get_tags_for_song(self, song_id: int) -> list[dict[str, Any]]:
        """Return all tags assigned to a song via the ``song_tags`` junction.

        Each row carries identity fields from ``tags`` plus edge metadata
        (confidence, source, created_at) from ``song_tags``.
        """
        with map_persistence_exceptions():
            stmt = (
                select(
                    _T.c.id,
                    _T.c.namespace,
                    _T.c.name,
                    _T.c.value,
                    _ST.c.confidence,
                    _ST.c.source,
                    _ST.c.created_at,
                )
                .join(_ST, _T.c.id == _ST.c.tag_id)
                .where(_ST.c.song_id == song_id)
            )
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    def assign_tag_to_song(
        self,
        song_id: int,
        tag_id: int,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> None:
        """Insert a row into ``song_tags`` linking *song_id* to *tag_id*."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                payload = {
                    "song_id": song_id,
                    "tag_id": tag_id,
                    "confidence": confidence,
                    "source": source or "nomarr",
                    "created_at": int(time.time() * 1000),
                }
                insert_one(_ST, payload, session=self._session)
            self._session.commit()

    def remove_tag_from_song(self, song_id: int, tag_id: int) -> None:
        """Delete the junction row for a specific song + tag pair."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_ST).where(
                    _ST.c.song_id == song_id,
                    _ST.c.tag_id == tag_id,
                )
                self._session.execute(stmt)
            self._session.commit()

    def remove_tags_from_song(self, song_id: int, tag_ids: list[int]) -> None:
        """Delete several tag assignments for a song in one transaction."""
        if not tag_ids:
            return
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_ST).where(
                    _ST.c.song_id == song_id,
                    _ST.c.tag_id.in_(tag_ids),
                )
                self._session.execute(stmt)
            self._session.commit()

    def replace_song_tags_batch(
        self,
        edges: list[dict[str, Any]],
        *,
        song_ids: list[int] | None = None,
    ) -> None:
        """Set-based full-replace of song↔tag edges across many songs.

        Takes *edges* as a flat list of ``{"song_id", "tag_id",
        "confidence", "source"}`` dicts (callers MUST resolve ``tag_id``
        beforehand — this repo never looks tags up by name/value).  For every
        affected song the existing edges are deleted and the supplied edges are
        bulk-inserted in ONE statement each (full-replace semantics, so a retry
        yields the same assignments).  ``song_ids`` identifies affected songs
        when the replacement is intentionally empty.  Input rows are
        deduplicated by ``(song_id, tag_id)``.

        UoW-safe: never commits internally — the caller's unit of work owns
        the transaction.  No per-song/per-tag loop on the hot path.

        Args:
            edges: Flat list of edge dicts.  ``confidence`` defaults to
                   ``1.0`` and ``source`` to ``"nomarr"`` when omitted.

        """
        affected_song_ids = list(dict.fromkeys(song_ids or [int(e["song_id"]) for e in edges]))
        if not affected_song_ids:
            return
        now_ms = int(time.time() * 1000)
        # Dedupe by (song_id, tag_id) and group per song.
        deduped: dict[tuple[int, int], dict[str, Any]] = {}
        for e in edges:
            key = (int(e["song_id"]), int(e["tag_id"]))
            deduped.setdefault(
                key,
                {
                    "song_id": key[0],
                    "tag_id": key[1],
                    "confidence": float(e.get("confidence", 1.0)),
                    "source": str(e.get("source", "nomarr")),
                    "created_at": now_ms,
                },
            )
        rows = list(deduped.values())
        self._session.execute(delete(_ST).where(_ST.c.song_id.in_(affected_song_ids)))
        if rows:
            self._session.execute(pg_insert(_ST).values(rows))

    def replace_song_tags(self, song_id: int, tags: list[dict[str, Any]]) -> None:
        """Delete all existing tag assignments for a song and insert new ones."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_ST).where(_ST.c.song_id == song_id))
                if tags:
                    now_ms = int(time.time() * 1000)
                    rows = [
                        {
                            "song_id": song_id,
                            "tag_id": t["tag_id"],
                            "confidence": t.get("confidence", 1.0),
                            "source": t.get("source", "nomarr"),
                            "created_at": now_ms,
                        }
                        for t in tags
                    ]
                    self._session.execute(pg_insert(_ST).values(rows))
            self._session.commit()

    def get_songs_for_tag(self, tag_id: int, limit: int | None = None) -> list[SongRow]:
        """Return songs assigned to a tag via JOIN."""
        with map_persistence_exceptions():
            stmt = select(_S).join(_ST, _S.c.id == _ST.c.song_id).where(_ST.c.tag_id == tag_id)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def list_song_ids_for_tag(
        self,
        tag_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[int]:
        """Return song ids assigned to a tag with pagination, ordered by song id."""
        with map_persistence_exceptions():
            stmt = select(_ST.c.song_id).where(_ST.c.tag_id == tag_id).order_by(_ST.c.song_id)
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    # ── batch queries ───────────────────────────────────────────

    def get_tags_for_songs_batch(
        self,
        song_ids: list[int],
        *,
        name_starts_with: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return tag assignments for a batch of song ids.

        Each dict contains ``song_id``, ``tag_id``, ``tag_name``,
        ``tag_value``, ``namespace``, and the edge metadata ``confidence`` and
        ``source`` (from ``song_tags`` only).
        """
        with map_persistence_exceptions():
            if not song_ids:
                return []
            stmt = (
                select(
                    _ST.c.song_id,
                    _ST.c.tag_id,
                    _T.c.name,
                    _T.c.value,
                    _T.c.namespace,
                    _ST.c.confidence,
                    _ST.c.source,
                )
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(_ST.c.song_id.in_(song_ids))
            )
            if name_starts_with is not None:
                stmt = stmt.where(_T.c.name.like(name_starts_with + "%"))
            result = self._session.execute(stmt)
            return [
                {
                    "song_id": r[0],
                    "tag_id": r[1],
                    "tag_name": r[2],
                    "tag_value": r[3],
                    "namespace": r[4],
                    "confidence": r[5],
                    "source": r[6],
                }
                for r in result.all()
            ]

    def get_song_tags(self, song_id: int, nomarr_only: bool = False) -> list[dict[str, Any]]:
        """Return tags for a song, optionally filtered to ``nom:`` namespace.

        Each row carries identity fields from ``tags`` plus edge metadata
        (confidence, source, created_at) from ``song_tags``.
        """
        with map_persistence_exceptions():
            stmt = (
                select(
                    _T.c.id,
                    _T.c.namespace,
                    _T.c.name,
                    _T.c.value,
                    _ST.c.confidence,
                    _ST.c.source,
                    _ST.c.created_at,
                )
                .join(_ST, _T.c.id == _ST.c.tag_id)
                .where(_ST.c.song_id == song_id)
            )
            if nomarr_only:
                stmt = stmt.where(_T.c.namespace == "nom")
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    # ── search ──────────────────────────────────────────────────

    # ── numeric tag search ─────────────────────────────────────

    @staticmethod
    def _guarded_numeric_value(value_col: Any, dialect_name: str):
        """Return a SQL expression yielding the numeric value of *value_col* or NULL.

        The CASE guard ensures invalid numeric text in ``tags.value`` can NEVER
        reach an unconditional ``CAST`` that raises: PostgreSQL's
        ``CAST(text AS float)`` aborts the whole statement on bad input, so the
        guard is essential there. SQLite's ``CAST`` never raises, but the same
        guard stops non-numeric strings (e.g. ``"rock"``) from being coerced to
        ``0.0`` and matching a bogus zero distance. The dialect-specific
        regexp operator (``~`` on PostgreSQL, a GLOB character-class check on
        SQLite) is selected here so the validity predicate stays explicit.
        """
        if dialect_name == "postgresql":
            is_numeric = value_col.op("~")(_NUMERIC_TEXT_RE)
        else:
            # SQLite has no built-in regexp(); a GLOB character-class check is
            # sufficient for the integer/decimal values in practice and rejects
            # non-numeric text. Slightly more permissive than the PostgreSQL
            # regex (e.g. "1.2.3") — acceptable and covered by query-shape tests.
            is_numeric = and_(
                value_col.op("GLOB")("*[0-9]*"),
                ~value_col.op("GLOB")("*[^0-9.eE+-]*"),
            )
        return case((is_numeric, cast(value_col, Float)), else_=None)

    def search_songs_by_numeric_tag(
        self,
        tag_key: str,
        target_value: float | str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[NumericSongTagMatchRow]:
        """Return songs with a numeric *tag_key* tag, ordered by tag distance.

        A set-based query over ``_S``/``_ST``/``_T`` keeps only tags whose
        ``name`` is *tag_key* and whose ``value`` is valid numeric text, picks
        the single closest tag per song (deterministic tie-break by tag id),
        orders the result by ``distance ASC, song id ASC``, and applies
        offset/limit in SQL before any rows are materialized in Python.
        """
        with map_persistence_exceptions():
            bind = getattr(self._session, "bind", None)
            dialect = getattr(bind, "dialect", None)
            dialect_name = dialect.name if dialect is not None else "postgresql"

            numeric_value = self._guarded_numeric_value(_T.c.value, dialect_name)
            numeric_target = literal(float(target_value))
            distance = func.abs(numeric_value - numeric_target)
            row_number = (
                func.row_number()
                .over(
                    partition_by=_ST.c.song_id,
                    order_by=(distance.asc(), _T.c.id.asc()),
                )
                .label("rn")
            )

            inner = (
                select(
                    _S,
                    _T.c.value.label("matched_tag"),
                    distance.label("distance"),
                    row_number,
                )
                .select_from(_S)
                .join(_ST, _S.c.id == _ST.c.song_id)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.name == tag_key,
                    distance.is_not(None),
                )
                .subquery()
            )

            stmt = select(inner).where(inner.c.rn == 1).order_by(inner.c.distance.asc(), inner.c.id.asc())
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_numeric_match_row_to_dto(r) for r in result.all()]

    def count_songs_by_numeric_tag(self, tag_key: str, target_value: float | str) -> int:
        """Count distinct songs matching a numeric *tag_key* tag.

        Separate uncapped query using the SAME tag-key and safe-numeric
        predicate as :meth:`search_songs_by_numeric_tag` — no edge limit and
        no dependence on the paged query.
        """
        with map_persistence_exceptions():
            bind = getattr(self._session, "bind", None)
            dialect = getattr(bind, "dialect", None)
            dialect_name = dialect.name if dialect is not None else "postgresql"

            numeric_value = self._guarded_numeric_value(_T.c.value, dialect_name)
            distance = func.abs(numeric_value - literal(float(target_value)))
            stmt = (
                select(func.count(func.distinct(_ST.c.song_id)))
                .select_from(_ST)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.name == tag_key,
                    distance.is_not(None),
                )
            )
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def search_songs_by_tag(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SongRow]:
        """Return songs that have a tag with exact *tag_key* name and *value*."""
        with map_persistence_exceptions():
            stmt = (
                select(_S)
                .join(_ST, _S.c.id == _ST.c.song_id)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(_T.c.name == tag_key, _T.c.value == value)
            )
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def search_songs_by_tag_contains(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None = None,
    ) -> list[SongRow]:
        """Return songs whose tag value contains *value* (ILIKE)."""
        with map_persistence_exceptions():
            stmt = (
                select(_S)
                .join(_ST, _S.c.id == _ST.c.song_id)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.name == tag_key,
                    _T.c.value.ilike(f"%{_escape_like_search(value)}%", escape="\\"),
                )
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def search_songs_by_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        limit: int | None = None,
    ) -> list[SongRow]:
        """Return songs whose tag value matches an ILIKE *pattern*."""
        with map_persistence_exceptions():
            stmt = (
                select(_S)
                .join(_ST, _S.c.id == _ST.c.song_id)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.name == tag_name,
                    _T.c.value.ilike(pattern),
                )
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def relink_song_tags(
        self,
        source_tag_id: int,
        target_tag_id: int,
        *,
        song_ids: list[int] | None = None,
    ) -> dict[str, int]:
        """Re-point assignments, removing collisions; return moved/skipped counts.

        ADR-014 duplicate-safe relink: source rows that would collide with an
        existing target row are deleted (``skipped``) before the remaining
        source rows are re-pointed to the target (``moved``). ``source_orphaned``
        is 1 when the source tag lost all of its assignments as a result of this
        operation (and was not already orphaned), else 0.

        The whole operation runs in one short repository-owned transaction.
        Returns ``{"moved": int, "skipped": int, "source_orphaned": int}``.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                target_edges = _ST.alias("target_song_tags")

                in_scope = [_ST.c.tag_id == source_tag_id]
                if song_ids is not None:
                    in_scope.append(_ST.c.song_id.in_(song_ids))

                source_total = (
                    self._session.execute(select(func.count()).select_from(_ST).where(*in_scope)).scalar() or 0
                )

                collision = exists(
                    select(1)
                    .select_from(target_edges)
                    .where(
                        target_edges.c.song_id == _ST.c.song_id,
                        target_edges.c.tag_id == target_tag_id,
                    )
                )
                skipped = (
                    self._session.execute(
                        select(func.count()).select_from(_ST).where(*in_scope).where(collision)
                    ).scalar()
                    or 0
                )

                # Remove source rows that would collide with an existing target
                # row before moving the remaining source rows.  Merely excluding
                # those rows from UPDATE leaves the source assignment behind.
                delete_stmt = delete(_ST).where(*in_scope).where(collision)
                self._session.execute(delete_stmt)

                update_stmt = update(_ST).where(*in_scope).values(tag_id=target_tag_id)
                self._session.execute(update_stmt)

                remaining = (
                    self._session.execute(
                        select(func.count()).select_from(_ST).where(_ST.c.tag_id == source_tag_id)
                    ).scalar()
                    or 0
                )
            self._session.commit()
            source_orphaned = 1 if remaining == 0 and source_total > 0 else 0
            return {
                "moved": int(source_total - skipped),
                "skipped": int(skipped),
                "source_orphaned": int(source_orphaned),
            }

    # ── Plan E facade support ───────────────────────────────────

    def get_genre_tags_for_songs(self, song_ids: list[int]) -> list[dict[str, Any]]:
        """Return genre tags assigned to the given song ids.

        Each row carries identity fields from ``tags`` plus edge metadata
        (confidence, source, created_at) from ``song_tags``.
        """
        with map_persistence_exceptions():
            if not song_ids:
                return []
            stmt = (
                select(
                    _T.c.id,
                    _T.c.namespace,
                    _T.c.name,
                    _T.c.value,
                    _ST.c.confidence,
                    _ST.c.source,
                    _ST.c.created_at,
                )
                .join(_ST, _T.c.id == _ST.c.tag_id)
                .where(
                    _ST.c.song_id.in_(song_ids),
                    _T.c.name == "genre",
                )
            )
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    # ── maintenance ─────────────────────────────────────────────

    def truncate_song_tag_assignments(self) -> None:
        """Delete all rows from ``song_tags``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_ST))
            self._session.commit()

    def count_songs_for_tag(self, tag_id: int) -> int:
        """Count song-tag assignments for a specific tag."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_ST).where(_ST.c.tag_id == tag_id)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def count_songs_by_tag(self, tag_key: str, target_value: str) -> int:
        """Count distinct songs assigned to tags matching *tag_key* and *target_value*."""
        with map_persistence_exceptions():
            stmt = (
                select(func.count(func.distinct(_ST.c.song_id)))
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.name == tag_key,
                    _T.c.value == target_value,
                )
            )
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def get_song_tag_edges_for_tags(
        self,
        tag_ids: list[int],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return song-tag edge rows for the given tag ids.

        Each dict contains ``song_id``, ``tag_id``, ``confidence``, and ``source``.
        """
        with map_persistence_exceptions():
            if not tag_ids:
                return []
            stmt = select(
                _ST.c.song_id,
                _ST.c.tag_id,
                _ST.c.confidence,
                _ST.c.source,
            ).where(_ST.c.tag_id.in_(tag_ids))
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [
                {
                    "song_id": r[0],
                    "tag_id": r[1],
                    "confidence": r[2],
                    "source": r[3],
                }
                for r in result.all()
            ]
