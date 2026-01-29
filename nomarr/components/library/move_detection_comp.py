"""Move detection component for library scanning.

Detects file moves by comparing chromaprints between removed and new files.
"""

import logging
from dataclasses import dataclass
from typing import Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.components.library.metadata_extraction_comp import compute_chromaprint_for_file
from nomarr.persistence import Database

logger = logging.getLogger(__name__)


# Component-local DTOs (not promoted to helpers/dto)
@dataclass
class FileMove:
    """Represents a detected file move."""

    old_path: str
    new_path: str
    file_id: str  # DB _id of the moved file
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


def detect_file_moves(
    files_to_remove: list[dict[str, Any]],
    new_file_entries: list[dict[str, Any]],
    db: Database,
) -> MoveDetectionResult:
    """Detect file moves by comparing chromaprints.

    Computes chromaprints for new files and matches against removed files.
    Only processes files if chromaprints exist in the library (fast-fail).

    Args:
        files_to_remove: Files marked for removal (with chromaprint if available)
        new_file_entries: Newly discovered file entries from scan
        db: Database instance for chromaprint computation

    Returns:
        MoveDetectionResult with detected moves and statistics

    """
    # Fast path: No files to analyze
    if not files_to_remove or not new_file_entries:
        return MoveDetectionResult(
            moves=[],
            files_moved_count=0,
            chromaprints_computed=0,
            collisions_detected=0,
        )

    # Fast path: No chromaprints in DB yet, can't do move detection
    has_chromaprints = any(f.get("chromaprint") for f in files_to_remove)
    if not has_chromaprints:
        logger.info(f"No chromaprints found in library - skipping move detection for {len(files_to_remove)} files")
        return MoveDetectionResult(
            moves=[],
            files_moved_count=0,
            chromaprints_computed=0,
            collisions_detected=0,
        )

    # Full move detection
    logger.info(f"Checking {len(new_file_entries)} new files for moves against {len(files_to_remove)} removed files...")

    # Sort removed files by ID for deterministic matching when duplicates exist
    files_to_remove.sort(key=lambda f: f["_id"])

    moves: list[FileMove] = []
    matched_indices: set[int] = set()
    chromaprints_computed = 0
    collisions_detected = 0

    # Match new files against removed files
    for new_file in new_file_entries:
        new_path = new_file["path"]

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
                        removed_duration is None or new_duration is None or abs(removed_duration - new_duration) <= 1.0
                    )

                    if duration_matches:
                        # Match confirmed
                        logger.info(f"File moved: {removed_file['path']} → {new_path}")

                        move = FileMove(
                            old_path=removed_file["path"],
                            new_path=new_path,
                            file_id=removed_file["_id"],
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

        except Exception as e:
            logger.warning(f"Failed to compute chromaprint for {new_path}: {e}")
            continue

    logger.info(
        f"Move detection complete: {len(moves)} moves found, "
        f"{chromaprints_computed} chromaprints computed, "
        f"{collisions_detected} collisions detected",
    )

    return MoveDetectionResult(
        moves=moves,
        files_moved_count=len(moves),
        chromaprints_computed=chromaprints_computed,
        collisions_detected=collisions_detected,
    )
