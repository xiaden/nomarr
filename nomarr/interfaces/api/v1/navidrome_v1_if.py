"""Navidrome v1 API endpoints for integration use.

Routes: /v1/navidrome/similar-tracks, /v1/navidrome/sync-songs.
Auth: API key (verify_key).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.types.navidrome_types import SyncSongsResponse
from nomarr.interfaces.api.web.dependencies import get_navidrome_service

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.navidrome_svc import NavidromeService

router = APIRouter(tags=["navidrome"], prefix="/v1/navidrome")


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class SimilarTracksRequest(BaseModel):
    """Request body for similar tracks endpoint."""

    song_id: str
    count: int = Field(default=50, ge=1, le=500)
    backbone_id: str = "effnet-discogs"


class SongResult(BaseModel):
    """A single similar song in the response."""

    id: str
    name: str
    artist: str
    album: str
    score: float


class SimilarTracksResponse(BaseModel):
    """Response for similar tracks endpoint."""

    songs: list[SongResult]



# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.post("/similar-tracks", dependencies=[Depends(verify_key)])
async def navidrome_similar_tracks(
    body: SimilarTracksRequest,
    svc: Annotated[NavidromeService, Depends(get_navidrome_service)],
) -> SimilarTracksResponse:
    """Find tracks similar to a Navidrome song via vector ANN search."""
    try:
        results = await asyncio.to_thread(
            svc.get_similar_tracks,
            nd_song_id=body.song_id,
            count=body.count,
            backbone_id=body.backbone_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SimilarTracksResponse(
        songs=[
            SongResult(
                id=r["nd_id"],
                name=r["name"],
                artist=r["artist"],
                album=r["album"],
                score=r["score"],
            )
            for r in results
        ],
    )


@router.post("/sync-songs", dependencies=[Depends(verify_key)])
async def navidrome_sync_songs(
    svc: Annotated[NavidromeService, Depends(get_navidrome_service)],
) -> SyncSongsResponse:
    """Trigger a full Navidrome song map sync."""
    try:
        result = await asyncio.to_thread(svc.sync_song_map)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SyncSongsResponse(
        total_songs=result["total_songs"],
        resolved=result["resolved"],
        unresolved=result["unresolved"],
        duration_ms=result["duration_ms"],
    )
