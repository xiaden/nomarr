"""Sync Navidrome song inventory to graph-based collections.

Walks Navidrome's album inventory via the Subsonic API, matches file paths
(with configurable prefix remapping) to Nomarr library_files, upserts
``navidrome_tracks`` vertices + ``has_nd_id`` edges, captures per-user play
counts as ``has_plays`` edges, and removes orphaned tracks no longer present
in Navidrome.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.navidrome.subsonic_crawl_comp import crawl_navidrome_songs, remap_path
from nomarr.helpers.dto.navidrome_dto import NdSyncResult
from nomarr.helpers.time_helper import internal_ms

if TYPE_CHECKING:
    from nomarr.components.navidrome.subsonic_client_comp import SubsonicClient
    from nomarr.components.navidrome.subsonic_crawl_comp import CrawledSong
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_UPSERT_BATCH_SIZE = 500


def sync_navidrome(
    client: SubsonicClient,
    path_prefix_map: list[tuple[str, str]],
    db: Database,
    user_id: str,
) -> NdSyncResult:
    """Sync Navidrome's song inventory into graph collections.

    Walks all albums via ``getAlbumList2`` (paginated), fetches each album's
    songs via ``getAlbum``, applies path prefix remapping, resolves Nomarr
    file IDs via ``db.library_files.get_files_by_paths_bulk()``, and writes
    to ``navidrome_tracks``, ``has_nd_id``, ``navidrome_playcounts``, and
    ``has_plays`` collections.  Orphan tracks (present in DB but absent from
    Navidrome) are cascade-deleted.

    Args:
        client: Authenticated Subsonic API client.
        path_prefix_map: List of (navidrome_prefix, nomarr_prefix) tuples
            for converting Navidrome file paths to Nomarr normalized_paths.
        db: Database instance.
        user_id: Navidrome user identifier for play count attribution.

    Returns:
        NdSyncResult with sync statistics.

    """
    start_time = internal_ms()

    # Step 1: Crawl all albums and collect song data
    all_songs: list[CrawledSong] = crawl_navidrome_songs(client)

    # Step 2: Remap paths and resolve to Nomarr file IDs
    remapped_paths = [remap_path(s["nd_path"], path_prefix_map) for s in all_songs]
    path_to_doc = db.library_files.get_files_by_paths_bulk(remapped_paths)

    # Step 3: Build resolved mappings and play edge data
    nd_ids: list[str] = []
    file_link_mappings: list[dict[str, str]] = []
    play_edges: list[dict[str, Any]] = []
    seen_nd_ids: set[str] = set()
    unresolved_count = 0

    for song, remapped_path in zip(all_songs, remapped_paths, strict=True):
        nd_id: str = song["nd_id"]
        nd_ids.append(nd_id)
        seen_nd_ids.add(nd_id)

        doc = path_to_doc.get(remapped_path)
        if doc:
            file_link_mappings.append({"nd_id": nd_id, "file_id": doc["_id"]})
        else:
            unresolved_count += 1

        if song["play_count"] > 0:
            play_edges.append(
                {
                    "nd_id": nd_id,
                    "playcount": song["play_count"],
                    "last_played": song["last_played_ms"],
                }
            )

    # Step 4: Upsert track vertices and file link edges (batched)
    tracks_upserted = 0
    for i in range(0, len(nd_ids), _UPSERT_BATCH_SIZE):
        tracks_upserted += db.navidrome_tracks.bulk_upsert_tracks(nd_ids[i : i + _UPSERT_BATCH_SIZE])

    for i in range(0, len(file_link_mappings), _UPSERT_BATCH_SIZE):
        db.navidrome_tracks.bulk_ensure_file_links(file_link_mappings[i : i + _UPSERT_BATCH_SIZE])

    # Step 5: Upsert play count data (wipe-and-rebuild for user)
    play_edges_upserted = db.navidrome_playcounts.bulk_upsert_plays(user_id, play_edges)

    # Step 6: Orphan cleanup — remove tracks no longer in Navidrome
    all_db_track_keys = db.navidrome_tracks.get_all_track_keys()
    orphan_keys = [k for k in all_db_track_keys if k not in seen_nd_ids]
    orphans_removed = db.navidrome_tracks.delete_tracks_cascade(orphan_keys) if orphan_keys else 0
    if orphans_removed:
        logger.info("sync_navidrome: Removed %d orphan tracks", orphans_removed)

    duration = internal_ms().value - start_time.value

    if unresolved_count > 0:
        logger.warning(
            "sync_navidrome: %d/%d songs could not be resolved to Nomarr files",
            unresolved_count,
            len(all_songs),
        )

    logger.info(
        "sync_navidrome: Complete. %d tracks, %d resolved, %d play edges, %d orphans removed, %dms",
        tracks_upserted,
        len(file_link_mappings),
        play_edges_upserted,
        orphans_removed,
        duration,
    )

    return NdSyncResult(
        total_songs=len(all_songs),
        resolved=len(file_link_mappings),
        unresolved=unresolved_count,
        tracks_upserted=tracks_upserted,
        play_edges_upserted=play_edges_upserted,
        orphans_removed=orphans_removed,
        duration_ms=duration,
    )
