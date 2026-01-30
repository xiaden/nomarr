"""Navidrome integration endpoints for web UI."""
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.exceptions import PlaylistQueryError
from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.navidrome_types import (
    GeneratePlaylistResponse,
    GenerateTemplateFilesRequest,
    GenerateTemplateFilesResponse,
    GetTemplateSummaryResponse,
    NavidromeConfigResponse,
    PlaylistGenerateRequest,
    PlaylistPreviewRequest,
    PlaylistPreviewResponse,
    PreviewTagStatsResponse,
)
from nomarr.interfaces.api.web.dependencies import get_navidrome_service

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.navidrome_svc import NavidromeService
router = APIRouter(prefix="/navidrome", tags=["Navidrome"])

@router.get("/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_preview(navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)]) -> PreviewTagStatsResponse:
    """Get preview of tags for Navidrome config generation (web UI proxy)."""
    try:
        result_dto = navidrome_service.preview_tag_stats()
        return PreviewTagStatsResponse.from_dto(result_dto)
    except Exception as e:
        logger.exception("[Web API] Error generating Navidrome preview")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to generate preview")) from e

@router.get("/config", dependencies=[Depends(verify_session)])
async def web_navidrome_config(navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)]) -> NavidromeConfigResponse:
    """Generate Navidrome TOML configuration (web UI proxy)."""
    try:
        toml_config = navidrome_service.generate_navidrome_config()
        return NavidromeConfigResponse.from_toml(toml_config)
    except Exception as e:
        logger.exception("[Web API] Error generating Navidrome config")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to generate config")) from e

@router.post("/playlists/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_preview(request: PlaylistPreviewRequest, navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)]) -> PlaylistPreviewResponse:
    """Preview Smart Playlist query results."""
    try:
        result_dto = navidrome_service.preview_playlist(query=request.query, preview_limit=request.preview_limit)
        return PlaylistPreviewResponse.from_dto(result_dto)
    except PlaylistQueryError:
        raise HTTPException(status_code=400, detail="Invalid playlist query") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Web API] Error previewing playlist")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to preview playlist")) from e

@router.post("/playlists/generate", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_generate(request: PlaylistGenerateRequest, navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)]) -> GeneratePlaylistResponse:
    """Generate Navidrome Smart Playlist (.nsp) from query."""
    try:
        result_dto = navidrome_service.generate_playlist(query=request.query, playlist_name=request.playlist_name, comment=request.comment, sort=request.sort, limit=request.limit)
        return GeneratePlaylistResponse.from_dto(result_dto)
    except PlaylistQueryError:
        raise HTTPException(status_code=400, detail="Invalid playlist query") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Web API] Error generating playlist")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to generate playlist")) from e

@router.get("/templates", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_list(navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)]) -> GetTemplateSummaryResponse:
    """Get list of all available playlist templates."""
    try:
        result_dto = navidrome_service.get_template_summary()
        return GetTemplateSummaryResponse.from_dto(result_dto)
    except Exception as e:
        logger.exception("[Web API] Error listing templates")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to list templates")) from e

@router.post("/templates", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_generate(request: GenerateTemplateFilesRequest, navidrome_service: Annotated["NavidromeService", Depends(get_navidrome_service)]) -> GenerateTemplateFilesResponse:
    """Generate all playlist templates as a batch."""
    try:
        result_dto = navidrome_service.generate_template_files(template_id=request.template_id or "", output_dir=request.output_dir or "")
        return GenerateTemplateFilesResponse(files_generated=result_dto.files_generated)
    except Exception as e:
        logger.exception("[Web API] Error generating templates")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to generate templates")) from e
