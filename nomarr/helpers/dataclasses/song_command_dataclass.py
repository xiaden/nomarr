"""Typed identities for song-scoped persistence intents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LibraryIdentity:
    """Natural identity of a library used to scope an operation."""

    name: str
    root_path: str | None = None


@dataclass(frozen=True, slots=True)
class SongIdentity:
    """Natural identity of a song within a library."""

    library: LibraryIdentity
    normalized_path: str


@dataclass(frozen=True, slots=True)
class SongPathUpdate:
    song: SongIdentity
    path: str


@dataclass(frozen=True, slots=True)
class SongRemoval:
    song: SongIdentity


@dataclass(frozen=True, slots=True)
class SongScanUpdate:
    song: SongIdentity
    file_size: int
    modified_time: int


@dataclass(frozen=True, slots=True)
class SongSyncResult:
    created: int = 0
    updated: int = 0


@dataclass(frozen=True, slots=True)
class SongUpsertInput:
    song: SongIdentity
    path: str
    file_size: int = 0
    modified_time: int = 0


__all__ = [
    "LibraryIdentity",
    "SongIdentity",
    "SongPathUpdate",
    "SongRemoval",
    "SongScanUpdate",
    "SongSyncResult",
    "SongUpsertInput",
]
