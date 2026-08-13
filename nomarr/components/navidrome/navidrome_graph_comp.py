"""Component-owned graph helpers for Navidrome track and playcount storage.

Updated for PostgreSQL: all methods use ``AppDb`` directly
instead of the removed ``AppLegacyNavidromeDb`` surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto.navidrome_dto import TrackPlayData

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _to_int_file_id(file_id: str | int | None) -> int | None:
    """Coerce a file-ID value to ``int`` or ``None``."""
    if isinstance(file_id, int):
        return file_id
    if isinstance(file_id, str) and file_id.isdigit():
        return int(file_id)
    return None


def upsert_navidrome_track(db: Database, nd_id: str) -> None:
    # The legacy signature only supplied a key; we pass None for the optional fields.
    db.app.upsert_navidrome_track(nd_id, title=None, artist=None, album=None, file_path=None)


def bulk_upsert_navidrome_tracks(db: Database, nd_ids: list[str]) -> int:
    if not nd_ids:
        return 0
    return db.app.bulk_upsert_navidrome_tracks(nd_ids)


def ensure_navidrome_file_link(db: Database, nd_id: str, file_id: int) -> None:
    db.app.map_navidrome_track_to_song(nd_id, file_id)


def bulk_ensure_navidrome_file_links(db: Database, mappings: list[dict[str, str]]) -> int:
    if not mappings:
        return 0
    return db.app.bulk_map_navidrome_tracks(mappings)


def list_navidrome_track_keys(db: Database) -> list[str]:
    return [str(key) for key in db.app.legacy_navidrome.list_nd_track_keys()]


def delete_navidrome_tracks_cascade(db: Database, nd_ids: list[str]) -> int:
    """Cascade-delete Navidrome tracks.

    The PostgreSQL API deletes tracks by library song id, not by nd_id.
    We loop through nd_ids resolving each to a song id first.
    """
    if not nd_ids:
        return 0
    total = 0
    for nd_id in nd_ids:
        file_id = db.app.get_mapped_file_for_navidrome_track(nd_id)
        if file_id is not None:
            total += db.app.delete_navidrome_tracks_for_song(file_id)
    return total


def resolve_navidrome_track_to_file(db: Database, nd_id: str) -> int | None:
    return db.app.get_mapped_file_for_navidrome_track(nd_id)


def resolve_song_to_navidrome_track(db: Database, song_id: int) -> str | None:
    return db.app.resolve_song_to_navidrome_track(song_id)


def bulk_resolve_navidrome_tracks_to_files(db: Database, nd_ids: list[str]) -> dict[str, int]:
    """Resolve multiple Navidrome track ids to library song ids."""
    if not nd_ids:
        return {}
    result: dict[str, int] = {}
    for nd_id in nd_ids:
        file_id = db.app.get_mapped_file_for_navidrome_track(nd_id)
        if file_id is not None:
            result[nd_id] = file_id
    return result


def bulk_resolve_files_to_navidrome_ids(db: Database, song_ids: list[int]) -> dict[int, str]:
    """Resolve multiple library song ids to Navidrome track ids."""
    if not song_ids:
        return {}
    result: dict[int, str] = {}
    for song_id in song_ids:
        nd_id = db.app.resolve_song_to_navidrome_track(song_id)
        if nd_id is not None:
            result[song_id] = nd_id
    return result


def bulk_upsert_navidrome_plays(db: Database, user_id: str, plays: list[dict[str, Any]]) -> int:
    """Record plays for a user.

    The legacy ArangoDB API bulk-upserted a play graph. PostgreSQL records
    individual plays via ``record_navidrome_play``.
    """
    if not plays:
        return 0
    total = 0
    for play in plays:
        nd_id = str(play.get("nd_id", ""))
        if not nd_id:
            continue
        played_at = play.get("played_at")
        if not isinstance(played_at, int):
            continue
        file_id = _to_int_file_id(play.get("file_id"))
        total += db.app.record_navidrome_play(nd_id, user_id, played_at, file_id)
    return total


def _coerce_top_play_rows(rows: list[Any]) -> list[TrackPlayData]:
    return [
        TrackPlayData(
            nd_id=str(row.get("nd_id", row.get("nd_id", ""))),
            # NdPlayRecord is song_id-keyed; map into the wire TrackPlayData.file_id field.
            file_id=_to_int_file_id(row.get("song_id")),
            playcount=int(row.get("playcount", row.get("playcount", 0))),
            last_played=last_played if isinstance((last_played := row.get("last_played")), int) else None,
        )
        for row in rows
    ]


def get_top_navidrome_plays(db: Database, user_id: str, top_n: int) -> list[TrackPlayData]:
    """Return the user's most-played tracks, resolving file_id where a library link exists."""
    if top_n <= 0:
        return []
    rows = db.app.get_top_navidrome_plays(user_id, top_n)
    return _coerce_top_play_rows(cast("list[Any]", rows))
