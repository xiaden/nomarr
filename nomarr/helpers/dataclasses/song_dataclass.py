"""Application ``Song`` value object (semantic-only).

ADR-041/ADR-047 application value object: carries only the semantic fields
consumed by the application — the song's physical path and library-relative
normalized path plus its file-metadata, tagging/validity state, calibration
fingerprint, claim, and timing values. It is produced by the ``LibraryDb``
persistence facade through a persistence-owned row mapper
(:func:`nomarr.persistence.mappers.song_mapper.song_row_to_domain`); the class
itself has no knowledge of storage shapes or column names and carries no
persistence identifiers.

Identity is deliberately *not* carried on this value. There is no generated
``songs.id``, no integer ``library_id``/``folder_id``, and no stable application
id. The :class:`Song` value answers "what is this song's state/metadata"; the
mutable, request-scoped *locator* is the separate
:class:`~nomarr.helpers.dataclasses.song_command_dataclass.SongIdentity`
(``SongIdentity(LibraryIdentity, normalized_path)``). ``Song`` is not a locator
and does not wrap one — per ADR-048 no alias, tombstone, wrapper, history, or
stable-id mechanism exists, and the absolute physical ``path`` is not global
identity (it is a maintained physical-path detail alongside the locator's
library-relative ``normalized_path``).

Rows, generated keys, foreign keys, joins, and storage serialization stay
private to the persistence layer. This class exposes no ``from_row`` and no
storage-shaped ``to_dict``; row-to-domain conversion happens only inside
persistence mappers and domain-to-wire projection happens at the interface
boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Song:
    """Semantic application value for a single library song.

    Carries only application-facing song values: the physical ``path`` and the
    library-relative ``normalized_path`` (the locator path component), plus file
    metadata, tagging/validity state, the calibration fingerprint, the write
    claim, and the relevant timestamps. No generated ``songs.id``, no integer
    ``library_id``/``folder_id``, and no stable identity cross into the
    application. The owning song is located by the separate, mutable
    :class:`~nomarr.helpers.dataclasses.song_command_dataclass.SongIdentity`
    locator (``LibraryIdentity`` + ``normalized_path``); library-scoped callers
    pair the ``normalized_path`` on this value with the ``LibraryIdentity`` they
    already hold to address the song.
    """

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


@dataclass(frozen=True, slots=True)
class SongTagMatch:
    """A song returned by a tag search with match metadata."""

    song: Song
    matched_tag: str
    distance: float


__all__ = ["Song", "SongTagMatch"]
