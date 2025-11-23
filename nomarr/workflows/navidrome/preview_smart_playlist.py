"""
Preview smart playlist query results workflow.

This workflow previews tracks matching a smart playlist query without generating
the full .nsp file.
"""

from typing import Any

from nomarr.persistence.db import Database
from nomarr.workflows.navidrome.parse_smart_playlist_query import (
    parse_smart_playlist_query,
)


def preview_smart_playlist_workflow(
    db: Database,
    query: str,
    *,
    namespace: str = "nom",
    preview_limit: int = 10,
) -> dict[str, Any]:
    """
    Preview tracks matching a smart playlist query.

    Args:
        db: Database instance
        query: Smart Playlist query string
        namespace: Tag namespace
        preview_limit: Number of sample tracks to return

    Returns:
        Dictionary with keys:
            - total_count: Total matching tracks
            - sample_tracks: List of sample track dicts
            - query: Original query string
    """
    if not query or not query.strip():
        raise ValueError("Query cannot be empty")

    # Parse query
    playlist_filter = parse_smart_playlist_query(query, namespace)

    # Count total matching tracks
    total_count = db.navidrome_smart_playlists.count_tracks_for_smart_playlist(playlist_filter)

    # Fetch sample tracks
    sample_tracks = db.navidrome_smart_playlists.select_tracks_for_smart_playlist(
        filter=playlist_filter, order_by=None, limit=preview_limit
    )

    return {"total_count": total_count, "sample_tracks": sample_tracks, "query": query}
