"""Navidrome integration endpoints for web UI."""

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.exceptions import PlaylistQueryError
from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_id
from nomarr.interfaces.api.types.navidrome_types import (
    GeneratePlaylistResponse,
    GenerateTemplateFilesRequest,
    GenerateTemplateFilesResponse,
    GetTemplateSummaryResponse,
    NavidromeConfigResponse,
    NavidromeStatusResponse,
    PingResponse,
    PlaylistGenerateRequest,
    PlaylistPreviewRequest,
    PlaylistPreviewResponse,
    PreviewTagStatsResponse,
    StaticPlaylistRequest,
    StaticPlaylistResponse,
    TagValuesResponse,
)
from nomarr.interfaces.api.web.dependencies import get_navidrome_service

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.navidrome_svc import NavidromeService
router = APIRouter(prefix="/navidrome", tags=["Navidrome"])


@router.get("/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_preview(
    navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> PreviewTagStatsResponse:
    """Get preview of tags for Navidrome config generation (web UI proxy)."""
    try:
        result_dto = await asyncio.to_thread(navidrome_service.preview_tag_stats)
        return PreviewTagStatsResponse.from_dto(result_dto)
    except Exception as e:
        logger.exception("[Web API] Error generating Navidrome preview")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to generate preview")) from e


@router.get("/tag-value", dependencies=[Depends(verify_session)])
async def web_navidrome_tag_values(
    name: str,
    navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> TagValuesResponse:
    """Get distinct values for a specific tag name."""
    try:
        values = await asyncio.to_thread(navidrome_service.get_tag_values, name)
        return TagValuesResponse(name=name, values=values)
    except Exception as e:
        logger.exception("[Web API] Error fetching tag values")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to fetch tag values")) from e


@router.get("/config", dependencies=[Depends(verify_session)])
async def web_navidrome_config(
    navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> NavidromeConfigResponse:
    """Generate Navidrome TOML configuration (web UI proxy)."""
    try:
        toml_config = await asyncio.to_thread(navidrome_service.generate_navidrome_config)
        return NavidromeConfigResponse.from_toml(toml_config)
    except Exception as e:
        logger.exception("[Web API] Error generating Navidrome config")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to generate config")) from e


@router.post("/playlist/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_preview(
    request: PlaylistPreviewRequest, navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)]
) -> PlaylistPreviewResponse:
    """Preview Smart Playlist query results."""
    try:
        result_dto = await asyncio.to_thread(
            navidrome_service.preview_playlist, query=request.query, preview_limit=request.preview_limit
        )
        return PlaylistPreviewResponse.from_dto(result_dto)
    except PlaylistQueryError:
        raise HTTPException(status_code=400, detail="Invalid playlist query") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Web API] Error previewing playlist")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to preview playlist")) from e


@router.post("/playlist/generate", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_generate(
    request: PlaylistGenerateRequest, navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)]
) -> GeneratePlaylistResponse:
    """Generate Navidrome Smart Playlist (.nsp) from query."""
    try:
        result_dto = await asyncio.to_thread(
            navidrome_service.generate_playlist,
            query=request.query,
            playlist_name=request.playlist_name,
            comment=request.comment,
            sort=request.sort,
            limit=request.limit,
        )
        return GeneratePlaylistResponse.from_dto(result_dto)
    except PlaylistQueryError:
        raise HTTPException(status_code=400, detail="Invalid playlist query") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Web API] Error generating playlist")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to generate playlist")) from e


@router.get("/template", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_list(
    navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> GetTemplateSummaryResponse:
    """Get list of all available playlist templates."""
    try:
        result_dto = await asyncio.to_thread(navidrome_service.get_template_summary)
        return GetTemplateSummaryResponse.from_dto(result_dto)
    except Exception as e:
        logger.exception("[Web API] Error listing templates")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to list templates")) from e


@router.post("/template", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_generate(
    request: GenerateTemplateFilesRequest,
    navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> GenerateTemplateFilesResponse:
    """Generate all playlist templates as a batch."""
    try:
        result_dto = await asyncio.to_thread(
            navidrome_service.generate_template_files,
            template_id=request.template_id or "",
            output_dir=request.output_dir or "",
        )
        return GenerateTemplateFilesResponse(files_generated=result_dto.files_generated)
    except Exception as e:
        logger.exception("[Web API] Error generating templates")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to generate templates")
        ) from e


@router.post("/playlist/static", dependencies=[Depends(verify_session)])
async def web_navidrome_static_playlist(
    request: StaticPlaylistRequest, navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)]
) -> StaticPlaylistResponse:
    """Generate a static M3U playlist from a list of file IDs."""
    try:
        result_dto = await asyncio.to_thread(
            navidrome_service.generate_static_playlist,
            file_ids=[decode_id(fid) for fid in request.file_ids],
            playlist_name=request.playlist_name,
        )
        return StaticPlaylistResponse.from_dto(result_dto)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Web API] Error generating static playlist")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to generate static playlist")
        ) from e


@router.post("/playlist/push", dependencies=[Depends(verify_session)])
async def web_navidrome_push_playlist(
    _request: StaticPlaylistRequest,
    _navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> None:
    """Push a static playlist to Navidrome via Subsonic API.

    Creates or replaces a Navidrome playlist using song IDs resolved from
    the supplied Nomarr file IDs.  Returns the Navidrome playlist ID and
    resolution details.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "Backend Navidrome-ID playlist push has been removed. "
            "Use plugin-backed descriptor flows where the plugin resolves Navidrome IDs locally."
        ),
    )


@router.post("/sync-song", dependencies=[Depends(verify_session)])
async def web_navidrome_sync_songs(
    _navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> None:
    """Trigger a full Navidrome song sync to graph collections."""
    raise HTTPException(
        status_code=410,
        detail=(
            "Backend Navidrome song-map sync has been removed for playlist/recommendation output paths. "
            "Use plugin-backed descriptor flows."
        ),
    )


@router.post("/generate-personal-playlists", dependencies=[Depends(verify_session)])
async def web_generate_personal_playlists(
    _navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> None:
    """Trigger personal playlist generation for the configured Navidrome user."""
    raise HTTPException(
        status_code=410,
        detail=(
            "Backend personal-playlist push has been removed. "
            "Use plugin-backed /api/v1/navidrome/playlist/generate descriptor flow."
        ),
    )


@router.post("/ping", response_model=PingResponse)
async def navidrome_ping(
    navidrome_service: "NavidromeService" = Depends(get_navidrome_service),
) -> PingResponse:
    """Test connectivity to the Navidrome server."""
    ok, error = await asyncio.to_thread(navidrome_service.ping)
    return PingResponse(ok=ok, error=error or None)


@router.get("/status", response_model=NavidromeStatusResponse)
async def navidrome_status(
    navidrome_service: "NavidromeService" = Depends(get_navidrome_service),
) -> NavidromeStatusResponse:
    """Check whether Navidrome integration is configured (no connection attempt)."""
    configured = navidrome_service.is_navidrome_configured()
    return NavidromeStatusResponse(configured=configured)
