"""Sync file metadata and tags to library database.

Orchestrates library, tagging, and metadata domain operations to keep
the library database in sync with audio file state.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.components.library.library_records_comp import find_library_containing_path
from nomarr.components.library.library_song_mutation_comp import set_chromaprint, upsert_library_song
from nomarr.components.library.song_sync_comp import mark_song_processed, save_song_tags
from nomarr.components.metadata.entity_seeding_comp import build_song_tag_assignments
from nomarr.components.tagging.tag_parsing_comp import parse_tag_values

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.persistence.db import Database


def _sync_tags_and_entities(
    db: Database,
    song: SongIdentity,
    file_path: str,
    metadata: dict[str, Any],
    _namespace: str,
    tagged_version: str | None,
) -> None:
    """Write tags, compute entity tag assignments, and update metadata for a known song.

    Internal helper — assumes the locator is valid. Called by
    sync_file_to_library for both the fast path (locator known) and slow path
    (after upsert).

    Args:
        db: Database instance
        song: Semantic ``SongIdentity`` locator for the file
        file_path: Absolute path (for logging only)
        metadata: Pre-extracted metadata dict
        _namespace: Unused tag namespace (retained for call-site signature stability)
        tagged_version: Tagger version if file was tagged

    """
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

    # Persist all external tags
    save_song_tags(db, song, parsed_all_tags)

    # Persist nomarr-namespaced tags (prefix names with "nom:")
    prefixed_nom_tags = {
        (f"nom:{name}" if not name.startswith("nom:") else name): values for name, values in parsed_nom_tags.items()
    }
    save_song_tags(db, song, prefixed_nom_tags)

    try:
        entity_tags = {
            "artist": metadata.get("artist"),
            "artists": metadata.get("artists"),
            "album": metadata.get("album"),
            "label": metadata.get("label"),
            "genre": metadata.get("genre"),
            "year": metadata.get("year"),
        }
        assignments = build_song_tag_assignments(entity_tags)
        if assignments:
            db.library.replace_song_tags(song, assignments)
        logger.debug(f"[sync_file_to_library] Seeded entities for {file_path}")
    except Exception as entity_error:
        logger.warning(f"[sync_file_to_library] Failed to seed entities: {entity_error}", exc_info=True)

    chromaprint = metadata.get("chromaprint")
    if chromaprint:
        set_chromaprint(db, song, chromaprint)
        logger.debug(f"[sync_file_to_library] Stored chromaprint for {file_path}")

    if tagged_version:
        mark_song_processed(db, song)

    logger.debug(f"[sync_file_to_library] Synced {file_path}")


def sync_file_to_library(
    db: Database,
    file_path: str,
    metadata: dict[str, Any],
    namespace: str,
    tagged_version: str | None,
    library: Library | None,
    song: SongIdentity | None = None,
) -> None:
    """Sync a file's metadata and tags to the library database.

    This is the canonical workflow for syncing file state to the database,
    used by both the library scanner and the processor after tagging.

    Orchestrates:
    1. Library domain: Upsert the song and resolve its ``SongIdentity`` locator
       locator-addressed (fast path takes the supplied locator; slow path goes
       through ``upsert_library_song(path=...)``)
    2. Tagging domain: Parse and upsert file_tags (external + nomarr tags)
    3. Metadata domain: Compute entity tag assignments (``build_song_tag_assignments``)
       and replace them through ``db.library.replace_song_tags`` (compute-only;
       no cache writer or Arango-era entity graph seeding)

    Args:
        db: Database instance
        file_path: Absolute path to audio file
        metadata: Pre-extracted metadata dict from extract_metadata()
        namespace: Tag namespace (e.g., "nom")
        tagged_version: Tagger version if file was tagged, None otherwise
        library: Optional domain ``Library`` (natural identity). When None,
            the owning library is auto-detected from the file path.
        song: Semantic ``SongIdentity`` locator. When provided, skips the
            path-based upsert and syncs the supplied locator directly.

    Returns:
        None (updates database in-place)

    Raises:
        Logs warnings on failure but does not raise exceptions

    """
    try:
        if song is not None:
            # Fast path: we already have the song locator (from worker flow)
            # Skip path-based upsert — the scanner already processed this track
            _sync_tags_and_entities(db, song, file_path, metadata, namespace, tagged_version)
            return

        # Slow path: no track identifier provided, need path-based lookup
        # This path is used by the scanner's initial sync
        if library is None:
            library = find_library_containing_path(db, file_path)
            if not library:
                logger.warning(f"[sync_file_to_library] File path not in any library: {file_path}")
                return

        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        modified_time = int(file_stat.st_mtime * 1000)

        library_path = build_library_path_from_input(file_path, db)
        if not library_path.is_valid():
            logger.warning(
                f"[sync_file_to_library] Invalid path ({library_path.status}): {file_path} - {library_path.reason}",
            )
            return

        identity = upsert_library_song(
            db,
            path=library_path,
            library=library,
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=metadata.get("duration"),
        )

        _sync_tags_and_entities(db, identity, file_path, metadata, namespace, tagged_version)

    except Exception as e:
        logger.warning(f"[sync_file_to_library] Failed to sync {file_path}: {e}", exc_info=True)
