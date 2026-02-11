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
_SPOTIFY_WEB_PATTERN = re.compile(
    r"(?:https?://)?(?:open\.)?spotify\.com/playlist/([a-zA-Z0-9]+)"
)
_SPOTIFY_URI_PATTERN = re.compile(r"spotify:playlist:([a-zA-Z0-9]+)")

# Deezer patterns
_DEEZER_WEB_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?deezer\.com/(?:[a-z]{2}/)?playlist/(\d+)"
)
_DEEZER_SHORT_PATTERN = re.compile(r"(?:https?://)?link\.deezer\.com/")


def parse_playlist_url(url: str) -> ParsedPlaylistUrl:
    """Extract platform and playlist ID from a streaming service URL.

    Args:
        url: A Spotify or Deezer playlist URL in any supported format

    Returns:
        ParsedPlaylistUrl with platform, playlist_id, and metadata

    Raises:
        PlaylistUrlError: If the URL doesn't match any known pattern

    Examples:
        >>> parse_playlist_url("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        ParsedPlaylistUrl(platform='spotify', playlist_id='37i9dQZF1DXcBWIGoYBM5M', ...)

        >>> parse_playlist_url("https://www.deezer.com/playlist/1234567890")
        ParsedPlaylistUrl(platform='deezer', playlist_id='1234567890', ...)

        >>> parse_playlist_url("https://link.deezer.com/s/32pxbZMVkKIxZyRZwEBEN")
        ParsedPlaylistUrl(platform='deezer', playlist_id='', is_short_link=True, ...)
    """
    url = url.strip()

    # Try Spotify web URL
    match = _SPOTIFY_WEB_PATTERN.search(url)
    if match:
        return ParsedPlaylistUrl(
            platform="spotify",
            playlist_id=match.group(1),
            original_url=url,
        )

    # Try Spotify URI
    match = _SPOTIFY_URI_PATTERN.search(url)
    if match:
        return ParsedPlaylistUrl(
            platform="spotify",
            playlist_id=match.group(1),
            original_url=url,
        )

    # Try Deezer web URL
    match = _DEEZER_WEB_PATTERN.search(url)
    if match:
        return ParsedPlaylistUrl(
            platform="deezer",
            playlist_id=match.group(1),
            original_url=url,
        )

    # Try Deezer short link (requires later resolution)
    if _DEEZER_SHORT_PATTERN.search(url):
        return ParsedPlaylistUrl(
            platform="deezer",
            playlist_id="",  # Will be resolved by fetcher
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
