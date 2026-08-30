"""Persistence-owned mappers for the song-tag facade surface.

Ownership (per ADR-032/ADR-041 and the song-domain-repair contracts ledger):
row-to-domain and domain-to-repository mapping for tag/song-tag operations is
owned by the persistence layer. The canonical ``tag_mapper`` deliberately drops
namespace/provenance/confidence when projecting the aggregate ``Tags`` value
object, so it is NOT used for ``SongTagAssignment``. Assignment mapping lives
here and PRESERVES the independent ``namespace`` column plus ``confidence`` /
``source`` provenance (per the ledger's "Domain values and ownership" note and
the ``namespace == "nom"`` and write-restriction semantics).

These helpers are persistence-private: only the persistence facades import
them. They import helpers DTOs/dataclasses (never repositories) and keep the
facade boundary free of ``TagRow`` / ``SongRow`` / raw mapping projections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.song_dataclass import Song, SongTagMatch
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    SongTagAssignment,
    TagRef,
    TagUsage,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity


def tag_identity_from_row(row: Mapping[str, Any]) -> TagRef:
    """Map a ``TagRow``/batch row mapping to a domain ``TagRef``.

    Preserves the independent ``namespace`` column. ``value`` is coerced to a
    string because tag values persist as strings in storage.
    """
    return TagRef(
        name=row["name"],
        value=str(row["value"]),
        namespace=row.get("namespace", ""),
    )


def song_tag_assignment_from_row(
    row: Mapping[str, Any],
    *,
    song: SongIdentity | None = None,
) -> SongTagAssignment:
    """Map a per-song ``TagRow`` to a domain ``SongTagAssignment``.

    ``song`` is populated by callers that know the owning song identity; it is
    left unset (``None``) for flat reads whose repository primitive does not
    attribute each assignment back to a song.
    """
    return SongTagAssignment(
        name=row["name"],
        value=str(row["value"]),
        namespace=row.get("namespace", ""),
        confidence=(float(row["confidence"]) if row.get("confidence") is not None else 1.0),
        source=row.get("source") or "nomarr",
        song=song,
    )


def song_tag_assignment_from_batch_row(
    row: Mapping[str, Any],
    song: SongIdentity,
) -> SongTagAssignment:
    """Map a batch song-tag row (``get_tags_for_songs_batch`` shape) to a domain assignment.

    The batch row uses ``tag_name``/``tag_value`` keys and the caller supplies
    the owning :class:`SongIdentity` (the batch row carries only a storage
    ``song_id``).
    """
    return SongTagAssignment(
        name=row["tag_name"],
        value=str(row["tag_value"]),
        namespace=row.get("namespace", ""),
        confidence=(float(row["confidence"]) if row.get("confidence") is not None else 1.0),
        source=row.get("source") or "nomarr",
        song=song,
    )


def song_from_row(row: Mapping[str, Any]) -> Song:
    """Map a ``SongRow`` mapping to a domain ``Song``.

    Delegates to ``Song.from_row`` (the domain class' own storage-agnostic
    projection) so facades never reach into song row shapes directly.
    """
    return Song.from_row(row)


def song_tag_match_from_row(row: Mapping[str, Any]) -> SongTagMatch:
    """Map a numeric tag-search result row to a domain ``SongTagMatch``."""
    return SongTagMatch(
        song=Song.from_row(row),
        matched_tag=str(row["matched_tag"]),
        distance=float(row["distance"]),
    )


def tag_usage_from_row(row: Mapping[str, Any]) -> TagUsage:
    """Map a tag-with-count row to a domain ``TagUsage``.

    The storage-shaped projection may include an ``id`` (and other tag
    metadata); only the natural identity and the usage count cross the boundary.
    """
    return TagUsage(
        identity=TagRef(
            name=row["name"],
            value=str(row["value"]),
            namespace=row.get("namespace", ""),
        ),
        song_count=int(row["song_count"]),
    )


__all__ = [
    "song_from_row",
    "song_tag_assignment_from_batch_row",
    "song_tag_assignment_from_row",
    "song_tag_match_from_row",
    "tag_identity_from_row",
    "tag_usage_from_row",
]
