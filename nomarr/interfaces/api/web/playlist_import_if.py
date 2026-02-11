"""Playlist import endpoints for web UI.

Converts streaming playlist URLs (Spotify, Deezer) to local M3U playlists.
"""

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.playlist_import_types import (
    ConvertPlaylistRequest,
    ConvertPlaylistResponse,
    SpotifyCredentialsStatusResponse,
)
from nomarr.interfaces.api.web.dependencies import get_playlist_import_service
from nomarr.workflows.playlist_import.convert_playlist_wf import (
    PlaylistConversionError,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nomarr.services.domain.playlist_import_svc import PlaylistImportService

router = APIRouter(prefix="/playlist-import", tags=["Playlist Import"])


@router.post("/convert", dependencies=[Depends(verify_session)])
async def web_convert_playlist(
    request: ConvertPlaylistRequest,
    playlist_service: Annotated[
        "PlaylistImportService", Depends(get_playlist_import_service)
    ],
) -> ConvertPlaylistResponse:
    """Convert a streaming playlist URL to local M3U playlist.

    Accepts Spotify or Deezer playlist URLs and returns:
    - M3U file content ready to save
    - Match statistics
    - Unmatched and ambiguous tracks for review

    Note: Spotify requires credentials configured (`spotify_client_id`/`secret`).
    Deezer works immediately (public API).
    """
    try:
        result_dto = playlist_service.convert_playlist(
            playlist_url=request.playlist_url,
            library_id=request.library_id,
        )
        return ConvertPlaylistResponse.from_dto(result_dto)

    except PlaylistConversionError as e:
        # User-facing error (bad URL, API failure, etc.)
        raise HTTPException(status_code=400, detail=str(e)) from None

    except Exception as e:
        logger.exception("[Web API] Error converting playlist")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to convert playlist"),
        ) from e


@router.get("/spotify-status", dependencies=[Depends(verify_session)])
async def web_spotify_credentials_status(
    playlist_service: Annotated[
        "PlaylistImportService", Depends(get_playlist_import_service)
    ],
) -> SpotifyCredentialsStatusResponse:
    """Check if Spotify credentials are configured.

    Returns configuration status. If not configured, only Deezer playlists
    can be converted.
    """
    has_creds = playlist_service.has_spotify_credentials()

    return SpotifyCredentialsStatusResponse(
        configured=has_creds,
        message=(
            "Spotify credentials configured - ready to convert Spotify playlists"
            if has_creds
            else "Spotify credentials not configured. "
            "Set spotify_client_id and spotify_client_secret in config to enable Spotify."
        ),
    )
