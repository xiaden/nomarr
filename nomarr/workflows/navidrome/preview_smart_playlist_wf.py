"""Preview smart playlist query results workflow.

This workflow previews tracks matching a smart playlist query without generating
the full .nsp file.

Flow:
1. API receives request → validates with Pydantic model
2. Service injects database and config → calls this workflow
3. Workflow validates query → parses into filter tree
4. Filter engine executes each condition → Python set operations combine results
5. Persistence fetches track metadata for sample
6. Return typed PlaylistPreviewResult → API serializes to JSON
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.navidrome.tag_query_comp import get_playlist_preview_tracks
from nomarr.helpers.dto.navidrome_dto import PlaylistPreviewResult
from nomarr.helpers.exceptions import PlaylistQueryError

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
from nomarr.workflows.navidrome.filter_engine_wf import execute_smart_playlist_filter
from nomarr.workflows.navidrome.parse_smart_playlist_query_wf import (
    parse_smart_playlist_query,
)


def preview_smart_playlist_workflow(
    db: Database,
    query: str,
    *,
    namespace: str = "nom",
    preview_limit: int = 10,
) -> PlaylistPreviewResult:
    """Preview tracks matching a smart playlist query.

    Args:
        db: Database instance
        query: Smart Playlist query string
        namespace: Tag namespace
        preview_limit: Number of sample tracks to return (validated at API: 1-100)

    Returns:
        PlaylistPreviewResult with total count, sample tracks, and original query

    Raises:
        PlaylistQueryError: If query is invalid or empty

    """
    if not query or not query.strip():
        msg = "Query cannot be empty"
        raise PlaylistQueryError(msg)

    # Parse query into filter tree
    playlist_filter = parse_smart_playlist_query(query, namespace)

    # Execute filter to get matching file IDs
    file_ids = execute_smart_playlist_filter(db, playlist_filter)

    # Count total matches
    total_count = len(file_ids)

    # Fetch sample tracks (limit already validated at API layer: 1-100)
    sample_tracks = get_playlist_preview_tracks(
        db,
        file_ids=file_ids,
        order_by=None,  # Random order for preview
        limit=preview_limit,
    )

    return PlaylistPreviewResult(total_count=total_count, sample_tracks=sample_tracks, query=query)
