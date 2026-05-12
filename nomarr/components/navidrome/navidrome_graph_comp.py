"""Component-owned graph helpers for Navidrome track and playcount storage."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto.navidrome_dto import TrackPlayData

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _edge_key(left_id: str, right_id: str) -> str:
    """Return a stable edge-document key for one source/target pair."""
    return hashlib.sha256(f"{left_id}:{right_id}".encode()).hexdigest()[:16]


def _build_edge_namespace(db: Database, name: str) -> Any:
    """Return the runtime-wired edge namespace for an edge collection.

    Runtime callers should use ``db.app.*``. This helper remains only as a
    compatibility path for legacy unit tests that still patch edge namespaces
    directly and have not yet been migrated to the sub-facade surface.
    """
    return cast("Any", getattr(db, name))


def _is_dict_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def upsert_navidrome_track(db: Database, nd_id: str) -> None:
    """Ensure one Navidrome track vertex exists."""
    db.app.upsert_nd_track({"_key": nd_id})


def bulk_upsert_navidrome_tracks(db: Database, nd_ids: list[str]) -> int:
    """Ensure all provided Navidrome track vertices exist."""
    if not nd_ids:
        return 0

    return db.app.bulk_upsert_nd_tracks(nd_ids)


def ensure_navidrome_file_link(db: Database, nd_id: str, file_id: str) -> None:
    """Ensure a single Navidrome track → library file edge exists."""
    bulk_ensure_navidrome_file_links(db, [{"nd_id": nd_id, "file_id": file_id}])


def bulk_ensure_navidrome_file_links(db: Database, mappings: list[dict[str, str]]) -> int:
    """Ensure track → file link edges exist for each mapping entry."""
    if not mappings:
        return 0

    return db.app.bulk_ensure_nd_file_links(mappings)


def list_navidrome_track_keys(db: Database) -> list[str]:
    """Return all Navidrome track `_key` values."""
    return [str(key) for key in db.app.list_nd_track_keys()]


def delete_navidrome_tracks_cascade(db: Database, nd_ids: list[str]) -> int:
    """Cascade-delete track vertices and their connected edges.

    Args:
        db: Database instance.
        nd_ids: Navidrome track id strings (bare keys, not ``_id`` paths).
            The function constructs the full ``navidrome_tracks/<id>`` paths internally.

    Returns:
        Number of track vertex documents deleted, or 0 if ``nd_ids`` is empty.
    """
    if not nd_ids:
        return 0

    return db.app.delete_nd_tracks_cascade(nd_ids)


def resolve_navidrome_track_to_file(db: Database, nd_id: str) -> str | None:
    """Resolve one Navidrome track id to a library file `_id`."""
    return db.app.resolve_nd_track_to_file(nd_id)


def resolve_file_to_navidrome_track(db: Database, file_id: str) -> str | None:
    """Resolve one library file `_id` to its Navidrome track key."""
    return db.app.resolve_file_to_nd_track(file_id)


def bulk_resolve_navidrome_tracks_to_files(db: Database, nd_ids: list[str]) -> dict[str, str]:
    """Resolve multiple Navidrome track ids to library file ids."""
    if not nd_ids:
        return {}

    return {str(nd_id): str(file_id) for nd_id, file_id in db.app.bulk_resolve_nd_tracks_to_files(nd_ids).items()}


def bulk_resolve_files_to_navidrome_ids(db: Database, file_ids: list[str]) -> dict[str, str]:
    """Resolve multiple library file ids to Navidrome track ids."""
    if not file_ids:
        return {}

    return {str(file_id): str(nd_id) for file_id, nd_id in db.app.bulk_resolve_files_to_nd_ids(file_ids).items()}


def upsert_navidrome_play(
    db: Database,
    user_id: str,
    nd_id: str,
    playcount: int,
    last_played: int,
) -> None:
    """Upsert one bucketed playcount vertex and its track edge."""
    if playcount < 0:
        return

    db.app.upsert_nd_playcount(user_id, nd_id, playcount, last_played)


def increment_navidrome_play(db: Database, user_id: str, nd_id: str, timestamp_ms: int) -> None:
    """Move one track to the next playcount bucket for the user."""
    db.app.increment_nd_play(user_id, nd_id, timestamp_ms)


def bulk_upsert_navidrome_plays(db: Database, user_id: str, plays: list[dict[str, Any]]) -> int:
    """Replace the user's existing bucketed play graph with the provided payload."""
    return db.app.bulk_upsert_nd_plays(user_id, plays)


def _coerce_top_play_rows(rows: list[dict[str, Any]]) -> list[TrackPlayData]:
    return [
        TrackPlayData(
            nd_id=str(row["nd_id"]),
            file_id=file_id if isinstance((file_id := row.get("file_id")), str) else None,
            playcount=int(row["playcount"]),
            last_played=last_played if isinstance((last_played := row.get("last_played")), int) else None,
        )
        for row in rows
    ]


def get_top_navidrome_plays(db: Database, user_id: str, top_n: int) -> list[TrackPlayData]:
    """Return the user's most-played tracks, resolving ``file_id`` where a library link exists."""
    if top_n <= 0:
        return []

    return _coerce_top_play_rows(db.app.get_top_nd_plays(user_id, top_n))
