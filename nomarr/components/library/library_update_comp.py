"""Library update component for syncing file metadata and tags to database.

This component handles the database-side operations for keeping the library
in sync with audio file metadata and tags.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def update_library_from_tags(
    db: Database,
    file_path: str,
    metadata: dict[str, Any],
    namespace: str,
    tagged_version: str | None,
    library_id: str | None,
) -> None:
    """
    Update library database with extracted file metadata and tags.

    This is the canonical way to sync a file's tags to the library database,
    used by both the library scanner and the processor after tagging.

    This component function:
    1. Takes pre-extracted metadata from metadata_extraction_comp
    2. Upserts to library_files table
    3. Populates file_tags table with parsed tag values:
       - External tags (from file metadata) with is_nomarr_tag=False
       - Nomarr-generated tags (nom:*) with is_nomarr_tag=True
    4. Optionally marks file as tagged with tagger version
    5. Stores calibration metadata (model_key -> calibration_id mapping)

    Args:
        db: Database instance (must provide library and tags accessors)
        file_path: Absolute path to audio file
        metadata: Pre-extracted metadata dict from extract_metadata()
        namespace: Tag namespace (e.g., "nom")
        tagged_version: Tagger version if file was tagged, None otherwise
        library_id: Optional library ID (will auto-detect if None)

    Returns:
        None (updates database in-place)

    Raises:
        Logs warnings on failure but does not raise exceptions
    """
    try:
        # Determine library_id if not provided
        if library_id is None:
            library = db.libraries.find_library_containing_path(file_path)
            if not library:
                logging.warning(f"[update_library_from_tags] File path not in any library: {file_path}")
                return
            library_id = library["id"]

        # At this point library_id is guaranteed to be int
        assert library_id is not None  # Type narrowing for mypy

        # Get file stats
        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        modified_time = int(file_stat.st_mtime * 1000)

        # Build LibraryPath from file path with validation
        library_path = build_library_path_from_input(file_path, db)
        if not library_path.is_valid():
            logging.warning(
                f"[update_library_from_tags] Invalid path ({library_path.status}): {file_path} - {library_path.reason}"
            )
            return

        # Upsert to library database
        # Note: calibration_hash remains NULL until first recalibration
        db.library_files.upsert_library_file(
            path=library_path,
            library_id=library_id,
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=metadata.get("duration"),
            artist=metadata.get("artist"),
            album=metadata.get("album"),
            title=metadata.get("title"),
        )

        # Get file ID and populate file_tags table
        file_record = db.library_files.get_library_file(file_path)
        if file_record:
            # Parse all_tags (external metadata) and nom_tags (Nomarr-generated)
            all_tags = metadata.get("all_tags", {})
            nom_tags = metadata.get("nom_tags", {})

            # Add genre, year, track_number to all_tags if they exist
            # (these are now stored as tags instead of library_files columns)
            if metadata.get("genre"):
                all_tags["genre"] = metadata["genre"]
            if metadata.get("year"):
                all_tags["year"] = metadata["year"]
            if metadata.get("track_number"):
                all_tags["track_number"] = metadata["track_number"]

            parsed_all_tags = _parse_tag_values(all_tags) if all_tags else {}
            parsed_nom_tags = _parse_tag_values(nom_tags) if nom_tags else {}

            # Insert both sets of tags with appropriate is_nomarr_tag flags
            db.file_tags.upsert_file_tags_mixed(
                str(file_record["id"]),
                external_tags=parsed_all_tags,
                nomarr_tags=parsed_nom_tags,
            )

            # Seed entity vertices and edges from metadata (hybrid graph model)
            # This creates entities (artists, albums, genres, etc.) and edges from raw metadata
            try:
                from nomarr.components.metadata.entity_seeding_comp import seed_song_entities_from_tags
                from nomarr.components.metadata.metadata_cache_comp import rebuild_song_metadata_cache

                # Prepare tags dict for entity seeding
                entity_tags = {
                    "artist": metadata.get("artist"),
                    "artists": metadata.get("artists"),
                    "album": metadata.get("album"),
                    "label": metadata.get("label"),
                    "genre": metadata.get("genre"),
                    "year": metadata.get("year"),
                }

                # Seed entities + edges from raw metadata
                seed_song_entities_from_tags(db, str(file_record["id"]), entity_tags)

                # Rebuild cache from edges (deterministic derived fields)
                rebuild_song_metadata_cache(db, str(file_record["id"]))

                logging.debug(f"[update_library_from_tags] Seeded entities for {file_path}")
            except Exception as entity_error:
                logging.warning(f"[update_library_from_tags] Failed to seed entities: {entity_error}")

        # Mark file as tagged if tagger version provided (called from processor)
        if tagged_version and file_record:
            # Pass file ID (not file_path) to mark_file_tagged
            db.library_files.mark_file_tagged(str(file_record["id"]), tagged_version)

        logging.debug(f"[update_library_from_tags] Updated library for {file_path}")
    except Exception as e:
        logging.warning(f"[update_library_from_tags] Failed to update library for {file_path}: {e}")


def _parse_tag_values(tags: dict[str, Any]) -> dict[str, Any]:
    """
    Parse tag values from strings to appropriate types.

    Pure helper that converts string tag values to their proper types:
    - JSON arrays (e.g., "[\"value1\", \"value2\"]") -> list
    - Floats (e.g., "0.95") -> float
    - Integers (e.g., "120") -> int
    - Everything else -> str

    Handles values that are already typed (passthrough).

    This is used when populating library_tags table with typed values.

    Args:
        tags: Dict of tag_key -> tag_value (strings from file or already typed)

    Returns:
        Dict with parsed values (arrays as lists, numbers as float/int, rest as str)

    Example:
        >>> _parse_tag_values({"tempo": "120", "score": "0.95", "tags": '["pop", "upbeat"]'})
        {"tempo": 120, "score": 0.95, "tags": ["pop", "upbeat"]}
    """
    parsed: dict[str, Any] = {}

    for key, value in tags.items():
        if not value:
            continue

        # If value is already typed (not a string), keep it as-is
        if not isinstance(value, str):
            parsed[key] = value
            continue

        # Try to parse as JSON (for arrays)
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed_value = json.loads(value)
                if isinstance(parsed_value, list):
                    parsed[key] = parsed_value
                    continue
            except json.JSONDecodeError:
                pass

        # Handle semicolon-delimited multi-value tags
        # Some formats (MP3) don't support native multi-value, so tags are stored as "value1; value2; value3"
        # Split these into proper lists for consistent database storage
        if ";" in value:
            parsed[key] = [v.strip() for v in value.split(";") if v.strip()]
            continue

        # Try to parse as float
        try:
            if "." in value:
                parsed[key] = float(value)
                continue
        except ValueError:
            pass

        # Try to parse as int
        try:
            parsed[key] = int(value)
            continue
        except ValueError:
            pass

        # Keep as string
        parsed[key] = value

    return parsed
