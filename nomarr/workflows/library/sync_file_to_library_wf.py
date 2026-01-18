"""Sync file metadata and tags to library database.

Orchestrates library, tagging, and metadata domain operations to keep
the library database in sync with audio file state.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.components.metadata.entity_seeding_comp import seed_song_entities_from_tags
from nomarr.components.metadata.metadata_cache_comp import rebuild_song_metadata_cache
from nomarr.components.tagging.tag_parsing_comp import parse_tag_values

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def sync_file_to_library(
    db: Database,
    file_path: str,
    metadata: dict[str, Any],
    namespace: str,
    tagged_version: str | None,
    library_id: str | None,
) -> None:
    """
    Sync a file's metadata and tags to the library database.

    This is the canonical workflow for syncing file state to the database,
    used by both the library scanner and the processor after tagging.

    Orchestrates:
    1. Library domain: Validate path, upsert library_files record
    2. Tagging domain: Parse and upsert file_tags (external + nomarr tags)
    3. Metadata domain: Seed entity graph and rebuild cache

    Args:
        db: Database instance
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
        # Resolve library_id if not provided
        if library_id is None:
            library = db.libraries.find_library_containing_path(file_path)
            if not library:
                logging.warning(f"[sync_file_to_library] File path not in any library: {file_path}")
                return
            library_id = library["_id"]

        assert library_id is not None  # Type narrowing for mypy

        # --- Library domain: validate and upsert file record ---
        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        modified_time = int(file_stat.st_mtime * 1000)

        library_path = build_library_path_from_input(file_path, db)
        if not library_path.is_valid():
            logging.warning(
                f"[sync_file_to_library] Invalid path ({library_path.status}): {file_path} - {library_path.reason}"
            )
            return

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

        # Get the file record for subsequent operations
        file_record = db.library_files.get_library_file(file_path)
        if not file_record:
            logging.warning(f"[sync_file_to_library] File record not found after upsert: {file_path}")
            return

        file_id = str(file_record["_id"])

        # --- Tagging domain: parse and upsert tags ---
        all_tags = metadata.get("all_tags", {})
        nom_tags = metadata.get("nom_tags", {})

        # Add genre, year, track_number to all_tags if present in metadata
        if metadata.get("genre"):
            all_tags["genre"] = metadata["genre"]
        if metadata.get("year"):
            all_tags["year"] = metadata["year"]
        if metadata.get("track_number"):
            all_tags["track_number"] = metadata["track_number"]

        parsed_all_tags = parse_tag_values(all_tags) if all_tags else {}
        parsed_nom_tags = parse_tag_values(nom_tags) if nom_tags else {}

        db.file_tags.upsert_file_tags_mixed(
            file_id,
            external_tags=parsed_all_tags,
            nomarr_tags=parsed_nom_tags,
        )

        # --- Metadata domain: seed entities and rebuild cache ---
        try:
            entity_tags = {
                "artist": metadata.get("artist"),
                "artists": metadata.get("artists"),
                "album": metadata.get("album"),
                "label": metadata.get("label"),
                "genre": metadata.get("genre"),
                "year": metadata.get("year"),
            }

            seed_song_entities_from_tags(db, file_id, entity_tags)
            rebuild_song_metadata_cache(db, file_id)

            logging.debug(f"[sync_file_to_library] Seeded entities for {file_path}")
        except Exception as entity_error:
            logging.warning(f"[sync_file_to_library] Failed to seed entities: {entity_error}")

        # Mark file as tagged if version provided (called from processor)
        if tagged_version:
            db.library_files.mark_file_tagged(file_id, tagged_version)

        logging.debug(f"[sync_file_to_library] Synced {file_path}")

    except Exception as e:
        logging.warning(f"[sync_file_to_library] Failed to sync {file_path}: {e}")
