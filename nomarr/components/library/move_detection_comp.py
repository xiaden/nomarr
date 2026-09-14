"""Move detection component for library scanning.

Detects file moves by matching a newly discovered file's chromaprint against
bounded, library-scoped persisted candidates. Matching is persistence-backed and
per-file (never a whole-library candidate set), so a library-root/mount remap
does not materialize O(library-size) Python objects or run O(N²) comparisons.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.components.library.library_song_mutation_comp import update_song_path
from nomarr.components.library.library_song_query_comp import find_move_candidates_by_chromaprint
from nomarr.components.library.metadata_extraction_comp import compute_chromaprint_for_file
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongPathUpdate,
    SongScanUpdate,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.persistence import Database

logger = logging.getLogger(__name__)

_DURATION_TOLERANCE_SECONDS = 1.0


def _library_identity(library: Library) -> LibraryIdentity:
    """Resolve a domain ``Library`` value to its immutable ``LibraryIdentity`` locator."""
    if library.library_uuid is None:
        raise ValueError(f"Library {library.name!r} has no library_uuid")
    return LibraryIdentity(
        library_uuid=library.library_uuid,
        name=library.name,
        root_path=library.root_path,
    )


def song_identity_for(library: Library, normalized_path: str) -> SongIdentity:
    """Build the ``SongIdentity`` source locator for a library-relative path (ADR-048)."""
    return SongIdentity(library=_library_identity(library), normalized_path=normalized_path)


# Component-local DTOs (not promoted to helpers/dto)
@dataclass
class FileMove:
    """Represents a detected file move.

    ``song_identity`` is the **source locator** of the moved row
    (``SongIdentity(library, normalized_path)``; ADR-048) — the mutable,
    request-scoped identity the move is addressed by. It is *not* a stable
    application id and names no generated row id; detection builds it from the
    owning library's natural key and the source row's canonical normalized path.
    """

    old_path: str
    new_path: str
    song_identity: SongIdentity
    chromaprint: str
    old_duration: float | None
    new_duration: float | None
    new_file_size: int
    new_modified_time: int


def relocate_song(
    db: Database,
    song_identity: SongIdentity,
    *,
    new_path: str,
    normalized_path: str,
    file_size: int,
    modified_time: int,
    duration_seconds: float | None,
) -> bool:
    """Build one complete ``SongPathUpdate`` and apply it in place; True when it commits.

    The command carries the destination physical path plus the complete
    destination scan snapshot (normalized path, size, mtime, duration); the
    default ``is_valid``/``scanned_at`` semantics are unchanged from the prior
    move-application path. Persistence owns the single atomic in-place update, so
    the existing row and its tags/states/vectors/ML associations are preserved.
    A stale/missing source locator is a safe no-op miss (``False``).
    """
    command = SongPathUpdate(
        song_identity=song_identity,
        new_path=new_path,
        scan=SongScanUpdate(
            normalized_path=normalized_path,
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=duration_seconds,
        ),
    )
    return update_song_path(db, command) is not None


def detect_move_for_new_file(
    new_file_entry: dict[str, Any],
    library: Library,
    db: Database,
    *,
    source_present: Callable[[Song], bool],
) -> FileMove | None:
    """Detect whether a newly discovered file is a relocation of an absent row.

    Computes the new file's chromaprint and looks up a bounded, library-scoped
    set of persisted candidates sharing that (non-unique) fingerprint. A
    candidate is a valid source only when it is not the new file itself, is not
    the new entry's own locator, is within the 1 s duration tolerance when both
    durations are known, and its source is genuinely absent per
    ``source_present``. Exactly one surviving candidate yields a :class:`FileMove`
    addressed by that candidate's source ``SongIdentity``; zero yields ``None``,
    and more than one logs an ambiguous-relocation warning and yields ``None``
    (never an arbitrary pick). A live duplicate/copy is never turned into a move.
    """
    new_path = new_file_entry["path"]
    try:
        library_path = build_library_path_from_input(new_path, db)
        if not library_path.is_valid():
            logger.warning("Cannot compute chromaprint for %s: %s", new_path, library_path.reason)
            return None
        chromaprint = compute_chromaprint_for_file(library_path)
    except (OSError, RuntimeError) as e:
        logger.warning("Failed to compute chromaprint for %s: %s", new_path, e)
        return None

    if not chromaprint:
        logger.warning("Empty chromaprint for %s; skipping move detection", new_path)
        return None

    candidate_matches = find_move_candidates_by_chromaprint(db, library, chromaprint)
    if not candidate_matches.complete:
        logger.warning("Refusing move detection for truncated chromaprint candidates: %s", new_path)
        return None
    candidates = candidate_matches.songs
    new_duration = new_file_entry.get("duration_seconds")
    new_normalized_path = new_file_entry.get("normalized_path")

    survivors: list[Song] = []
    for candidate in candidates:
        if candidate.path == new_path:
            continue
        if new_normalized_path is not None and candidate.normalized_path == new_normalized_path:
            continue

        candidate_duration = candidate.duration_seconds
        if (
            candidate_duration is not None
            and new_duration is not None
            and abs(candidate_duration - new_duration) > _DURATION_TOLERANCE_SECONDS
        ):
            logger.warning(
                "Chromaprint collision: %s vs %s (duration %ss vs %ss)",
                candidate.path,
                new_path,
                candidate_duration,
                new_duration,
            )
            continue

        if source_present(candidate):
            continue
        survivors.append(candidate)

    if not survivors:
        return None
    if len(survivors) > 1:
        logger.warning(
            "Ambiguous relocation for %s: %d absent chromaprint candidates (%s)",
            new_path,
            len(survivors),
            ", ".join(sorted(candidate.path for candidate in survivors)),
        )
        return None

    candidate = survivors[0]
    logger.info("File moved: %s → %s", candidate.path, new_path)
    return FileMove(
        old_path=candidate.path,
        new_path=new_path,
        song_identity=song_identity_for(library, candidate.normalized_path),
        chromaprint=chromaprint,
        old_duration=candidate.duration_seconds,
        new_duration=new_duration if new_duration is not None else candidate.duration_seconds,
        new_file_size=new_file_entry["file_size"],
        new_modified_time=new_file_entry["modified_time"],
    )
