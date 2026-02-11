"""Spotify playlist fetcher using spotipy library.

Requires Client Credentials authentication:
- SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be configured
- Works with public playlists only (no user auth required)

Uses spotipy library for API access and pagination handling.
"""

import logging
from typing import Any

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from nomarr.helpers.dto.playlist_import_dto import PlaylistMetadata, PlaylistTrackInput

logger = logging.getLogger(__name__)


class SpotifyFetchError(Exception):
    """Raised when Spotify API request fails."""



class SpotifyCredentialsError(SpotifyFetchError):
    """Raised when Spotify credentials are missing or invalid."""



def create_spotify_client(
    client_id: str, client_secret: str
) -> spotipy.Spotify:
    """Create an authenticated Spotify client.

    Uses Client Credentials flow (app-level auth) which works for public playlists.

    Args:
        client_id: Spotify Developer App client ID
        client_secret: Spotify Developer App client secret

    Returns:
        Authenticated spotipy.Spotify client

    Raises:
        SpotifyCredentialsError: If credentials are missing or invalid
    """
    if not client_id or not client_secret:
        raise SpotifyCredentialsError(
            "Spotify credentials not configured. "
            "Set spotify_client_id and spotify_client_secret in config."
        )

    try:
        auth_manager = SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
        return spotipy.Spotify(auth_manager=auth_manager)

    except Exception as e:
        raise SpotifyCredentialsError(
            f"Failed to authenticate with Spotify: {e}"
        ) from e


def fetch_spotify_playlist(
    client: spotipy.Spotify,
    playlist_id: str,
) -> tuple[PlaylistMetadata, list[PlaylistTrackInput]]:
    """Fetch a Spotify playlist by ID.

    Args:
        client: Authenticated spotipy.Spotify client
        playlist_id: Spotify playlist ID (from URL or URI)

    Returns:
        Tuple of (playlist metadata, list of tracks)

    Raises:
        SpotifyFetchError: If the API request fails or playlist not found
    """
    try:
        # Fetch playlist metadata
        playlist_data = client.playlist(
            playlist_id,
            fields="name,description,external_urls,tracks.total",
        )

        metadata = PlaylistMetadata(
            name=playlist_data.get("name", "Unknown Playlist"),
            description=playlist_data.get("description"),
            track_count=playlist_data.get("tracks", {}).get("total", 0),
            source_platform="spotify",
            source_url=playlist_data.get("external_urls", {}).get(
                "spotify", f"https://open.spotify.com/playlist/{playlist_id}"
            ),
        )

        # Fetch all tracks with pagination
        tracks = _fetch_all_tracks(client, playlist_id)

        return metadata, tracks

    except spotipy.SpotifyException as e:
        if e.http_status == 404:
            raise SpotifyFetchError(
                f"Playlist not found: {playlist_id}. "
                "Make sure the playlist is public."
            ) from e
        if e.http_status == 400:
            # 400 errors often mean private/personalized playlists
            raise SpotifyFetchError(
                f"Cannot access playlist: {playlist_id}. "
                "Spotify 'Made For You' and personalized playlists (IDs starting with 37i9dQZF1) "
                "cannot be fetched with app credentials. Only public playlists are supported."
            ) from e
        raise SpotifyFetchError(f"Spotify API error: {e}") from e


def _fetch_all_tracks(
    client: spotipy.Spotify, playlist_id: str
) -> list[PlaylistTrackInput]:
    """Fetch all tracks from a playlist, handling pagination.

    Spotify API returns max 100 tracks per request.

    Args:
        client: Authenticated spotipy client
        playlist_id: Spotify playlist ID

    Returns:
        List of all PlaylistTrackInput objects
    """
    tracks: list[PlaylistTrackInput] = []
    offset = 0
    limit = 100

    while True:
        results = client.playlist_tracks(
            playlist_id,
            offset=offset,
            limit=limit,
            fields="items(track(name,artists,album,external_ids,duration_ms)),next",
        )

        items = results.get("items", [])
        if not items:
            break

        for item in items:
            track_input = _extract_track(item, len(tracks))
            if track_input:
                tracks.append(track_input)

        # Check if there are more pages
        if not results.get("next"):
            break

        offset += limit

    return tracks


def _extract_track(
    item: dict[str, Any], position: int
) -> PlaylistTrackInput | None:
    """Extract a PlaylistTrackInput from a Spotify track item.

    Args:
        item: Track item from playlist_tracks response
        position: Position in playlist (0-indexed)

    Returns:
        PlaylistTrackInput or None if track is unavailable
    """
    track = item.get("track")

    # Skip local files and unavailable tracks
    if not track or track.get("is_local"):
        return None

    # Extract artist names (join multiple artists)
    artists = track.get("artists", [])
    artist_name = ", ".join(a.get("name", "") for a in artists) if artists else ""

    # Extract ISRC from external_ids
    external_ids = track.get("external_ids", {})
    isrc = external_ids.get("isrc")

    return PlaylistTrackInput(
        title=track.get("name", ""),
        artist=artist_name,
        album=track.get("album", {}).get("name"),
        isrc=isrc,
        duration_ms=track.get("duration_ms"),
        position=position,
    )
