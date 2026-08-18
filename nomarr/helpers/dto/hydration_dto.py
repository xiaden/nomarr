"""Typed input contract for the song hydration persistence intent.

``HydrateSongInput`` is a persistence-facing data transfer object that
carries already-prepared values from the extraction layer into the atomic
``db.library.songs.hydrate_song`` / ``hydrate_songs_batch`` intents.

It deliberately contains NO filesystem-extraction or database-row fields:
metadata extraction, tag parsing / ``nom:`` namespace prefixing, canonical
metadata derivation, and filesystem path resolution all happen in components
(never in persistence). Persistence receives already parsed values and
atomically stores them.

Rules: import only from stdlib and ``typing`` (no ``nomarr.*`` imports),
and contain only dataclass/type definitions with no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class HydrateSongInput:
    """A single song's fully-parsed hydration payload.

    This is the complete input to one logical hydration unit of work. The
    persistence facade owns storing all of it atomically and idempotently.

    Attributes:
        song_id: Library song row primary key to hydrate.
        parsed_nom_tags: Mapping of tag name → values for ``nom:``-prefixed
            parsed tags. Values may be strings or numbers.
        entity_tags: Mapping of entity/tag relationship name → values (e.g.
            artist, artists, album, label, genre, year).
        metadata_cache: Computed metadata-cache fields to write onto the song
            row (sorted-array strings such as artist/artists/album/labels/
            genres/year, plus ``_cache_updated_at``).
        duration_seconds: Optional duration to store. Persistence treats this
            as one-shot: it must not overwrite an already-present duration.

    The dataclass is frozen (immutable) and holds no extraction logic or
    database-row state.
    """

    song_id: int
    parsed_nom_tags: Mapping[str, Sequence[str | int | float]]
    entity_tags: Mapping[str, Sequence[str | int | float]]
    metadata_cache: Mapping[str, str | int | float | list[str] | None]
    duration_seconds: float | None = None
