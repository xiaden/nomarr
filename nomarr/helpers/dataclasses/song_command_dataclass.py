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
    """Complete atomic move command for a single Song (ADR-048).

    Addressed by the **source locator**: ``song_identity`` is a
    ``SongIdentity(library, normalized_path)`` naming the row to relocate at its
    current library-relative ``normalized_path``. ``song_identity`` is the mutable,
    request-scoped source locator — it is *not* a stable application identity and
    it does *not* name a generated row id. After a successful move the old source
    locator no longer resolves and the returned destination locator becomes
    current; no alias, tombstone, or history mechanism exists (ADR-048 §2).

    ``new_path`` is the mutable destination physical locator and ``scan`` carries
    the complete destination scan data (destination normalized path, file size,
    mtime, duration, validity, scan timestamp). The destination normalized path
    lives in ``scan.normalized_path``; ``song_identity.normalized_path`` is the
    *source* normalized path the locator resolves by. Persistence resolves
    ``(library, source_normalized_path)`` privately and applies every atomic field
    in one in-place transaction or none, so a move can never leave
    path/normalized-path/scan metadata out of sync and never exposes a row id.

    A missing/stale source locator is a miss (``None``); a destination uniqueness
    conflict or injected failure leaves the complete old row unchanged.

    No repository row, generated id, session, transaction, or SQL payload is
    exposed.
    """

    song_identity: SongIdentity
    new_path: str
    scan: SongScanUpdate

    def __post_init__(self) -> None:
        if not isinstance(self.song_identity, SongIdentity):
            raise TypeError("SongPathUpdate.song_identity must be a source SongIdentity (library, normalized_path)")
        if not self.new_path.strip():
            raise ValueError("SongPathUpdate.new_path must not be blank")
        if not isinstance(self.scan, SongScanUpdate):
            raise TypeError("SongPathUpdate.scan must be a SongScanUpdate")
        if self.scan.normalized_path is not None and not self.scan.normalized_path.strip():
            raise ValueError("SongPathUpdate.scan.normalized_path must not be blank")


@dataclass(frozen=True, slots=True)
class SongRemoval:
    song_identity: SongIdentity

    @property
    def song(self) -> SongIdentity:
        return self.song_identity


@dataclass(frozen=True, slots=True)
class SongScanUpdate:
    """Scan snapshot carried by a song persistence intent.

    ``normalized_path`` is ``None`` only when a physical path cannot be expressed
    relative to its library root (a defensive move-detection case); the NOT NULL
    ``songs.normalized_path`` column means persistence owns rejecting an
    unrepresentable destination atomically rather than storing ``None``.
    ``is_valid`` reflects that the scanned file was valid (the move intent always
    records a valid destination; the upsert path maps only its explicit scan
    fields and does not persist this flag, so the column default applies there).
    ``scanned_at`` defaults to ``None`` and is owned by persistence (filled with
    the current time when absent) so components never generate storage
    timestamps as payload.
    """

    normalized_path: str | None
    file_size: int
    modified_time: int
    duration_seconds: float | None = None
    is_valid: bool = True
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
    """Application command to upsert a single song within a library.

    Carries natural library identity (``library``), the physical application
    ``path``, and optional application metadata (``scan``, ``last_tagged_at``).
    It deliberately carries no storage identifier: the current single-song
    payload never set ``folder_id``, and folder assignment is outside this
    correction's scope.
    """

    library: LibraryIdentity
    path: str
    scan: SongScanUpdate | None = None
    last_tagged_at: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.library, LibraryIdentity):
            raise TypeError("SongUpsertInput.library must be a LibraryIdentity")
        if not self.path.strip():
            raise ValueError("SongUpsertInput.path must not be blank")


__all__ = [
    "LibraryIdentity",
    "SongIdentity",
    "SongPathUpdate",
    "SongRemoval",
    "SongScanUpdate",
    "SongSyncResult",
    "SongUpsertInput",
]
