"""Typed query/metadata output carriers for the F song-query boundary.

These are component output contracts (the semantic values ``library_song_query_comp``
returns to its service/workflow/interface consumers), not persistence DTOs and not
row-shaped song documents. Each carrier wraps the semantic domain ``Song`` plus, where
the caller needs it, the ADR-045 tag-derived metadata and/or sealed tag values.

Binding rules (CONTRACTS §3.1 / plan F "Typed carriers F may create or return"):

- No carrier carries ``songs.id``, ``song_id``, ``library_id``, ``folder_id``,
  ``file_id``, a persistence row, a raw payload, or a merged song document.
- ``metadata`` is a metadata-only, read-only mapping whose keys are limited to the
  ADR-045 vocabulary (``artist``, ``album``, ``title``, ``artists``, ``labels``,
  ``genres``, ``year``); absent values are omitted (never injected as ``None``).
  It contains no song/document keys.
- ``extract_canonical_metadata`` may use a metadata-only mapping as its
  implementation value; nothing here returns or accepts a song document.

The typed song identity/locator travels as ``SongIdentity`` (ADR-048) wherever a
consumer needs to re-address the song; the owning ``LibraryIdentity`` + the song's
``normalized_path`` are the natural identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
    from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
    from nomarr.helpers.dto.library_dto import FileTag

# ADR-045 canonical metadata key vocabulary (the only keys a metadata mapping may hold).
CANONICAL_METADATA_KEYS = frozenset({"artist", "album", "title", "artists", "labels", "genres", "year"})

__all__ = [
    "HydratedSong",
    "RecentSong",
    "StateTaggedSong",
    "TagMatchedSong",
    "TaggedSong",
    "TrackSong",
]


@dataclass(frozen=True, slots=True)
class HydratedSong:
    """A semantic song with its ADR-045 tag-derived metadata.

    ``metadata`` is metadata-only (keys limited to the ADR-045 vocabulary) and
    omits absent values; it never contains song/document keys.
    """

    song: Song
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TaggedSong:
    """A semantic song with its ADR-045 metadata and sealed tag values."""

    song: Song
    metadata: Mapping[str, object]
    tags: tuple[FileTag, ...]


@dataclass(frozen=True, slots=True)
class StateTaggedSong:
    """A song (with its typed state candidate) annotated with processed-state membership.

    ``candidate`` carries the semantic ``SongStateCandidate`` for the song; the
    separate ``has_tagged_state`` flag is the folder/state annotation that previously
    was merged onto a row-shaped document.
    """

    candidate: SongStateCandidate
    has_tagged_state: bool


@dataclass(frozen=True, slots=True)
class RecentSong:
    """A recently-active processed song with metadata and its activity timestamp/event."""

    candidate: SongStateCandidate
    metadata: Mapping[str, object]
    activity_at: int
    activity_event: Literal["scanned", "tagged"]


@dataclass(frozen=True, slots=True)
class TagMatchedSong:
    """A semantic song matched by a tag search, with its ADR-045 metadata."""

    song: Song
    metadata: Mapping[str, object]
    matched_tag: TagRef
    distance: float


@dataclass(frozen=True, slots=True)
class TrackSong:
    """A song as a track descriptor for matching/playlist boundaries.

    ``isrc`` is typed derived data; there is no ``id`` field. Owning
    services/interfaces build their transport descriptors from this value.
    """

    song: Song
    metadata: Mapping[str, object]
    isrc: str | None
