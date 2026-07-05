"""URL parser for extracting playlist IDs from streaming service URLs.

Supports:
- Spotify: open.spotify.com/playlist/{id}, spotify:playlist:{id}
- Deezer: deezer.com/playlist/{id}, link.deezer.com short links
"""

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ParsedPlaylistUrl:
    """Result of parsing a playlist URL.

    Attributes:
        platform: The streaming platform (spotify or deezer)
        playlist_id: The extracted playlist ID
        original_url: The original URL that was parsed
        is_short_link: True if this is a short link requiring resolution
    """

    platform: Literal["spotify", "deezer"]
    playlist_id: str
    original_url: str
    is_short_link: bool = False


class PlaylistUrlError(ValueError):
    """Raised when a URL cannot be parsed as a valid playlist URL."""


# Spotify patterns
_SPOTIFY_WEB_PATTERN = re.compile(r"(?:https?://)?(?:open\.)?spotify\.com/playlist/([a-zA-Z0-9]+)")
_SPOTIFY_URI_PATTERN = re.compile(r"spotify:playlist:([a-zA-Z0-9]+)")

# Deezer patterns
_DEEZER_WEB_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?deezer\.com/(?:[a-z]{2}/)?playlist/(\d+)")
_DEEZER_SHORT_PATTERN = re.compile(r"(?:https?://)?link\.deezer\.com/")


def parse_playlist_url(url: str) -> ParsedPlaylistUrl:
    """Extract platform and playlist ID from a streaming service URL.

    Supports Spotify (open.spotify.com/playlist/{id}, spotify:playlist:{id})
    and Deezer (deezer.com/playlist/{id}, link.deezer.com short links).

    Raises PlaylistUrlError if the URL doesn't match any known pattern.
    """
    url = url.strip()

    match = _SPOTIFY_WEB_PATTERN.search(url)
    if match:
        return ParsedPlaylistUrl(
            platform="spotify",
            playlist_id=match.group(1),
            original_url=url,
        )

    match = _SPOTIFY_URI_PATTERN.search(url)
    if match:
        return ParsedPlaylistUrl(
            platform="spotify",
            playlist_id=match.group(1),
            original_url=url,
        )

    match = _DEEZER_WEB_PATTERN.search(url)
    if match:
        return ParsedPlaylistUrl(
            platform="deezer",
            playlist_id=match.group(1),
            original_url=url,
        )

    if _DEEZER_SHORT_PATTERN.search(url):
        return ParsedPlaylistUrl(
            platform="deezer",
            playlist_id="",
            original_url=url,
            is_short_link=True,
        )

    raise PlaylistUrlError(
        f"Unrecognized playlist URL format: {url}. "
        "Expected Spotify (open.spotify.com/playlist/...) or "
        "Deezer (deezer.com/playlist/... or link.deezer.com/...)"
    )


def is_spotify_url(url: str) -> bool:
    """Check if URL is a Spotify playlist URL."""
    return bool(_SPOTIFY_WEB_PATTERN.search(url) or _SPOTIFY_URI_PATTERN.search(url))


def is_deezer_url(url: str) -> bool:
    """Check if URL is a Deezer playlist URL."""
    return bool(_DEEZER_WEB_PATTERN.search(url) or _DEEZER_SHORT_PATTERN.search(url))
