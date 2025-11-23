"""Navidrome integration endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_navidrome_service
from nomarr.workflows.navidrome.parse_smart_playlist_query import PlaylistQueryError

if TYPE_CHECKING:
    from nomarr.services.navidrome_service import NavidromeService

router = APIRouter(prefix="/navidrome", tags=["Navidrome"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_preview(
    navidrome_service: "NavidromeService" = Depends(get_navidrome_service),
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
    navidrome_service: "NavidromeService" = Depends(get_navidrome_service),
) -> dict[str, Any]:
    """Generate Navidrome TOML configuration (web UI proxy)."""
    try:
        toml_config = navidrome_service.generate_navidrome_config()

        return {
            "config": toml_config,
        }

    except Exception as e:
        logging.exception("[Web API] Error generating Navidrome config")
        raise HTTPException(status_code=500, detail=f"Error generating config: {e}") from e


@router.post("/playlists/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_preview(
    request: dict,
    navidrome_service: "NavidromeService" = Depends(get_navidrome_service),
) -> dict[str, Any]:
    """Preview Smart Playlist query results."""
    try:
        query = request.get("query", "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        preview_limit = request.get("preview_limit", 10)

        # Call service method instead of workflow directly
        result = navidrome_service.preview_playlist(query=query, preview_limit=preview_limit)
        return result

    except PlaylistQueryError as e:
        raise HTTPException(status_code=400, detail=f"Invalid query: {e}") from e
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error previewing playlist")
        raise HTTPException(status_code=500, detail=f"Error previewing playlist: {e}") from e


@router.post("/playlists/generate", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_generate(
    request: dict,
    navidrome_service: "NavidromeService" = Depends(get_navidrome_service),
) -> dict[str, Any]:
    """Generate Navidrome Smart Playlist (.nsp) from query."""
    try:
        query = request.get("query", "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        playlist_name = request.get("playlist_name", "Playlist")
        comment = request.get("comment", "")
        limit = request.get("limit")
        sort = request.get("sort")

        # Call service method instead of workflow directly
        nsp_structure = navidrome_service.generate_playlist(
            query=query,
            playlist_name=playlist_name,
            comment=comment,
            sort=sort,
            limit=limit,
        )

        # Service returns the .nsp structure dict
        # Frontend expects: playlist_name, query, content, format
        # Convert dict to JSON string for "content" field
        import json

        return {
            "playlist_name": playlist_name,
            "query": query,
            "content": json.dumps(nsp_structure, indent=2),
            "format": "nsp",
        }

    except PlaylistQueryError as e:
        raise HTTPException(status_code=400, detail=f"Invalid query: {e}") from e
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error generating playlist")
        raise HTTPException(status_code=500, detail=f"Error generating playlist: {e}") from e


@router.get("/templates", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_list() -> dict[str, Any]:
    """Get list of all available playlist templates."""
    try:
        from nomarr.helpers.navidrome_templates import get_template_summary

        templates = get_template_summary()
        return {"templates": templates, "total_count": len(templates)}

    except Exception as e:
        logging.exception("[Web API] Error listing templates")
        raise HTTPException(status_code=500, detail=f"Error listing templates: {e}") from e


@router.post("/templates", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_generate() -> dict[str, Any]:
    """Generate all playlist templates as a batch."""
    try:
        from nomarr.helpers.navidrome_templates import generate_template_files

        templates = generate_template_files()
        return {"templates": templates, "total_count": len(templates)}

    except Exception as e:
        logging.exception("[Web API] Error generating templates")
        raise HTTPException(status_code=500, detail=f"Error generating templates: {e}") from e
