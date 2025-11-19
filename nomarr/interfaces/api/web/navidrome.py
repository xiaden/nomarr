"""Navidrome integration endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_database

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

router = APIRouter(prefix="/api/navidrome", tags=["Navidrome"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_preview(
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Get preview of tags for Navidrome config generation (web UI proxy)."""
    from nomarr.app import application
    from nomarr.services.navidrome.config_generator import preview_tag_stats

    namespace = application.namespace

    try:
        stats = preview_tag_stats(db, namespace=namespace)

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
            "namespace": namespace,
            "tag_count": len(tag_list),
            "tags": tag_list,
        }

    except Exception as e:
        logging.exception("[Web API] Error generating Navidrome preview")
        raise HTTPException(status_code=500, detail=f"Error generating preview: {e}") from e


@router.get("/config", dependencies=[Depends(verify_session)])
async def web_navidrome_config(
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Generate Navidrome TOML configuration (web UI proxy)."""
    from nomarr.app import application
    from nomarr.services.navidrome.config_generator import generate_navidrome_config

    namespace = application.namespace

    try:
        toml_config = generate_navidrome_config(db, namespace=namespace)

        return {
            "namespace": namespace,
            "config": toml_config,
        }

    except Exception as e:
        logging.exception("[Web API] Error generating Navidrome config")
        raise HTTPException(status_code=500, detail=f"Error generating config: {e}") from e


@router.post("/playlists/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_preview(request: dict) -> dict[str, Any]:
    """Preview Smart Playlist query results."""
    from nomarr.app import application

    try:
        from nomarr.services.navidrome.playlist_generator import (
            PlaylistQueryError,
            preview_playlist_query,
        )

        query = request.get("query", "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        preview_limit = request.get("preview_limit", 10)

        db_path = application.db_path
        namespace = application.namespace

        try:
            result = preview_playlist_query(db_path, query, namespace, preview_limit)
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
    from nomarr.app import application

    try:
        from nomarr.services.navidrome.playlist_generator import (
            PlaylistQueryError,
            generate_nsp_playlist,
        )

        query = request.get("query", "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        playlist_name = request.get("playlist_name", "Playlist")
        comment = request.get("comment", "")
        limit = request.get("limit")
        sort = request.get("sort")

        db_path = application.db_path
        namespace = application.namespace

        try:
            nsp_content = generate_nsp_playlist(
                db_path,
                query,
                playlist_name,
                comment,
                namespace,
                sort,
                limit,
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
        from nomarr.services.navidrome.templates import get_template_summary

        templates = get_template_summary()
        return {"templates": templates, "total_count": len(templates)}

    except Exception as e:
        logging.exception("[Web API] Error listing templates")
        raise HTTPException(status_code=500, detail=f"Error listing templates: {e}") from e


@router.post("/templates/generate", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_generate() -> dict[str, Any]:
    """Generate all playlist templates as a batch."""
    try:
        from nomarr.services.navidrome.templates import generate_template_files

        templates = generate_template_files()
        return {"templates": templates, "total_count": len(templates)}

    except Exception as e:
        logging.exception("[Web API] Error generating templates")
        raise HTTPException(status_code=500, detail=f"Error generating templates: {e}") from e
