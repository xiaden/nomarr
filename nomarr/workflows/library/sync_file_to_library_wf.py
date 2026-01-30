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
from nomarr.components.tagging.tagging_reader_comp import infer_write_mode_from_tags

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.persistence.db import Database

def sync_file_to_library(db: Database, file_path: str, metadata: dict[str, Any], namespace: str, tagged_version: str | None, library_id: str | None) -> None:
    """Sync a file's metadata and tags to the library database.

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
        if library_id is None:
            library = db.libraries.find_library_containing_path(file_path)
            if not library:
                logger.warning(f"[sync_file_to_library] File path not in any library: {file_path}")
                return
            library_id = library["_id"]
        assert library_id is not None
        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        modified_time = int(file_stat.st_mtime * 1000)
        library_path = build_library_path_from_input(file_path, db)
        if not library_path.is_valid():
            logger.warning(f"[sync_file_to_library] Invalid path ({library_path.status}): {file_path} - {library_path.reason}")
            return
        nom_tags = metadata.get("nom_tags", {})
        has_nomarr_namespace = bool(nom_tags)
        last_written_mode = infer_write_mode_from_tags(set(nom_tags.keys())) if has_nomarr_namespace else None
        db.library_files.upsert_library_file(path=library_path, library_id=library_id, file_size=file_size, modified_time=modified_time, duration_seconds=metadata.get("duration"), artist=metadata.get("artist"), album=metadata.get("album"), title=metadata.get("title"), has_nomarr_namespace=has_nomarr_namespace, last_written_mode=last_written_mode)
        file_record = db.library_files.get_library_file(file_path)
        if not file_record:
            logger.warning(f"[sync_file_to_library] File record not found after upsert: {file_path}")
            return
        file_id = str(file_record["_id"])
        all_tags = metadata.get("all_tags", {})
        nom_tags = metadata.get("nom_tags", {})
        if metadata.get("genre"):
            all_tags["genre"] = metadata["genre"]
        if metadata.get("year"):
            all_tags["year"] = metadata["year"]
        if metadata.get("track_number"):
            all_tags["track_number"] = metadata["track_number"]
        parsed_all_tags = parse_tag_values(all_tags) if all_tags else {}
        parsed_nom_tags = parse_tag_values(nom_tags) if nom_tags else {}
        for rel, values in parsed_all_tags.items():
            db.tags.set_song_tags(file_id, rel, values)
        for rel, values in parsed_nom_tags.items():
            nomarr_rel = f"nom:{rel}" if not rel.startswith("nom:") else rel
            db.tags.set_song_tags(file_id, nomarr_rel, values)
        try:
            entity_tags = {"artist": metadata.get("artist"), "artists": metadata.get("artists"), "album": metadata.get("album"), "label": metadata.get("label"), "genre": metadata.get("genre"), "year": metadata.get("year")}
            seed_song_entities_from_tags(db, file_id, entity_tags)
            rebuild_song_metadata_cache(db, file_id)
            logger.debug(f"[sync_file_to_library] Seeded entities for {file_path}")
        except Exception as entity_error:
            logger.warning(f"[sync_file_to_library] Failed to seed entities: {entity_error}")
        chromaprint = metadata.get("chromaprint")
        if chromaprint:
            db.library_files.set_chromaprint(file_id, chromaprint)
            logger.debug(f"[sync_file_to_library] Stored chromaprint for {file_path}")
        if tagged_version:
            db.library_files.mark_file_tagged(file_id, tagged_version)
        logger.debug(f"[sync_file_to_library] Synced {file_path}")
    except Exception as e:
        logger.warning(f"[sync_file_to_library] Failed to sync {file_path}: {e}")
