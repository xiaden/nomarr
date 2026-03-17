"""Sync Navidrome song inventory to the navidrome_song_map collection.

Walks Navidrome's album inventory via the Subsonic API, matches file paths
(with configurable prefix remapping) to Nomarr library_files, and upserts
the bidirectional ID mapping into ArangoDB.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypedDict

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.components.navidrome.subsonic_client_comp import SubsonicClient
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_ALBUM_PAGE_SIZE = 500
_UPSERT_BATCH_SIZE = 500
_PROGRESS_LOG_INTERVAL = 100


class SyncResult(TypedDict):
    """Result of a song map sync operation."""

    total_songs: int
    resolved: int
    unresolved: int
    duration_ms: int


def sync_song_map(
    client: SubsonicClient,
    path_prefix_map: list[tuple[str, str]],
    db: Database,
) -> SyncResult:
    """Sync Navidrome's song inventory into the navidrome_song_map collection.

    Walks all albums via ``getAlbumList2`` (paginated), fetches each album's
    songs via ``getAlbum``, applies path prefix remapping, resolves Nomarr
    file_ids via ``db.library_files.get_files_by_paths_bulk()``, and upserts
    mappings into ``db.navidrome_song_map``.

    Args:
        client: Authenticated Subsonic API client.
        path_prefix_map: List of (navidrome_prefix, nomarr_prefix) tuples
            for converting Navidrome file paths to Nomarr normalized_paths.
        db: Database instance.

    Returns:
        SyncResult with total_songs, resolved, unresolved, and duration_ms.
    """
    start_time = now_ms()
    all_songs: list[dict[str, str]] = []

    # Phase 1: Walk all albums and collect (song_id, song_path) pairs
    offset = 0
    album_count = 0
    while True:
        albums = client.get_album_list2("alphabeticalByName", _ALBUM_PAGE_SIZE, offset)
        if not albums:
            break

        for album in albums:
            album_id = album.get("id", "")
            if not album_id:
                continue

            album_detail = client.get_album(album_id)
            songs: list[dict[str, Any]] = album_detail.get("song", [])

            for song in songs:
                song_id = song.get("id", "")
                song_path = song.get("path", "")
                if song_id and song_path:
                    all_songs.append({"nd_id": song_id, "nd_path": song_path})

            album_count += 1
            if album_count % _PROGRESS_LOG_INTERVAL == 0:
                logger.info("sync_song_map: Processed %d albums (%d songs so far)", album_count, len(all_songs))

        offset += len(albums)

    logger.info("sync_song_map: Collected %d songs from %d albums", len(all_songs), album_count)

    # Phase 2: Remap paths and resolve to Nomarr file_ids
    remapped_paths: list[str] = []
    for song in all_songs:
        remapped = _remap_path(song["nd_path"], path_prefix_map)
        remapped_paths.append(remapped)

    # Batch resolve all paths at once
    path_to_doc = db.library_files.get_files_by_paths_bulk(remapped_paths)

    # Phase 3: Build mappings and upsert in batches
    mappings: list[dict[str, str]] = []
    unresolved_count = 0

    for song, remapped_path in zip(all_songs, remapped_paths, strict=True):
        doc = path_to_doc.get(remapped_path)
        if doc:
            mappings.append({
                "nd_id": song["nd_id"],
                "file_id": doc["_id"],
                "nd_path": song["nd_path"],
            })
        else:
            unresolved_count += 1

    # Upsert in chunks
    total_upserted = 0
    for i in range(0, len(mappings), _UPSERT_BATCH_SIZE):
        batch = mappings[i : i + _UPSERT_BATCH_SIZE]
        total_upserted += db.navidrome_song_map.upsert_batch(batch)

    duration = now_ms().value - start_time.value

    if unresolved_count > 0:
        logger.warning(
            "sync_song_map: %d/%d songs could not be resolved to Nomarr files",
            unresolved_count,
            len(all_songs),
        )

    logger.info(
        "sync_song_map: Complete. %d resolved, %d unresolved, %dms",
        total_upserted,
        unresolved_count,
        duration,
    )

    return SyncResult(
        total_songs=len(all_songs),
        resolved=total_upserted,
        unresolved=unresolved_count,
        duration_ms=duration,
    )


def _remap_path(nd_path: str, prefix_map: list[tuple[str, str]]) -> str:
    """Apply path prefix remapping from Navidrome to Nomarr format.

    Tries each (navidrome_prefix, nomarr_prefix) pair in order.
    Returns the original path unchanged if no prefix matches.
    """
    for nd_prefix, nomarr_prefix in prefix_map:
        if nd_path.startswith(nd_prefix):
            return nomarr_prefix + nd_path[len(nd_prefix) :]
    return nd_path
