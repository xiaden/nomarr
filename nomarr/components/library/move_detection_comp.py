"""Move detection component for library scanning.

Detects file moves by comparing chromaprints between removed and new files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.components.library.library_song_mutation_comp import update_song_path
from nomarr.components.library.library_song_query_comp import find_move_candidate_by_chromaprint
from nomarr.components.library.metadata_extraction_comp import compute_chromaprint_for_file
from nomarr.components.metadata.entity_seeding_comp import _extract_entity_tags, build_song_tag_assignments
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongPathUpdate,
    SongScanUpdate,
)

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence import Database

logger = logging.getLogger(__name__)


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


@dataclass
class MoveDetectionResult:
    """Result of move detection analysis."""

    moves: list[FileMove]
    files_moved_count: int
    chromaprints_computed: int  # For new files without chromaprint
    collisions_detected: int  # Same chromaprint, different duration


_EMPTY_MOVE_RESULT = MoveDetectionResult(
    moves=[],
    files_moved_count=0,
    chromaprints_computed=0,
    collisions_detected=0,
)


def detect_file_moves(
    files_to_remove: list[dict[str, Any]],
    new_file_entries: list[dict[str, Any]],
    library: Library,
    db: Database,
) -> MoveDetectionResult:
    """Detect file moves by comparing chromaprints.

    Computes chromaprints for new files and matches against removed files.
    Only processes files if chromaprints exist in the library (fast-fail).

    Optimizations applied:
    - **Duration pre-filter:** New files whose duration doesn't match any
      removed file (within 1 s tolerance) are skipped entirely, avoiding
      an expensive audio-decode + spectral fingerprint per file.
    - **Early termination:** Once every removed file has been matched, the
      loop stops immediately instead of fingerprinting remaining new files.

    Each detected move is addressed by its **source locator** (ADR-048): the
    owning natural ``library`` and the removed row's canonical
    ``normalized_path``. Rows in ``files_to_remove`` must therefore carry the
    natural source ``normalized_path`` (removed rows sourced from a library
    scan carry it) so a :class:`FileMove` can be built without any row id.

    Args:
        files_to_remove: Files marked for removal (with chromaprint if
            available and their natural ``normalized_path``).
        new_file_entries: Newly discovered file entries from scan.
        library: The natural ``Library`` owning the moved rows (the library
            being scanned).
        db: Database instance for chromaprint computation

    Returns:
        MoveDetectionResult with detected moves and statistics

    """
    # Fast path: No files to analyze
    if not files_to_remove or not new_file_entries:
        return _EMPTY_MOVE_RESULT

    # Fast path: No chromaprints in DB yet, can't do move detection
    has_chromaprints = any(f.get("chromaprint") for f in files_to_remove)
    if not has_chromaprints:
        logger.info(f"No chromaprints found in library - skipping move detection for {len(files_to_remove)} files")
        return _EMPTY_MOVE_RESULT

    # Full move detection
    logger.info(f"Checking {len(new_file_entries)} new files for moves against {len(files_to_remove)} removed files...")

    # Sort removed files by source path for deterministic matching when
    # duplicates exist (no row ids are available for sorting).
    files_to_remove.sort(key=lambda f: f.get("path") or "")

    # Build set of removed-file durations for fast pre-filtering.
    # A new file can only be a move if its duration is within 1 s of some
    # removed file.  Files with unknown duration are never filtered out.
    duration_tolerance = 1.0
    removed_durations: list[float] = [
        f["duration_seconds"] for f in files_to_remove if f.get("duration_seconds") is not None
    ]

    def _duration_could_match(new_dur: float | None) -> bool:
        """Return True when *new_dur* is close to any removed-file duration."""
        if new_dur is None or not removed_durations:
            # Unknown duration → can't rule it out.
            return True
        return any(abs(new_dur - rd) <= duration_tolerance for rd in removed_durations)

    library_identity = LibraryIdentity(name=library.name, root_path=library.root_path)
    moves: list[FileMove] = []
    matched_indices: set[int] = set()
    chromaprints_computed = 0
    collisions_detected = 0
    skipped_by_duration = 0

    total_to_match = sum(1 for f in files_to_remove if f.get("chromaprint"))

    # Match new files against removed files
    for new_file in new_file_entries:
        # Early termination: all removed files matched
        if len(matched_indices) >= total_to_match:
            break

        new_path = new_file["path"]

        # Duration pre-filter: skip expensive chromaprint if duration
        # doesn't match any removed file.
        if not _duration_could_match(new_file.get("duration_seconds")):
            skipped_by_duration += 1
            continue

        # Compute chromaprint for new file
        try:
            library_path_for_audio = build_library_path_from_input(new_path, db)
            if not library_path_for_audio.is_valid():
                continue

            new_chromaprint = compute_chromaprint_for_file(library_path_for_audio)
            chromaprints_computed += 1

            # Check if chromaprint matches any removed file
            for idx, removed_file in enumerate(files_to_remove):
                if idx in matched_indices:
                    continue

                removed_chromaprint = removed_file.get("chromaprint")
                if new_chromaprint and removed_chromaprint and removed_chromaprint == new_chromaprint:
                    # Chromaprint matches - verify duration to catch edge cases
                    removed_duration = removed_file.get("duration_seconds")
                    new_duration = new_file.get("duration_seconds")

                    # Verify duration matches (allow 1 second tolerance)
                    duration_matches = (
                        removed_duration is None
                        or new_duration is None
                        or abs(removed_duration - new_duration) <= duration_tolerance
                    )

                    if duration_matches:
                        # Match confirmed
                        logger.info(f"File moved: {removed_file['path']} → {new_path}")

                        move = FileMove(
                            old_path=removed_file["path"],
                            new_path=new_path,
                            song_identity=SongIdentity(
                                library=library_identity,
                                normalized_path=removed_file["normalized_path"],
                            ),
                            chromaprint=new_chromaprint,
                            old_duration=removed_duration,
                            new_duration=new_duration,
                            new_file_size=new_file["file_size"],
                            new_modified_time=new_file["modified_time"],
                        )
                        moves.append(move)
                        matched_indices.add(idx)
                        break
                    # Chromaprint collision - different songs with same fingerprint
                    collisions_detected += 1
                    logger.warning(
                        f"Chromaprint collision detected: "
                        f"{removed_file['path']} vs {new_path} "
                        f"(duration: {removed_duration}s vs {new_duration}s)",
                    )

        except (OSError, RuntimeError) as e:
            logger.warning("Failed to compute chromaprint for %s: %s", new_path, e)
            continue

    logger.info(
        f"Move detection complete: {len(moves)} moves found, "
        f"{chromaprints_computed} chromaprints computed, "
        f"{skipped_by_duration} skipped by duration pre-filter, "
        f"{collisions_detected} collisions detected",
    )

    return MoveDetectionResult(
        moves=moves,
        files_moved_count=len(moves),
        chromaprints_computed=chromaprints_computed,
        collisions_detected=collisions_detected,
    )


def apply_detected_moves(
    moves: list[FileMove],
    metadata_map: dict[str, dict[str, Any]],
    db: Database,
    library_root: Path,
) -> int:
    """Persist detected file moves to the database.

    For each move:
    1. Persists the move atomically via one complete ``SongPathUpdate`` command
       (source ``SongIdentity`` locator + destination path + full scan data)
       through the mutation-component adapter, which makes exactly one
       move-intent call.
    2. On a successful move, re-seeds entity tags under the *destination*
       ``SongIdentity`` returned by the move intent (after a successful move the
       source locator no longer resolves, so tags cannot be reseeded by the old
       source identity).

    Stale/missing source locators (the move intent returns ``None``) are a
    safe no-op miss: the move is skipped and processing continues to the next
    move (ADR-048 §5). Real persistence errors still propagate and abort on the
    first failure, preserving the historical abort-on-first-persistence-error
    behavior — only the *None* stale-source miss is a skip-and-continue, never a
    raised exception.

    Args:
        moves: Detected moves from :func:`detect_file_moves`
        metadata_map: Map of file_path -> raw metadata dict (from scan)
        db: Database instance
        library_root: Library root path for computing normalized_path

    Returns:
        Number of moves successfully applied

    """
    applied = 0
    for move in moves:
        # Compute normalized_path from new_path relative to library_root
        new_path_obj = Path(move.new_path)
        try:
            relative = new_path_obj.relative_to(library_root)
            computed_normalized_path = relative.as_posix()
        except ValueError:
            # new_path not under library_root; skip normalization (defensive;
            # a detected move's destination is always inside the library).
            computed_normalized_path = None

        command = SongPathUpdate(
            song_identity=move.song_identity,
            new_path=move.new_path,
            scan=SongScanUpdate(
                normalized_path=computed_normalized_path,
                file_size=move.new_file_size,
                modified_time=move.new_modified_time,
                duration_seconds=move.new_duration,
            ),
        )
        destination = update_song_path(db, command)
        if destination is None:
            # Stale/missing source locator: safe no-op miss (ADR-048 §5).
            # Skip-and-continue; the row was not moved and no replacement was
            # fabricated.
            logger.warning(
                "Skipping stale move %s → %s: source locator no longer resolves",
                move.old_path,
                move.new_path,
            )
            continue

        new_metadata = metadata_map.get(move.new_path)
        if new_metadata:
            try:
                entity_tags = _extract_entity_tags(new_metadata)
                # build_song_tag_assignments' int argument is compute-only and is
                # dropped by its flat mapping; pass the existing sentinel (0) as
                # extract_entity_tag_mapping does — no identity migration.
                assignments = build_song_tag_assignments(0, entity_tags)
                if assignments:
                    db.library.replace_song_tags(destination, assignments)
            except RuntimeError as e:
                logger.warning(
                    "Failed to update entities for moved file %s: %s",
                    move.new_path,
                    e,
                )

        applied += 1

    return applied


def detect_file_move_via_db(
    new_file_entry: dict[str, Any],
    library: Library,
    db: Database,
) -> FileMove | None:
    """Check whether ``new_file_entry`` is a moved version of an existing DB file.

    Computes the chromaprint for the new file, then queries the DB for a file
    with the same fingerprint belonging to ``library`` (the natural ``Library``
    domain value).  Used during the final scan pass when there are no in-memory
    ``missing_docs_map`` candidates (e.g. files moved from a folder that
    vanished entirely from disk).

    The detected move carries its **source locator** (ADR-048): a
    ``SongIdentity`` built from ``library``'s natural key and the candidate
    row's canonical ``normalized_path``. No row id or numeric library handle
    crosses this boundary.

    Returns a :class:`FileMove` when a match is found, ``None`` otherwise.
    """
    new_path = new_file_entry["path"]

    try:
        library_path = build_library_path_from_input(new_path, db)
        if not library_path.is_valid():
            return None
        chromaprint = compute_chromaprint_for_file(library_path)
    except (OSError, RuntimeError) as e:
        logger.warning("Failed to compute chromaprint for %s: %s", new_path, e)
        return None

    if not chromaprint:
        return None

    candidate = find_move_candidate_by_chromaprint(db, library, chromaprint)
    if candidate is None:
        return None

    # Verify path actually changed (guard against self-match on re-scan)
    if candidate.get("path") == new_path:
        return None

    # Duration tolerance check
    removed_duration = candidate.get("duration_seconds")
    new_duration = new_file_entry.get("duration_seconds")
    if removed_duration is not None and new_duration is not None and abs(removed_duration - new_duration) > 1.0:
        logger.warning(
            "Chromaprint collision: %s vs %s (duration %ss vs %ss)",
            candidate.get("path"),
            new_path,
            removed_duration,
            new_duration,
        )
        return None

    logger.info("File moved (DB lookup): %s → %s", candidate.get("path"), new_path)
    return FileMove(
        old_path=candidate["path"],
        new_path=new_path,
        song_identity=SongIdentity(
            library=LibraryIdentity(name=library.name, root_path=library.root_path),
            normalized_path=candidate["normalized_path"],
        ),
        chromaprint=chromaprint,
        old_duration=removed_duration,
        new_duration=new_duration,
        new_file_size=new_file_entry["file_size"],
        new_modified_time=new_file_entry["modified_time"],
    )
