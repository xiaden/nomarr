"""NavidromeRepo — CRUD for Navidrome track, play, and junction tables.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
joins, aggregations, and bulk operations.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.dto.navidrome_repo_dto import NdPlayRecord, NdTrackRecord
from nomarr.persistence.models.navidrome_play import NavidromePlay
from nomarr.persistence.models.navidrome_play_map import NavidromePlayMap
from nomarr.persistence.models.navidrome_track import NavidromeTrack
from nomarr.persistence.models.navidrome_track_map import NavidromeTrackMap

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.ext.asyncio import AsyncSession

_T_TRACK = cast("Table", NavidromeTrack.__table__)
_T_TRACK_MAP = cast("Table", NavidromeTrackMap.__table__)
_T_PLAY = cast("Table", NavidromePlay.__table__)
_T_PLAY_MAP = cast("Table", NavidromePlayMap.__table__)


def _row_to_track_record(row: Row[Any]) -> NdTrackRecord:
    """Convert a SQLAlchemy ``Row`` to a ``NdTrackRecord`` TypedDict."""
    m = row._mapping
    return NdTrackRecord(
        id=m["id"],
        title=m["title"],
        artist=m["artist"],
        album=m["album"],
        file_path=m["file_path"],
        created_at=m["created_at"],
    )


def _row_to_play_record(row: Row[Any]) -> NdPlayRecord:
    """Convert a SQLAlchemy ``Row`` to a ``NdPlayRecord`` TypedDict."""
    m = row._mapping
    return NdPlayRecord(
        nd_id=m["nd_id"],
        file_id=m["file_id"],
        playcount=m["playcount"],
        last_played=m["last_played"],
    )


class NavidromeRepo:
    """Repository for Navidrome track, play, and junction tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── tracks ──────────────────────────────────────────────────

    async def upsert_track(
        self,
        nd_id: str,
        title: str | None,
        artist: str | None,
        album: str | None,
        file_path: str | None,
    ) -> NdTrackRecord:
        """Insert or update a Navidrome track row.

        ``NavidromeTrack`` columns are NOT NULL, so ``None`` values are
        coerced to empty strings at the DB boundary.
        """
        now = int(time.time())
        data = {
            "id": nd_id,
            "title": title or "",
            "artist": artist or "",
            "album": album or "",
            "file_path": file_path or "",
            "created_at": now,
        }
        set_clause = {k: v for k, v in data.items() if k != "id"}
        stmt = (
            pg_insert(_T_TRACK)
            .values(**data)
            .on_conflict_do_update(
                index_elements=["id"],
                set_=set_clause,
            )
            .returning(_T_TRACK)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        row = result.fetchone()
        assert row is not None
        return _row_to_track_record(row)

    async def get_track(self, nd_id: str) -> NdTrackRecord | None:
        """Fetch a single track by its Navidrome ID (string PK)."""
        stmt = select(_T_TRACK).where(_T_TRACK.c.id == nd_id)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return _row_to_track_record(row) if row else None

    async def list_nd_track_keys(self) -> list[str]:
        """Return all Navidrome track IDs."""
        stmt = select(_T_TRACK.c.id)
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    # ── track ↔ file junction ───────────────────────────────────

    async def map_track_to_file(self, nd_id: str, file_id: int) -> None:
        """Insert a track-to-file mapping (ON CONFLICT DO NOTHING)."""
        now = int(time.time())
        stmt = (
            pg_insert(_T_TRACK_MAP)
            .values(
                navidrome_track_id=nd_id,
                file_id=file_id,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["navidrome_track_id", "file_id"])
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def get_mapped_file(self, nd_id: str) -> int | None:
        """Return the file_id mapped to a Navidrome track, or ``None``."""
        stmt = select(_T_TRACK_MAP.c.file_id).where(_T_TRACK_MAP.c.navidrome_track_id == nd_id)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    async def resolve_file_to_nd_track(self, file_id: int) -> str | None:
        """Reverse lookup: return the Navidrome track ID for a file."""
        stmt = select(_T_TRACK_MAP.c.navidrome_track_id).where(_T_TRACK_MAP.c.file_id == file_id)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return row[0] if row else None

    async def bulk_upsert_tracks(self, nd_ids: list[str]) -> int:
        """Batch insert track stubs (ON CONFLICT DO NOTHING).  Returns count."""
        if not nd_ids:
            return 0
        now = int(time.time())
        values = [
            {
                "id": nd_id,
                "title": "",
                "artist": "",
                "album": "",
                "file_path": "",
                "created_at": now,
            }
            for nd_id in nd_ids
        ]
        stmt = pg_insert(_T_TRACK).values(values).on_conflict_do_nothing(index_elements=["id"])
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult.rowcount is int at runtime

    async def bulk_map_tracks(self, mappings: list[dict[str, str]]) -> int:
        """Batch insert track-to-file mappings.  Returns count inserted.

        Each dict in *mappings* must have ``nd_id`` and ``file_id`` keys.
        """
        if not mappings:
            return 0
        now = int(time.time())
        values = [
            {
                "navidrome_track_id": m["nd_id"],
                "file_id": int(m["file_id"]),
                "created_at": now,
            }
            for m in mappings
        ]
        stmt = (
            pg_insert(_T_TRACK_MAP)
            .values(values)
            .on_conflict_do_nothing(index_elements=["navidrome_track_id", "file_id"])
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult.rowcount is int at runtime

    # ── plays ───────────────────────────────────────────────────

    async def record_play(
        self,
        nd_id: str,
        user_id: str | None,
        played_at: int,
        file_id: int | None = None,
    ) -> int:
        """Record a play event and optionally map it to a file.

        Returns the new play row's primary key.
        """
        stmt = (
            pg_insert(_T_PLAY)
            .values(
                navidrome_track_id=nd_id,
                played_at=played_at,
                user_id=user_id,
            )
            .returning(_T_PLAY.c.id)
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        assert row is not None
        play_id: int = row[0]

        if file_id is not None:
            now = int(time.time())
            map_stmt = (
                pg_insert(_T_PLAY_MAP)
                .values(play_id=play_id, file_id=file_id, created_at=now)
                .on_conflict_do_nothing(index_elements=["play_id", "file_id"])
            )
            await self._session.execute(map_stmt)

        await self._session.commit()
        return play_id

    async def get_top_plays(self, user_id: str, top_n: int) -> list[NdPlayRecord]:
        """Return top-played tracks for a user, aggregated via junction tables.

        Joins ``navidrome_plays`` → ``navidrome_play_maps`` to compute
        per-track play counts and most-recent play timestamps.
        """
        np_ = _T_PLAY
        npm = _T_PLAY_MAP
        stmt = (
            select(
                np_.c.navidrome_track_id.label("nd_id"),
                npm.c.file_id,
                func.count().label("playcount"),
                func.max(np_.c.played_at).label("last_played"),
            )
            .select_from(np_.join(npm, np_.c.id == npm.c.play_id))
            .where(np_.c.user_id == user_id)
            .group_by(np_.c.navidrome_track_id, npm.c.file_id)
            .order_by(func.count().desc())
            .limit(top_n)
        )
        result = await self._session.execute(stmt)
        return [_row_to_play_record(r) for r in result.all()]

    async def delete_tracks_for_file(self, file_id: int) -> int:
        """Delete track mappings for a file, then orphaned tracks.

        Returns the number of track-map rows deleted.
        """
        # 1. Collect track IDs that will lose their last mapping
        sel = select(_T_TRACK_MAP.c.navidrome_track_id).where(_T_TRACK_MAP.c.file_id == file_id)
        result = await self._session.execute(sel)
        affected_nd_ids = [r[0] for r in result.all()]

        # 2. Delete the track-map rows for this file
        del_map = delete(_T_TRACK_MAP).where(_T_TRACK_MAP.c.file_id == file_id)
        map_result = await self._session.execute(del_map)
        map_deleted = int(map_result.rowcount)  # type: ignore[attr-defined]  # CursorResult.rowcount is int at runtime

        # 3. Delete tracks that no longer have any mappings
        if affected_nd_ids:
            orphan_check = select(_T_TRACK_MAP.c.navidrome_track_id).where(
                _T_TRACK_MAP.c.navidrome_track_id.in_(affected_nd_ids),
            )
            orphan_result = await self._session.execute(orphan_check)
            still_mapped = {r[0] for r in orphan_result.all()}
            orphans = [nid for nid in affected_nd_ids if nid not in still_mapped]
            if orphans:
                del_tracks = delete(_T_TRACK).where(_T_TRACK.c.id.in_(orphans))
                await self._session.execute(del_tracks)

        await self._session.commit()
        return map_deleted
