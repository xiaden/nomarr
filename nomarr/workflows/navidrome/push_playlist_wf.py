"""Push playlist to Navidrome via Subsonic API.

Workflow that resolves Nomarr file IDs to Navidrome song IDs and creates
or replaces a playlist on the Navidrome server.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.helpers.dto.navidrome_dto import PushPlaylistResult

if TYPE_CHECKING:
    from nomarr.components.navidrome.subsonic_client_comp import SubsonicClient
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def push_playlist(
    db: Database,
    client: SubsonicClient,
    playlist_name: str,
    file_ids: list[str],
) -> PushPlaylistResult:
    """Push a playlist to Navidrome via the Subsonic API.

    Resolves Nomarr file IDs to Navidrome song IDs, finds an existing playlist
    by name (case-insensitive), and creates or replaces it.

    Args:
        db: Database instance for song map lookups.
        client: Authenticated Subsonic API client.
        playlist_name: Name for the Navidrome playlist.
        file_ids: List of Nomarr library_files document IDs.

    Returns:
        PushPlaylistResult with resolved/unresolved counts and playlist ID.

    """
    # 1. Resolve Nomarr file_ids to Navidrome song IDs.
    id_map = db.navidrome_tracks.bulk_resolve_files_to_nd(file_ids)
    resolved_ids = [id_map[fid] for fid in file_ids if fid in id_map]
    unresolved_count = len(file_ids) - len(resolved_ids)

    if unresolved_count > 0:
        unresolved = [fid for fid in file_ids if fid not in id_map]
        logger.warning(
            "push_playlist: %d/%d file IDs have no Navidrome mapping: %s",
            unresolved_count,
            len(file_ids),
            unresolved[:10],
        )

    if not resolved_ids:
        logger.warning("push_playlist: no resolvable file IDs, skipping push")
        return PushPlaylistResult(
            resolved_count=0,
            unresolved_count=unresolved_count,
            playlist_id="",
        )

    # 2. Find existing playlist by name (case-insensitive match).
    existing_id: str | None = None
    playlists = client.get_playlists()
    name_lower = playlist_name.lower()
    for pl in playlists:
        if pl.get("name", "").lower() == name_lower:
            existing_id = pl.get("id")
            break

    # 3. Create or replace the playlist.
    resp = client.create_or_replace_playlist(
        name=playlist_name,
        song_ids=resolved_ids,
        playlist_id=existing_id,
    )

    # Extract playlist ID from response.
    playlist_id = ""
    playlist_data = resp.get("playlist", {})
    if isinstance(playlist_data, dict):
        playlist_id = playlist_data.get("id", "")

    action = "replaced" if existing_id else "created"
    logger.info(
        "push_playlist: %s playlist '%s' (id=%s) with %d tracks",
        action,
        playlist_name,
        playlist_id or existing_id or "unknown",
        len(resolved_ids),
    )

    return PushPlaylistResult(
        resolved_count=len(resolved_ids),
        unresolved_count=unresolved_count,
        playlist_id=playlist_id or existing_id or "",
    )
