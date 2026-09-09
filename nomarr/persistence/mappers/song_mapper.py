"""Persistence-private row-to-domain mappers for the ``songs`` table.

Ownership (per ADR-032/ADR-041 and the song-row-mirror contracts ledger):
row-to-domain conversion for songs is owned by the persistence layer. The
:class:`~nomarr.helpers.dataclasses.song_dataclass.Song` application value
deliberately carries no storage identity and exposes no ``from_row``; these
mappers are the sole bridge from a persistence ``SongRow`` to the semantic
value and to its natural locator.

These helpers are persistence-private: only the persistence facades (and sibling
persistence mappers, e.g. ``song_tag_mapper``) import them. They never leak a
``SongRow``, a generated ``id``, a ``library_id``/``folder_id`` foreign key, a
table/column name, or a raw mapping past the persistence boundary. Row fixtures
appear only in persistence mapper/repo tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nomarr.helpers.dto.repo_dto import SongRow

# Keys on an identity-enriched song row that carry the owning library's natural
# identity. A raw ``SongRow`` (which has only ``library_id``) cannot form a
# :class:`SongIdentity` on its own; the owning library natural key is supplied
# by library-scoped facade reads that already resolved it (persistence-internal).
_LIBRARY_NAME_KEY = "library_name"
_ROOT_PATH_KEY = "root_path"


def song_row_to_domain(row: SongRow | Mapping[str, Any]) -> Song:
    """Map a persistence ``SongRow`` to a semantic application ``Song``.

    Preserves nullable values (``duration_seconds``, ``chromaprint``,
    ``calibration_hash``, ``write_claimed_by``, ``last_tagged_at``,
    ``scanned_at``), integer booleans coerced to ``bool`` (``needs_tagging``,
    ``is_valid``, ``tagged``), and integer-millisecond timestamps verbatim.
    Both the absolute physical ``path`` and the library-relative
    ``normalized_path`` are kept: ``normalized_path`` is the locator path
    component (the physical ``path`` is a maintained detail, not global
    identity). Generated/foreign keys on the row (``id``, ``library_id``,
    ``folder_id``) are never copied onto the value object.
    """
    return Song(
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


def song_row_to_identity(row: SongRow | Mapping[str, Any]) -> SongIdentity:
    """Map a library-scoped song row to its natural ``SongIdentity`` locator.

    A raw ``SongRow`` carries only the private ``library_id`` and its own
    ``normalized_path``; a :class:`SongIdentity` requires the owning library's
    natural identity (name, optional root path). Library-scoped facade reads
    resolve that library and pass an identity-enriched row carrying
    ``library_name`` (and optionally ``root_path``); this mapper reads those
    keys. When the library natural identity is absent the mapping fails
    deterministically with a clear ``ValueError`` — never a fabricated lookup,
    never a fallback, and never an exposed storage id. The locator returned is
    the mutable, request-scoped ``SongIdentity`` (ADR-048), not a stable id.
    """
    library_name = row.get(_LIBRARY_NAME_KEY)
    if not library_name or not str(library_name).strip():
        raise ValueError(
            "song_row_to_identity requires a library-scoped row carrying the owning "
            f"library natural identity ({_LIBRARY_NAME_KEY!r}); a bare SongRow has no "
            "library natural key and cannot form a SongIdentity"
        )
    normalized_path = row.get("normalized_path")
    if not normalized_path or not str(normalized_path).strip():
        raise ValueError("song_row_to_identity requires a non-blank normalized_path")
    root_path = row.get(_ROOT_PATH_KEY)
    return SongIdentity(
        library=LibraryIdentity(
            name=str(library_name),
            root_path=str(root_path) if root_path is not None else None,
        ),
        normalized_path=str(normalized_path),
    )


__all__ = ["song_row_to_domain", "song_row_to_identity"]
