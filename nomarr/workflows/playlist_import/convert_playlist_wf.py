"""Workflow for converting streaming playlists to local Navidrome playlists.

Orchestrates: URL parsing → API fetch → matching → M3U output
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

from nomarr.components.playlist_import.deezer_fetcher_comp import (
    DeezerFetchError,
    fetch_deezer_playlist,
    resolve_short_link,
)
from nomarr.components.playlist_import.spotify_fetcher_comp import (
    SpotifyCredentialsError,
    SpotifyFetchError,
    create_spotify_client,
    fetch_spotify_playlist,
)
from nomarr.components.playlist_import.track_matcher_comp import (
    LibraryTrack,
    match_tracks,
)
from nomarr.components.playlist_import.url_parser_comp import (
    ParsedPlaylistUrl,
    PlaylistUrlError,
    parse_playlist_url,
)
from nomarr.helpers.dto.playlist_import_dto import (
    MatchResult,
    PlaylistConversionResult,
    PlaylistMetadata,
    PlaylistTrackInput,
)

logger = logging.getLogger(__name__)


class PlaylistConversionError(Exception):
    """Raised when playlist conversion fails."""



def convert_playlist_workflow(
    db: Database,
    playlist_url: str,
    *,
    library_id: str | None = None,
    spotify_client_id: str | None = None,
    spotify_client_secret: str | None = None,
) -> PlaylistConversionResult:
    """Convert a streaming playlist URL to a local Navidrome playlist.

    Workflow:
    1. Parse URL to identify platform and playlist ID
    2. Fetch playlist metadata and tracks from streaming API
    3. Load library tracks for matching
    4. Match each playlist track against library
    5. Generate M3U content with matched paths

    Args:
        db: ArangoDB database connection
        playlist_url: Spotify or Deezer playlist URL
        library_id: Optional library _id to restrict matching scope
        spotify_client_id: Spotify API client ID (required for Spotify playlists)
        spotify_client_secret: Spotify API client secret (required for Spotify playlists)

    Returns:
        PlaylistConversionResult with M3U content and match statistics

    Raises:
        PlaylistConversionError: If conversion fails at any stage
    """
    # Step 1: Parse URL
    try:
        parsed_url = parse_playlist_url(playlist_url)
    except PlaylistUrlError as e:
        raise PlaylistConversionError(str(e)) from e

    logger.info(
        f"Converting {parsed_url.platform} playlist: {parsed_url.playlist_id or 'short link'}"
    )

    # Step 2: Fetch playlist from streaming service
    metadata, input_tracks = _fetch_playlist(parsed_url, spotify_client_id, spotify_client_secret)

    logger.info(f"Fetched {len(input_tracks)} tracks from '{metadata.name}'")

    # Step 3: Load library tracks
    library_rows = db.library_files.get_tracks_for_matching(library_id=library_id)
    library_tracks = [LibraryTrack.from_db_row(row) for row in library_rows]

    logger.info(f"Loaded {len(library_tracks)} library tracks for matching")

    if not library_tracks:
        raise PlaylistConversionError(
            "No library tracks found. Import a library first."
        )

    # Step 4: Match tracks
    match_results = match_tracks(input_tracks, library_tracks)

    # Step 5: Generate output
    m3u_content = _generate_m3u(metadata, match_results)

    # Calculate statistics
    exact_isrc = sum(1 for r in match_results if r.status == "exact_isrc")
    exact_meta = sum(1 for r in match_results if r.status == "exact_metadata")
    fuzzy = sum(1 for r in match_results if r.status == "fuzzy")
    ambiguous = sum(1 for r in match_results if r.status == "ambiguous")
    not_found = sum(1 for r in match_results if r.status == "not_found")

    matched_count = exact_isrc + exact_meta + fuzzy

    logger.info(
        f"Match results: {matched_count} matched, {ambiguous} ambiguous, {not_found} not found"
    )

    return PlaylistConversionResult(
        playlist_metadata=metadata,
        m3u_content=m3u_content,
        total_tracks=len(input_tracks),
        matched_count=matched_count,
        exact_matches=exact_isrc + exact_meta,
        fuzzy_matches=fuzzy,
        ambiguous_count=ambiguous,
        not_found_count=not_found,
        match_results=tuple(match_results),
    )


def _fetch_playlist(
    parsed_url: ParsedPlaylistUrl,
    spotify_client_id: str | None,
    spotify_client_secret: str | None,
) -> tuple[PlaylistMetadata, list[PlaylistTrackInput]]:
    """Fetch playlist from the appropriate streaming service.

    Args:
        parsed_url: Parsed URL with platform and playlist ID
        spotify_client_id: Spotify credentials (if Spotify)
        spotify_client_secret: Spotify credentials (if Spotify)

    Returns:
        Tuple of (metadata, tracks)

    Raises:
        PlaylistConversionError: If fetching fails
    """
    if parsed_url.platform == "deezer":
        return _fetch_deezer(parsed_url)
    if parsed_url.platform == "spotify":
        return _fetch_spotify(parsed_url, spotify_client_id, spotify_client_secret)
    raise PlaylistConversionError(f"Unknown platform: {parsed_url.platform}")


def _fetch_deezer(
    parsed_url: ParsedPlaylistUrl,
) -> tuple[PlaylistMetadata, list[PlaylistTrackInput]]:
    """Fetch from Deezer API."""
    try:
        playlist_id = parsed_url.playlist_id

        # Handle short links
        if parsed_url.is_short_link:
            playlist_id = resolve_short_link(parsed_url.original_url)

        return fetch_deezer_playlist(playlist_id)

    except DeezerFetchError as e:
        raise PlaylistConversionError(f"Deezer fetch failed: {e}") from e


def _fetch_spotify(
    parsed_url: ParsedPlaylistUrl,
    client_id: str | None,
    client_secret: str | None,
) -> tuple[PlaylistMetadata, list[PlaylistTrackInput]]:
    """Fetch from Spotify API."""
    try:
        client = create_spotify_client(
            client_id=client_id or "",
            client_secret=client_secret or "",
        )
        return fetch_spotify_playlist(client, parsed_url.playlist_id)

    except SpotifyCredentialsError as e:
        raise PlaylistConversionError(
            f"Spotify credentials not configured: {e}"
        ) from e
    except SpotifyFetchError as e:
        raise PlaylistConversionError(f"Spotify fetch failed: {e}") from e


def _generate_m3u(
    metadata: PlaylistMetadata,
    match_results: list[MatchResult],
) -> str:
    """Generate M3U playlist content from match results.

    Only includes successfully matched tracks (exact or fuzzy).
    Ambiguous matches are excluded (require user review).

    Args:
        metadata: Playlist metadata for header
        match_results: List of match results

    Returns:
        M3U file content as string
    """
    lines = [
        "#EXTM3U",
        f"#PLAYLIST:{metadata.name}",
        f"# Source: {metadata.source_url}",
        f"# Converted from {metadata.source_platform}",
        "",
    ]

    for result in match_results:
        if result.matched_file and result.status in ("exact_isrc", "exact_metadata", "fuzzy"):
            # Add EXTINF with track info
            duration_s = (
                result.input_track.duration_ms // 1000
                if result.input_track.duration_ms
                else -1
            )
            artist = result.input_track.artist
            title = result.input_track.title
            lines.append(f"#EXTINF:{duration_s},{artist} - {title}")
            lines.append(result.matched_file.path)

    return "\n".join(lines) + "\n"
