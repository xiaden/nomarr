"""Navidrome integration endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.app import application
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_navidrome_service
from nomarr.workflows.navidrome.parse_smart_playlist_query import PlaylistQueryError

if TYPE_CHECKING:
    pass

router = APIRouter(prefix="/api/navidrome", tags=["Navidrome"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_preview(
    navidrome_service: Any = Depends(get_navidrome_service),
) -> dict[str, Any]:
    """Get preview of tags for Navidrome config generation (web UI proxy)."""
    try:
        stats = navidrome_service.preview_tag_stats()

        # Convert to list format for easier frontend consumption
        tag_list = []
        for tag_key, tag_stats in sorted(stats.items()):
            tag_list.append(
                {
                    "tag_key": tag_key,
                    "type": tag_stats["type"],
                    "is_multivalue": tag_stats["is_multivalue"],
                    "summary": tag_stats["summary"],
                    "total_count": tag_stats["total_count"],
                }
            )

        return {
            "tag_count": len(tag_list),
            "tags": tag_list,
        }

    except Exception as e:
        logging.exception("[Web API] Error generating Navidrome preview")
        raise HTTPException(status_code=500, detail=f"Error generating preview: {e}") from e


@router.get("/config", dependencies=[Depends(verify_session)])
async def web_navidrome_config(
    navidrome_service: Any = Depends(get_navidrome_service),
) -> dict[str, Any]:
    """Generate Navidrome TOML configuration (web UI proxy)."""
    try:
        toml_config = navidrome_service.generate_navidrome_config(format="toml")

        return {
            "config": toml_config,
        }

    except Exception as e:
        logging.exception("[Web API] Error generating Navidrome config")
        raise HTTPException(status_code=500, detail=f"Error generating config: {e}") from e


@router.post("/playlists/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_preview(
    request: dict,
    navidrome_service: Any = Depends(get_navidrome_service),
) -> dict[str, Any]:
    """Preview Smart Playlist query results."""
    # TODO: NavidromeService.preview_playlist method signature doesn't match utility function
    # This endpoint currently bypasses the service to maintain functionality.
    # Fix NavidromeService methods to match utility function signatures.
    try:
        from nomarr.workflows.navidrome.preview_smart_playlist import (
            preview_smart_playlist_workflow,
        )

        query = request.get("query", "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        preview_limit = request.get("preview_limit", 10)

        try:
            # Call workflow directly
            result = preview_smart_playlist_workflow(
                db=application.db,
                query=query,
                namespace=navidrome_service.cfg.namespace,
                preview_limit=preview_limit,
            )
            return result
        except PlaylistQueryError as e:
            raise HTTPException(status_code=400, detail=f"Invalid query: {e}") from e

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error previewing playlist")
        raise HTTPException(status_code=500, detail=f"Error previewing playlist: {e}") from e


@router.post("/playlists/generate", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_generate(request: dict) -> dict[str, Any]:
    """Generate Navidrome Smart Playlist (.nsp) from query."""
    from nomarr.workflows.navidrome.generate_smart_playlist import (
        generate_smart_playlist_workflow,
    )

    navidrome_service = get_navidrome_service()

    try:
        query = request.get("query", "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        playlist_name = request.get("playlist_name", "Playlist")
        comment = request.get("comment", "")
        limit = request.get("limit")
        sort = request.get("sort")

        # Call workflow directly
        nsp_content = generate_smart_playlist_workflow(
            db=application.db,
            query=query,
            playlist_name=playlist_name,
            comment=comment,
            namespace=navidrome_service.cfg.namespace,
            sort=sort,
            limit=limit,
        )

        return {
            "playlist_name": playlist_name,
            "query": query,
            "content": nsp_content,
            "format": "nsp",
        }

    except PlaylistQueryError as e:
        raise HTTPException(status_code=400, detail=f"Invalid query: {e}") from e
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error generating playlist")
        raise HTTPException(status_code=500, detail=f"Error generating playlist: {e}") from e


@router.get("/templates/list", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_list() -> dict[str, Any]:
    """Get list of all available playlist templates."""
    try:
        from nomarr.helpers.navidrome_templates import get_template_summary

        templates = get_template_summary()
        return {"templates": templates, "total_count": len(templates)}

    except Exception as e:
        logging.exception("[Web API] Error listing templates")
        raise HTTPException(status_code=500, detail=f"Error listing templates: {e}") from e


@router.post("/templates/generate", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_generate() -> dict[str, Any]:
    """Generate all playlist templates as a batch."""
    try:
        from nomarr.helpers.navidrome_templates import generate_template_files

        templates = generate_template_files()
        return {"templates": templates, "total_count": len(templates)}

    except Exception as e:
        logging.exception("[Web API] Error generating templates")
        raise HTTPException(status_code=500, detail=f"Error generating templates: {e}") from e
