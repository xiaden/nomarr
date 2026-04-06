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
    PushStaticPlaylistResponse,
    StaticPlaylistRequest,
    StaticPlaylistResponse,
    SyncSongsResponse,
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
    rel: str,
    navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> TagValuesResponse:
    """Get distinct values for a specific tag relationship."""
    try:
        values = await asyncio.to_thread(navidrome_service.get_tag_values, rel)
        return TagValuesResponse(rel=rel, values=values)
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


@router.post("/playlist/push", dependencies=[Depends(verify_session)], response_model=PushStaticPlaylistResponse)
async def web_navidrome_push_playlist(
    request: StaticPlaylistRequest,
    navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> PushStaticPlaylistResponse:
    """Push a static playlist to Navidrome via Subsonic API.

    Creates or replaces a Navidrome playlist using song IDs resolved from
    the supplied Nomarr file IDs.  Returns the Navidrome playlist ID and
    resolution details.
    """
    try:
        result_dto = await asyncio.to_thread(
            navidrome_service.push_static_playlist,
            file_ids=[decode_id(fid) for fid in request.file_ids],
            playlist_name=request.playlist_name,
        )
        return PushStaticPlaylistResponse.from_dto(result_dto)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Web API] Error pushing static playlist to Navidrome")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to push playlist")) from e


@router.post("/sync-song", dependencies=[Depends(verify_session)])
async def web_navidrome_sync_songs(
    navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)],
) -> SyncSongsResponse:
    """Trigger a full Navidrome song sync to graph collections."""
    try:
        result = await asyncio.to_thread(navidrome_service.sync_navidrome)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        logger.exception("[Web API] Error syncing Navidrome songs")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to sync songs")) from e

    return SyncSongsResponse(
        total_songs=result["total_songs"],
        resolved=result["resolved"],
        unresolved=result["unresolved"],
        tracks_upserted=result["tracks_upserted"],
        play_edges_upserted=result["play_edges_upserted"],
        orphans_removed=result["orphans_removed"],
        duration_ms=result["duration_ms"],
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
