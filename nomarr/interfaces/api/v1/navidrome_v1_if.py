"""Navidrome v1 API endpoints for integration use.

Routes: /v1/navidrome/similar-tracks, /v1/navidrome/sync-songs.
Auth: API key (verify_key).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
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
    """Trigger a full Navidrome song sync to graph collections."""
    try:
        result = await asyncio.to_thread(svc.sync_navidrome)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SyncSongsResponse(
        total_songs=result["total_songs"],
        resolved=result["resolved"],
        unresolved=result["unresolved"],
        tracks_upserted=result["tracks_upserted"],
        play_edges_upserted=result["play_edges_upserted"],
        orphans_removed=result["orphans_removed"],
        duration_ms=result["duration_ms"],
    )


# ------------------------------------------------------------------
# Scrobble models
# ------------------------------------------------------------------


class ScrobbleTrack(BaseModel):
    """Track identification from a scrobble event."""

    id: str
    title: str = ""
    duration: float = 0.0


class ScrobbleRequest(BaseModel):
    """Scrobble request body (Navidrome Scrobbler plugin format).

    ``timestamp`` is epoch seconds (Navidrome convention).
    """

    username: str
    track: ScrobbleTrack
    timestamp: int


@router.post("/scrobble", dependencies=[Depends(verify_key)], status_code=204)
async def navidrome_scrobble(
    body: ScrobbleRequest,
    svc: Annotated[NavidromeService, Depends(get_navidrome_service)],
) -> Response:
    """Ingest a real-time scrobble event from Navidrome."""
    timestamp_ms = body.timestamp * 1000
    await asyncio.to_thread(
        svc.ingest_scrobble,
        user_id=body.username,
        nd_id=body.track.id,
        timestamp_ms=timestamp_ms,
    )
    return Response(status_code=204)


# ------------------------------------------------------------------
# Playlist generation models
# ------------------------------------------------------------------


class GeneratePlaylistsRequest(BaseModel):
    """Request body for personal playlist generation."""

    user_id: str
    max_songs: int | None = None
    enabled_types: list[str] | None = None
    min_songs: int | None = None


class PlaylistResultResponse(BaseModel):
    """A single generated playlist in the response."""

    playlist_type: str
    playlist_name: str
    track_nd_ids: list[str]
    track_count: int


class GeneratePlaylistsResponse(BaseModel):
    """Response for personal playlist generation."""

    playlists: list[PlaylistResultResponse]


# ------------------------------------------------------------------
# Playlist generation endpoint
# ------------------------------------------------------------------


@router.post("/generate-playlists", dependencies=[Depends(verify_key)])
async def navidrome_generate_playlists(
    body: GeneratePlaylistsRequest,
    svc: Annotated[NavidromeService, Depends(get_navidrome_service)],
) -> GeneratePlaylistsResponse:
    """Generate personal playlists for a Navidrome user."""
    results = await asyncio.to_thread(
        svc.generate_playlists,
        user_id=body.user_id,
        enabled_types=body.enabled_types,
        max_songs=body.max_songs,
        min_songs=body.min_songs,
    )

    # Resolve internal file_ids to Navidrome track IDs (external concern).
    all_file_ids = list({fid for r in results for fid in r["file_ids"]})
    nd_map = await asyncio.to_thread(svc.resolve_files_to_nd, all_file_ids)

    return GeneratePlaylistsResponse(
        playlists=[
            PlaylistResultResponse(
                playlist_type=r["playlist_type"],
                playlist_name=r["playlist_name"],
                track_nd_ids=[nd_map[fid] for fid in r["file_ids"] if fid in nd_map],
                track_count=len([fid for fid in r["file_ids"] if fid in nd_map]),
            )
            for r in results
        ],
    )
