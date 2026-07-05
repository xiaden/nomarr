"""Deezer playlist fetcher using public API.

No authentication required. Fetches playlist tracks via:
GET https://api.deezer.com/playlist/{id}

The Deezer API returns track data including ISRC codes when available.
"""

import logging
from typing import Any

import requests

from nomarr.helpers.dto.playlist_import_dto import PlaylistMetadata, PlaylistTrackInput

logger = logging.getLogger(__name__)

_DEEZER_API_BASE = "https://api.deezer.com"
_REQUEST_TIMEOUT = 30  # seconds


class DeezerFetchError(Exception):
    """Raised when Deezer API request fails."""


def resolve_short_link(short_url: str) -> str:
    """Resolve a Deezer short link (link.deezer.com) to get the actual playlist ID.

    Raises DeezerFetchError if the short link cannot be resolved.
    """
    try:
        response = requests.head(short_url, allow_redirects=True, timeout=_REQUEST_TIMEOUT)
        final_url = response.url

        if "/playlist/" in final_url:
            parts = final_url.split("/playlist/")
            if len(parts) >= 2:
                return parts[1].split("?")[0].split("/")[0]

        raise DeezerFetchError(f"Short link did not resolve to a playlist URL: {final_url}")

    except requests.RequestException as e:
        raise DeezerFetchError(f"Failed to resolve short link: {e}") from e


def fetch_deezer_playlist(
    playlist_id: str,
) -> tuple[PlaylistMetadata, list[PlaylistTrackInput]]:
    """Fetch a Deezer playlist by ID from the public API.

    Raises DeezerFetchError if the request fails or playlist is not found.
    """
    url = f"{_DEEZER_API_BASE}/playlist/{playlist_id}"

    try:
        response = requests.get(url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as e:
        raise DeezerFetchError(f"Deezer API request failed: {e}") from e

    if "error" in data:
        error_message = data["error"].get("message", "Unknown error")
        raise DeezerFetchError(f"Deezer API error: {error_message}")

    metadata = PlaylistMetadata(
        name=data.get("title", "Unknown Playlist"),
        description=data.get("description"),
        track_count=data.get("nb_tracks", 0),
        source_platform="deezer",
        source_url=data.get("link", f"https://www.deezer.com/playlist/{playlist_id}"),
    )

    tracks = _extract_tracks(data.get("tracks", {}).get("data", []))
    tracks_data = data.get("tracks", {})
    next_url = tracks_data.get("next")

    while next_url:
        try:
            response = requests.get(next_url, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            page_data = response.json()
            tracks.extend(_extract_tracks(page_data.get("data", [])))
            next_url = page_data.get("next")
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch next page: {e}")
            break

    return metadata, tracks


def _extract_tracks(track_data: list[dict[str, Any]]) -> list[PlaylistTrackInput]:
    """Extract PlaylistTrackInput objects from Deezer API track data.

    Geo-restricted tracks (``readable=false``) are included since we only need
    metadata for matching.
    """
    tracks = []

    for i, track in enumerate(track_data):
        tracks.append(
            PlaylistTrackInput(
                title=track.get("title", ""),
                artist=track.get("artist", {}).get("name", ""),
                album=track.get("album", {}).get("title"),
                isrc=track.get("isrc"),
                duration_ms=track.get("duration", 0) * 1000,
                position=i,
            )
        )

    return tracks
