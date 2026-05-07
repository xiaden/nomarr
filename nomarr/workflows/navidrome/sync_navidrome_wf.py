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
import unicodedata
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_query_comp import (
    detect_nd_path_prefix,
    get_files_by_paths_bulk,
    get_sample_normalized_path,
)
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


def _normalize_match_path(path: str) -> str:
    """Normalize Navidrome path text for robust library-file matching.

    This keeps matching exact-first, but lets the workflow recover from
    equivalent path representations such as Windows separators or Unicode
    normalization differences in API responses.
    """
    return unicodedata.normalize("NFKC", path).replace("\\", "/")


def _apply_path_prefix_map(nd_path: str, path_prefix_map: list[tuple[str, str]]) -> str:
    """Apply the longest configured Navidrome path-prefix rewrite, if any."""
    for source_prefix, target_prefix in sorted(path_prefix_map, key=lambda pair: len(pair[0]), reverse=True):
        if nd_path == source_prefix:
            return target_prefix
        if nd_path.startswith(source_prefix):
            suffix = nd_path.removeprefix(source_prefix)
            separator = "" if target_prefix.endswith("/") or not suffix or suffix.startswith("/") else "/"
            return f"{target_prefix}{separator}{suffix}"
    return nd_path


def _resolve_song_paths(
    songs: list[CrawledSong],
    db: Database,
    path_prefix_map: list[tuple[str, str]],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Resolve Navidrome song paths using raw, configured, or auto-detected mappings."""
    if not songs:
        return [], {}

    raw_paths = [song["nd_path"] for song in songs]
    best_paths = raw_paths
    best_docs = get_files_by_paths_bulk(db, raw_paths)
    best_label = "raw"
    best_score = sum(1 for path in raw_paths if path in best_docs)

    def consider_candidate(label: str, candidate_paths: list[str]) -> None:
        nonlocal best_docs, best_label, best_paths, best_score

        candidate_docs = get_files_by_paths_bulk(db, candidate_paths)
        candidate_score = sum(1 for path in candidate_paths if path in candidate_docs)
        if candidate_score > best_score:
            best_paths = candidate_paths
            best_docs = candidate_docs
            best_label = label
            best_score = candidate_score

    normalized_raw_paths = [_normalize_match_path(path) for path in raw_paths]
    if normalized_raw_paths != raw_paths:
        consider_candidate("normalized raw", normalized_raw_paths)

    if path_prefix_map and best_score < len(raw_paths):
        mapped_paths = [_apply_path_prefix_map(path, path_prefix_map) for path in raw_paths]
        if mapped_paths != raw_paths:
            consider_candidate("configured prefix map", mapped_paths)

        normalized_mapped_paths = [_normalize_match_path(path) for path in mapped_paths]
        if normalized_mapped_paths != mapped_paths:
            consider_candidate("normalized configured prefix map", normalized_mapped_paths)

    if best_score < len(raw_paths):
        try:
            detected_prefix = _detect_prefix(songs, db)
        except ValueError:
            detected_prefix = None
        if detected_prefix is not None:
            remapped_paths = [_normalize_match_path(path).removeprefix(detected_prefix) for path in raw_paths]
            if remapped_paths != raw_paths and remapped_paths != normalized_raw_paths:
                consider_candidate("auto-detected prefix", remapped_paths)

    if best_score == 0:
        nd_sample = raw_paths[0] if raw_paths else "(no songs)"
        nomarr_sample = get_sample_normalized_path(db) or "(library appears empty — run a scan first)"
        msg = (
            "Could not match Navidrome paths to Nomarr library files. "
            "Ensure the Nomarr library has been scanned, or configure navidrome_path_prefix_map "
            "when Navidrome and Nomarr see the same files under different mount points. "
            f"Navidrome sample path: {nd_sample} | Nomarr sample path: {nomarr_sample}"
        )
        raise ValueError(msg)

    logger.info(
        "sync_navidrome: using %s path resolution (%d/%d matched)",
        best_label,
        best_score,
        len(raw_paths),
    )
    return best_paths, best_docs


def _detect_prefix(songs: list[CrawledSong], db: Database) -> str:
    """Auto-detect the Navidrome path prefix from a sample of crawled songs.

    Tries up to ``_PREFIX_SAMPLE_SIZE`` paths against library_files until one
    matches a ``normalized_path`` suffix.  Returns the detected prefix (e.g.
    ``"/music/"``) or ``""`` if the paths already match without stripping.

    Raises:
        ValueError: If no sample path matches any Nomarr file — library may
            not have been scanned yet.
    """
    sample = [_normalize_match_path(s["nd_path"]) for s in songs[:_PREFIX_SAMPLE_SIZE]]
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
    path_prefix_map: list[tuple[str, str]] | None = None,
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

    # Step 2: Resolve ND paths via raw paths, configured mappings, or auto-detection
    remapped_paths, path_to_doc = _resolve_song_paths(all_songs, db, path_prefix_map or [])

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
