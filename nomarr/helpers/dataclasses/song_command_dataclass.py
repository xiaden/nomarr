"""Song identity and mutation command value objects.

ADR-041 domain objects for the song-domain intent boundary. These types
formalize the natural-key identity and typed write commands that the
``LibrarySongsDb``/``LibraryDb`` intent facades adopt in the facade-correction
phases of ``TASK-song-intent-facade-correction-A`` (ADR-032/041/043):

- Song identity is ``(library natural identity, normalized_path)``; the absolute
  path is a maintained detail, not part of identity. The library component is a
  lightweight ``LibraryIdentity(name, root_path)`` natural reference — never the
  PostgreSQL ``libraries.id`` primary key (ADR-032/041; ``P1-S4`` identity gate).
- Song mutations are expressed as typed intent commands (upsert / scan-update /
  path-update / removal), never arbitrary column-shaped dictionaries.
- The types carry no database identifiers, table metadata, storage keys, or
  row shapes.

Per ASR-0015, ``SongUpsertInput`` composes ``SongScanUpdate`` instead of
redeclaring its fields; there is exactly one authoritative definition of the
scan-metadata command block.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LibraryIdentity:
    """Natural reference to a library, carrying only its natural identity.

    ``(name, root_path)`` is the ADR-041 natural key of a ``Library``. This
    lightweight reference deliberately omits generated storage ids, timestamps,
    and all other row shape so it can be embedded in domain identity without
    leaking persistence details. No generated ``id`` crosses the boundary.
    """

    name: str
    root_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("LibraryIdentity.name must not be blank")
        if not isinstance(self.root_path, str) or not self.root_path.strip():
            raise ValueError("LibraryIdentity.root_path must not be blank")


@dataclass(frozen=True, slots=True)
class SongIdentity:
    """Stable domain identity for one library song.

    The natural key is ``(library natural identity, normalized_path)``. The
    absolute ``path`` is a maintained detail, not part of identity. ``library``
    is a :class:`LibraryIdentity` natural reference; ``normalized_path`` is the
    library-relative canonical normalized path. No storage primary key is
    carried.
    """

    library: LibraryIdentity
    normalized_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.library, LibraryIdentity):
            raise TypeError("SongIdentity.library must be a LibraryIdentity")
        if not isinstance(self.normalized_path, str) or not self.normalized_path.strip():
            raise ValueError("SongIdentity.normalized_path must not be blank")


@dataclass(frozen=True, slots=True)
class SongScanUpdate:
    """Scan/metadata write command shared by song upsert and reconcile.

    Covers the scan-derived mutable metadata fields. ``duration_seconds`` is
    nullable because some formats report no duration at scan time.
    """

    normalized_path: str
    file_size: int
    modified_time: int
    duration_seconds: float | None
    scanned_at: int

    def __post_init__(self) -> None:
        if not isinstance(self.normalized_path, str) or not self.normalized_path.strip():
            raise ValueError("SongScanUpdate.normalized_path must not be blank")
        if not isinstance(self.file_size, int):
            raise TypeError("SongScanUpdate.file_size must be an int")
        if not isinstance(self.modified_time, int):
            raise TypeError("SongScanUpdate.modified_time must be an int")


@dataclass(frozen=True, slots=True)
class SongUpsertInput:
    """Upsert a song for a library from scan discovery.

    Composes a :class:`SongScanUpdate` for the scan-derived metadata and adds
    the absolute path, folder membership, and validity/need flags. Never carries
    ``library_key`` (per the song-domain-repair DD open question Q1).
    """

    path: str
    folder_id: int | None
    scan: SongScanUpdate
    chromaprint: str | None = None
    needs_tagging: bool = True
    is_valid: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("SongUpsertInput.path must not be blank")


@dataclass(frozen=True, slots=True)
class SongPathUpdate:
    """Change a song's absolute path (path-move intent)."""

    song_identity: SongIdentity
    new_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.new_path, str) or not self.new_path.strip():
            raise ValueError("SongPathUpdate.new_path must not be blank")


@dataclass(frozen=True, slots=True)
class SongRemoval:
    """Remove a song identified by its natural key."""

    song_identity: SongIdentity


@dataclass(frozen=True, slots=True)
class SongSyncResult:
    """Domain result of a song reconcile/upsert batch.

    Replaces the storage-shaped ``dict[str, int]`` (``added``/``updated``/
    ``removed``) result at the facade boundary.
    """

    added: int
    updated: int
    removed: int


__all__ = [
    "LibraryIdentity",
    "SongIdentity",
    "SongPathUpdate",
    "SongRemoval",
    "SongScanUpdate",
    "SongSyncResult",
    "SongUpsertInput",
]
