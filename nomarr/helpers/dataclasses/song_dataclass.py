"""Song domain dataclass.

ADR-041 domain object for the ``songs`` table, produced by the ``LibraryDb``
persistence facade (and ``AppDb.list_song_docs_in_state``). The facade owns the
DB-row → domain-object mapping; this class has no knowledge of storage shapes
or column names.

Natural domain identity is ``song_id`` — a stable, caller-facing handle for a
library song (not a storage-internal name). All persistence-owned fields are
expressed in domain terms; the class carries no storage-internal identifiers
or table/collection references.

``to_dict()`` is a transitional projection back to the storage-shaped mapping
(``id`` key) used by the downstream component layer, which still consumes song
rows as dictionaries for hydration (title/artist/album derivation) and API
response building. Prefer attribute access where the ``Song`` object is used
directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class Song:
    """A single library song, identified by its ``song_id``.

    Mirrors the columns of the ``songs`` table but renames the storage primary
    key to the domain-facing ``song_id``.
    """

    song_id: int
    library_id: int
    folder_id: int | None
    path: str
    normalized_path: str
    file_size: int
    modified_time: int
    duration_seconds: float | None
    chromaprint: str | None
    needs_tagging: bool
    is_valid: bool
    tagged: bool
    calibration_hash: str | None
    write_claimed_by: str | None
    last_tagged_at: int | None
    scanned_at: int | None
    created_at: int

    def to_dict(self) -> dict[str, Any]:
        """Project this song to the storage-shaped row mapping.

        The ``id`` key is an alias for ``song_id`` so downstream dict consumers
        (hydration, projection) can keep reading ``row["id"]`` unchanged during
        the domain-model transition.
        """
        return {
            "id": self.song_id,
            "library_id": self.library_id,
            "folder_id": self.folder_id,
            "path": self.path,
            "normalized_path": self.normalized_path,
            "file_size": self.file_size,
            "modified_time": self.modified_time,
            "duration_seconds": self.duration_seconds,
            "chromaprint": self.chromaprint,
            "needs_tagging": self.needs_tagging,
            "is_valid": self.is_valid,
            "tagged": self.tagged,
            "calibration_hash": self.calibration_hash,
            "write_claimed_by": self.write_claimed_by,
            "last_tagged_at": self.last_tagged_at,
            "scanned_at": self.scanned_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Song:
        """Build a ``Song`` from a ``SongRow``-shaped mapping.

        Persistence-facade mapper entry point per ADR-041 (the facade mediates;
        the domain class stays storage-agnostic by accepting a plain mapping).
        """
        return cls(
            song_id=row["id"],
            library_id=row["library_id"],
            folder_id=row["folder_id"],
            path=row["path"],
            normalized_path=row["normalized_path"],
            file_size=row["file_size"],
            modified_time=row["modified_time"],
            duration_seconds=row["duration_seconds"],
            chromaprint=row["chromaprint"],
            needs_tagging=bool(row["needs_tagging"]),
            is_valid=bool(row["is_valid"]),
            tagged=bool(row["tagged"]),
            calibration_hash=row["calibration_hash"],
            write_claimed_by=row["write_claimed_by"],
            last_tagged_at=row["last_tagged_at"],
            scanned_at=row["scanned_at"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True, slots=True)
class SongTagMatch:
    """A song returned by a tag search with match metadata."""

    song: Song
    matched_tag: str
    distance: float


__all__ = ["Song", "SongTagMatch"]
