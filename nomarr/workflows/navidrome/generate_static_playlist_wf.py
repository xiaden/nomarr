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

from nomarr.components.infrastructure.path_comp import build_library_path_from_db, get_library_root
from nomarr.components.navidrome.m3u_comp import build_m3u, save_m3u
from nomarr.helpers.dto.navidrome_dto import StaticPlaylistResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_MAX_TRACKS = 200


def generate_static_playlist_workflow(
    db: Database,
    file_ids: list[str],
    playlist_name: str = "Vector Search Playlist",
    m3u_output_path: str = "",
) -> StaticPlaylistResult:
    """Generate a static M3U playlist from file IDs.

    Resolves file IDs to library metadata (path, artist, title, duration)
    and generates M3U content with relative paths (relative to the library
    root resolved from the file records).

    When *m3u_output_path* is non-empty the M3U file is also written to
    ``{library_root}/{m3u_output_path}/{playlist_name}.m3u``.

    Args:
        db: Database instance for file lookup.
        file_ids: List of library file document IDs (max 200).
        playlist_name: Name for the playlist header.
        m3u_output_path: Sub-directory (relative to library root) for
            server-side M3U output.  Empty string disables file output.

    Returns:
        StaticPlaylistResult with M3U content, track count, missing IDs,
        and optionally the server-side save path.

    Raises:
        ValueError: If file_ids exceeds the 200 track limit.

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
            saved_path=None,
        )

    # Step 1: Resolve file metadata from database
    files = db.library_files.get_files_by_ids_with_tags(file_ids)
    found_ids = {f["_id"] for f in files}
    missing_ids = [fid for fid in file_ids if fid not in found_ids]

    if missing_ids:
        logger.warning(
            "Static playlist: %d of %d file IDs not found",
            len(missing_ids),
            len(file_ids),
        )

    # Step 2: Resolve the library root from the first file
    library_root = ""
    if files:
        first_path = str(files[0].get("path", ""))
        library_path = build_library_path_from_db(first_path, db, check_disk=False)
        root = get_library_root(library_path, db)
        if root is not None:
            library_root = str(root)

    # Step 3: Build M3U content (relative paths)
    m3u_content = build_m3u(playlist_name, files, file_ids, library_root=library_root)

    # Step 4: Server-side save when configured
    saved_path: str | None = None
    if m3u_output_path and library_root:
        saved_path = save_m3u(library_root, m3u_output_path, playlist_name, m3u_content)

    return StaticPlaylistResult(
        playlist_name=playlist_name,
        m3u_content=m3u_content,
        track_count=len(files),
        missing_ids=missing_ids,
        saved_path=saved_path,
    )
