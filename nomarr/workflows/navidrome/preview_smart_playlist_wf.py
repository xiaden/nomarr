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

from nomarr.components.library.tag_hydration_comp import hydrate_songs_with_metadata
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

    # Execute filter to get matching song storage handles. The smart-playlist
    # tag engine still returns private handles; resolve them once to mutable
    # locators at this boundary and never carry the integers further.
    song_ids = execute_smart_playlist_filter(db, playlist_filter)

    # Count total matches
    total_count = len(song_ids)

    identities_by_id = db.library.resolve_song_identities(list(song_ids))
    sample_identities = list(identities_by_id.values())[:preview_limit]

    # Fetch sample tracks (limit already validated at API layer: 1-100)
    sample_pairs = []
    for identity in sample_identities:
        song = db.library.get_song(identity)
        if song is not None:
            sample_pairs.append((identity, song))
    hydrated = hydrate_songs_with_metadata(
        db,
        [song for _, song in sample_pairs],
        [identity for identity, _ in sample_pairs],
    )
    sample_tracks = [
        {
            "path": hydrated_song.song.path,
            "title": str(hydrated_song.metadata.get("title", "")),
            "artist": str(hydrated_song.metadata.get("artist", "")),
            "album": str(hydrated_song.metadata.get("album", "")),
        }
        for hydrated_song in hydrated
    ]

    return PlaylistPreviewResult(total_count=total_count, sample_tracks=sample_tracks, query=query)
