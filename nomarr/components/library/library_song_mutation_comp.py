"""Library song mutation helpers extracted from legacy persistence mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.dataclasses.song_command_dataclass import (
    ChromaprintValue,
    LibraryIdentity,
    SongIdentity,
    SongPathUpdate,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.time_helper import now_ms

# Provenance carried by DB-derived chromaprint handles resolved at this inbound
# adapter boundary. Real caller-supplied provenance is a Q3 caller-cutover item.
_CHROMAPRINT_PROVENANCE = "decoder:v1"

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dto import LibraryPath
    from nomarr.persistence.db import Database


def upsert_library_song(
    db: Database,
    path: LibraryPath,
    library: Library,
    file_size: int,
    modified_time: int,
    duration_seconds: float | None = None,
    last_tagged_at: int | None = None,
) -> SongIdentity:
    """Insert or update a library-song row and its ownership/state edges.

    Validates the physical ``LibraryPath`` and composes a typed
    ``SongUpsertInput`` command from the ``Library`` natural value and the
    application metadata. No raw SQL-column row is constructed here and no
    storage timestamp is generated as a persistence payload — scan
    ``scanned_at`` is left to the persistence default. Persistence resolves
    the library identity, maps the row, applies defaults, initializes states,
    and returns the natural ``SongIdentity``.

    Args:
        db: Database instance.
        path: Validated ``LibraryPath`` for the song.
        library: Domain ``Library`` (natural identity) that owns the song.
        file_size: File size in bytes.
        modified_time: File mtime in ms since epoch.
        duration_seconds: Optional audio duration.
        last_tagged_at: Optional wall-clock timestamp of last tag write.

    Raises ValueError if the path is not valid.

    Returns:
        The natural-key ``SongIdentity`` (never a generated integer song id).
    """
    if not path.is_valid():
        msg = f"Cannot upsert invalid path ({path.status}): {path.reason}"
        raise ValueError(msg)

    if library.library_uuid is None:
        raise ValueError(f"Library {library.name!r} has no library_uuid")
    command = SongUpsertInput(
        library=LibraryIdentity(
            library_uuid=library.library_uuid,
            name=library.name,
            root_path=library.root_path,
        ),
        path=str(path.absolute),
        scan=SongScanUpdate(
            normalized_path=str(path.relative),
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=duration_seconds,
        ),
        last_tagged_at=last_tagged_at,
    )
    return db.library.add_song_to_library(command)


def delete_library_song(db: Database, path: str, library: Library) -> None:
    """Delete a library-song document and its edges.

    The song is addressed by its natural ``(library, path)`` identity — the
    composite key the ``songs`` table guarantees unique. The storage primary key
    is never exposed to or interpreted by this component, so a numeric-looking
    path is still treated as a path, never as a database id. No-op when no song
    exists at the path.
    """
    db.library.remove_song_by_path(path, library)


def update_song_path(db: Database, command: SongPathUpdate) -> SongIdentity | None:
    """Atomically move a Song to a new path with its complete scan metadata.

    Component-level adapter over the single public move intent. The caller
    (move detection) constructs one complete ``SongPathUpdate`` addressed by the
    **source locator** ``SongIdentity(library, normalized_path)`` (ADR-048) and
    carrying the destination path plus the full scan data; this adapter forwards
    it in exactly one ``db.library`` move-intent call. It does not resolve
    locators, open transactions, call repositories, or retain the old two-call
    path-plus-scan choreography — persistence owns the single atomic update (all
    fields or none).

    Returns the destination ``SongIdentity`` when the move commits, or ``None``
    when the source locator is stale/missing (a safe no-op miss). After a
    successful move the source locator no longer resolves; callers that reseed
    tags must use the returned destination locator, not the source.
    """
    return db.library.move_library_song(command)


def update_song_modified_time(db: Database, file_key: int, modified_time_ms: int) -> None:
    """Update the stored modified-time after a successful file write.

    Inbound integer-handle adapter (allowlisted Q1): the claim handle is
    resolved to the semantic ``SongIdentity`` exactly once and the write
    delegates to the locator-addressed ``set_modified_time`` intent. The handle
    never propagates past this point. A handle that does not resolve is a
    missing-locator no-op: no write occurs and no error is raised (mirroring the
    facade's ``MISSING_LOCATOR`` outcome).
    """
    song = db.library.resolve_song_identity(file_key)
    if song is None:
        return
    db.library.set_modified_time(song, modified_time_ms)


def bulk_delete_songs(db: Database, paths: list[str], library: Library) -> int:
    """Delete multiple library-song documents by path in one library.

    Songs are addressed by their natural ``(library, path)`` identity; the
    storage primary key is never interpreted by this component. Silently skips
    paths with no matching document. Returns the number deleted.
    """
    if not paths:
        return 0

    resolved = [path for path in paths if db.library.get_song_by_path(path, library) is not None]
    matched_paths = list(dict.fromkeys(resolved))
    if not matched_paths:
        return 0

    for path in matched_paths:
        db.library.remove_song_by_path(path, library)
    return len(matched_paths)


def set_chromaprint(db: Database, song: SongIdentity, chromaprint: str) -> None:
    """Persist a chromaprint fingerprint for one song.

    Inbound integer-handle adapter (allowlisted Q1): the handle is resolved to
    the semantic ``SongIdentity`` exactly once and the write delegates to the
    guarded locator-addressed ``set_chromaprint`` intent.
    ``expected_absent=False`` preserves the prior unconditional-replace behavior
    for DB-derived fingerprints; provenance travels with the value. A handle that
    does not resolve is a missing-locator no-op: no write occurs and no error is
    raised (mirroring the facade's ``MISSING_LOCATOR`` outcome).
    """
    db.library.set_chromaprint(
        song,
        ChromaprintValue(chromaprint, _CHROMAPRINT_PROVENANCE, expected_absent=False),
    )


def update_last_tagged_at(db: Database, song: SongIdentity) -> None:
    """Record the wall-clock time at which a song was tagged.

    Inbound integer-handle adapter (allowlisted Q1): resolves the handle to the
    semantic ``SongIdentity`` once and delegates to ``set_last_tagged``. The
    handle never propagates past this point. A handle that does not resolve is a
    missing-locator no-op: no write occurs and no error is raised (mirroring the
    facade's ``MISSING_LOCATOR`` outcome).
    """
    db.library.set_last_tagged(song, now_ms().value)
