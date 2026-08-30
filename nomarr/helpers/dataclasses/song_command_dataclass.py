"""Typed identities for song-scoped persistence intents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LibraryIdentity:
    """Natural identity of a library used to scope an operation."""

    name: str
    root_path: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("LibraryIdentity.name must not be blank")
        if self.root_path is not None and not self.root_path.strip():
            raise ValueError("LibraryIdentity.root_path must not be blank")


@dataclass(frozen=True, slots=True)
class SongIdentity:
    """Natural identity of a song within a library."""

    library: LibraryIdentity
    normalized_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.library, LibraryIdentity):
            raise TypeError("SongIdentity.library must be a LibraryIdentity")
        if not self.normalized_path.strip():
            raise ValueError("SongIdentity.normalized_path must not be blank")


@dataclass(frozen=True, slots=True)
class SongPathUpdate:
    song_identity: SongIdentity
    new_path: str

    @property
    def song(self) -> SongIdentity:
        return self.song_identity

    @property
    def path(self) -> str:
        return self.new_path


@dataclass(frozen=True, slots=True)
class SongRemoval:
    song_identity: SongIdentity

    @property
    def song(self) -> SongIdentity:
        return self.song_identity


@dataclass(frozen=True, slots=True)
class SongScanUpdate:
    normalized_path: str
    file_size: int
    modified_time: int
    duration_seconds: float | None = None
    scanned_at: int | None = None


@dataclass(frozen=True, slots=True)
class SongSyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0

    @property
    def created(self) -> int:
        return self.added


@dataclass(frozen=True, slots=True)
class SongUpsertInput:
    path: str
    folder_id: int | None = None
    scan: SongScanUpdate | None = None


__all__ = [
    "LibraryIdentity",
    "SongIdentity",
    "SongPathUpdate",
    "SongRemoval",
    "SongScanUpdate",
    "SongSyncResult",
    "SongUpsertInput",
]
