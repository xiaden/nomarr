"""Generate static M3U playlist from a list of file IDs.

This workflow accepts a list of library file document IDs,
resolves their paths and metadata from the database, and
generates M3U playlist content suitable for Navidrome import.

Unlike smart playlists (.nsp) which are rule-based, this produces
a fixed, static playlist of specific tracks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.helpers.dto.navidrome_dto import StaticPlaylistResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_MAX_TRACKS = 200


def generate_static_playlist_workflow(
    db: Database,
    file_ids: list[str],
    playlist_name: str = "Vector Search Playlist",
) -> StaticPlaylistResult:
    """Generate a static M3U playlist from file IDs.

    Resolves file IDs to library metadata (path, artist, title, duration)
    and generates M3U content with #EXTM3U header and #EXTINF entries.

    Args:
        db: Database instance for file lookup
        file_ids: List of library file document IDs (max 200)
        playlist_name: Name for the playlist header

    Returns:
        StaticPlaylistResult with M3U content, track count, and any missing IDs

    Raises:
        ValueError: If file_ids exceeds the 200 track limit

    """
    if len(file_ids) > _MAX_TRACKS:
        msg = f"Cannot generate playlist with {len(file_ids)} tracks (max {_MAX_TRACKS})"
        raise ValueError(msg)

    if not file_ids:
        return StaticPlaylistResult(
            playlist_name=playlist_name,
            m3u_content="",
            track_count=0,
            missing_ids=[],
        )

    # Resolve file metadata from database
    files = db.library_files.get_files_by_ids_with_tags(file_ids)
    found_ids = {f["_id"] for f in files}
    missing_ids = [fid for fid in file_ids if fid not in found_ids]

    if missing_ids:
        logger.warning(
            "Static playlist: %d of %d file IDs not found",
            len(missing_ids),
            len(file_ids),
        )

    # Build M3U content
    m3u_content = _build_m3u(playlist_name, files, file_ids)

    return StaticPlaylistResult(
        playlist_name=playlist_name,
        m3u_content=m3u_content,
        track_count=len(files),
        missing_ids=missing_ids,
    )


def _build_m3u(
    playlist_name: str,
    files: list[dict[str, object]],
    ordered_ids: list[str],
) -> str:
    """Build M3U playlist content preserving the order of requested IDs.

    Args:
        playlist_name: Playlist name for header
        files: File dicts from database with metadata
        ordered_ids: Original file ID order to preserve

    Returns:
        M3U file content as string

    """
    # Index files by _id for ordered output
    files_by_id: dict[str, dict[str, object]] = {str(f["_id"]): f for f in files}

    lines = [
        "#EXTM3U",
        f"#PLAYLIST:{playlist_name}",
        "",
    ]

    for fid in ordered_ids:
        file_doc = files_by_id.get(fid)
        if file_doc is None:
            continue

        path = str(file_doc.get("path", ""))
        artist = str(file_doc.get("artist", "Unknown"))
        title = str(file_doc.get("title", "")) or path.rsplit("/", 1)[-1]
        duration_raw = file_doc.get("duration_seconds")
        duration_s = int(float(str(duration_raw))) if duration_raw is not None else -1

        lines.append(f"#EXTINF:{duration_s},{artist} - {title}")
        lines.append(path)

    return "\n".join(lines) + "\n"
