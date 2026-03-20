"""Service for playlist import and conversion.

Provides playlist conversion from Spotify/Deezer URLs to local Navidrome playlists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.config_svc import ConfigService

from nomarr.helpers.dto.playlist_import_dto import PlaylistConversionResult
from nomarr.helpers.exceptions import PlaylistConversionError
from nomarr.workflows.playlist_import.convert_playlist_wf import (
    convert_playlist_workflow,
)


class PlaylistImportService:
    """Service for importing and converting streaming playlists.

    Converts Spotify and Deezer playlist URLs to local M3U playlists
    by matching tracks against the imported library.

    Example:
        >>> service = PlaylistImportService(db, config_service)
        >>> result = service.convert_playlist(
        ...     "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        ... )
        >>> print(result.match_rate)  # 0.92 = 92% matched
    """

    def __init__(self, db: Database, config_service: ConfigService) -> None:
        """Initialize PlaylistImportService.

        Args:
            db: ArangoDB database instance
            config_service: Live configuration provider (for Spotify credentials)
        """
        self._db = db
        self._config_service = config_service

    def convert_playlist(
        self,
        playlist_url: str,
        *,
        library_id: str | None = None,
    ) -> PlaylistConversionResult:
        """Convert a streaming playlist URL to local M3U playlist.

        Supports:
        - Spotify: https://open.spotify.com/playlist/{id}
        - Deezer: https://deezer.com/playlist/{id} or link.deezer.com short links

        Args:
            playlist_url: Full URL to a Spotify or Deezer playlist
            library_id: Optional library _id to restrict matching scope

        Returns:
            PlaylistConversionResult with:
            - m3u_content: Ready-to-save M3U file content
            - Match statistics (total, matched, exact, fuzzy, ambiguous, not_found)
            - Full match_results for detailed review

        Raises:
            PlaylistConversionError: If URL is invalid, API fails, or no library exists
        """
        return convert_playlist_workflow(
            self._db,
            playlist_url,
            library_id=library_id,
            spotify_client_id=self._config_service.get("spotify_client_id"),
            spotify_client_secret=self._config_service.get("spotify_client_secret"),
        )

    def has_spotify_credentials(self) -> bool:
        """Check if Spotify credentials are configured.

        Returns:
            True if both client_id and client_secret are set
        """
        return bool(self._config_service.get("spotify_client_id") and self._config_service.get("spotify_client_secret"))


__all__ = [
    "PlaylistConversionError",
    "PlaylistConversionResult",
    "PlaylistImportService",
]
