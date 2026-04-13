"""Sync Navidrome song inventory to graph-based collections.

Walks Navidrome's album inventory via the Subsonic API, auto-detects the
path prefix mapping from crawled paths vs. Nomarr normalized_paths,
resolves Navidrome file paths to Nomarr library_files, upserts
``navidrome_tracks`` vertices + ``has_nd_id`` edges, captures per-user play
counts as ``has_plays`` edges, and removes orphaned tracks no longer present
in Navidrome.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_query_comp import detect_nd_path_prefix, get_files_by_paths_bulk
from nomarr.components.navidrome.navidrome_graph_comp import (
    bulk_ensure_navidrome_file_links,
    bulk_upsert_navidrome_plays,
    bulk_upsert_navidrome_tracks,
    delete_navidrome_tracks_cascade,
    list_navidrome_track_keys,
)
from nomarr.components.navidrome.subsonic_crawl_comp import crawl_navidrome_songs
from nomarr.helpers.dto.navidrome_dto import NdSyncResult
from nomarr.helpers.time_helper import internal_ms

if TYPE_CHECKING:
    from nomarr.components.navidrome.subsonic_client_comp import SubsonicClient
    from nomarr.components.navidrome.subsonic_crawl_comp import CrawledSong
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_UPSERT_BATCH_SIZE = 500
_PREFIX_SAMPLE_SIZE = 20


def _detect_prefix(songs: list[CrawledSong], db: Database) -> str:
    """Auto-detect the Navidrome path prefix from a sample of crawled songs.

    Tries up to ``_PREFIX_SAMPLE_SIZE`` paths against library_files until one
    matches a ``normalized_path`` suffix.  Returns the detected prefix (e.g.
    ``"/music/"``) or ``""`` if the paths already match without stripping.

    Raises:
        ValueError: If no sample path matches any Nomarr file — library may
            not have been scanned yet.
    """
    sample = [s["nd_path"] for s in songs[:_PREFIX_SAMPLE_SIZE]]
    for nd_path in sample:
        prefix = detect_nd_path_prefix(db, nd_path)
        if prefix is not None:
            logger.info("sync_navidrome: auto-detected path prefix %r", prefix)
            return prefix
    msg = (
        "Could not detect path prefix from Navidrome paths. "
        "Ensure the Nomarr library has been scanned before syncing. "
        f"Sample path: {sample[0] if sample else '(no songs)'}"
    )
    raise ValueError(msg)


def sync_navidrome(
    client: SubsonicClient,
    db: Database,
    user_id: str,
) -> NdSyncResult:
    """Sync Navidrome's song inventory into graph collections.

    Walks all albums via ``getAlbumList2`` (paginated), fetches each album's
    songs via ``getAlbum``, auto-detects the path prefix, resolves Nomarr
    file IDs via ``get_files_by_paths_bulk(db, ...)``, and writes
    to ``navidrome_tracks``, ``has_nd_id``, ``navidrome_playcounts``, and
    ``has_plays`` collections.  Orphan tracks (present in DB but absent from
    Navidrome) are cascade-deleted.

    Args:
        client: Authenticated Subsonic API client.
        db: Database instance.
        user_id: Navidrome user identifier for play count attribution.

    Returns:
        NdSyncResult with sync statistics.

    """
    start_time = internal_ms()

    # Step 1: Crawl all albums and collect song data
    all_songs: list[CrawledSong] = crawl_navidrome_songs(client)

    # Step 2: Auto-detect path prefix and strip it from all ND paths
    nd_prefix = _detect_prefix(all_songs, db)
    remapped_paths = [s["nd_path"].removeprefix(nd_prefix) for s in all_songs]
    path_to_doc = get_files_by_paths_bulk(db, remapped_paths)

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
        tracks_upserted += bulk_upsert_navidrome_tracks(db, nd_ids[i : i + _UPSERT_BATCH_SIZE])

    for i in range(0, len(file_link_mappings), _UPSERT_BATCH_SIZE):
        bulk_ensure_navidrome_file_links(db, file_link_mappings[i : i + _UPSERT_BATCH_SIZE])

    # Step 5: Upsert play count data (wipe-and-rebuild for user)
    play_edges_upserted = bulk_upsert_navidrome_plays(db, user_id, play_edges)

    # Step 6: Orphan cleanup — remove tracks no longer in Navidrome
    all_db_track_keys = list_navidrome_track_keys(db)
    orphan_keys = [k for k in all_db_track_keys if k not in seen_nd_ids]
    orphans_removed = delete_navidrome_tracks_cascade(db, orphan_keys) if orphan_keys else 0
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
