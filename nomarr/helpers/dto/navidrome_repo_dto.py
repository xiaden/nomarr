"""TypedDict DTOs for the NavidromeRepo return types.

These mirror the SQLAlchemy ``NavidromeTrack`` and ``NavidromePlay``
model columns from Part A and provide type-safe return types for
Navidrome repository methods.  Import only from ``typing``.
"""

from __future__ import annotations

from typing import TypedDict


class NdTrackRecord(TypedDict):
    """Single row from the ``navidrome_tracks`` table."""

    id: str
    title: str | None
    artist: str | None
    album: str | None
    file_path: str | None
    created_at: int


class NdPlayRecord(TypedDict):
    """Aggregated play record for a Navidrome track."""

    nd_id: str
    song_id: int | None
    playcount: int
    last_played: int


__all__ = ["NdPlayRecord", "NdTrackRecord"]
