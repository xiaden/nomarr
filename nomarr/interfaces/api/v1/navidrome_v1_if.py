"""Navidrome v1 API endpoints for integration use.

Routes: /v1/navidrome/similar-track, /v1/navidrome/playlist/generate.
Auth: API key (verify_key).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nomarr.helpers.dto.navidrome_dto import TrackPlayData
from nomarr.helpers.exceptions import MisconfiguredError
from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.web.dependencies import get_navidrome_service
from nomarr.services.domain.navidrome_svc import NavidromeService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["navidrome"], prefix="/v1/navidrome")


class SimilarTracksRequest(BaseModel):
    """Request body for similar tracks endpoint."""

    seed: SeedTrackDescriptor
    count: int = Field(default=50, ge=1, le=500)
    backbone_id: str = "effnet"


class SeedTrackDescriptor(BaseModel):
    """Portable track descriptor used for plugin-side Navidrome resolution."""

    title: str = ""
    artist: str
    album: str = ""
    album_artist: str = ""
    duration_ms: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    year: int | None = None
    nomarr_file_key: str | None = None


class SongDescriptor(SeedTrackDescriptor):
    """Portable descriptor plus similarity score."""

    score: float


class SimilarTracksResponse(BaseModel):
    """Response for similar tracks endpoint."""

    songs: list[SongDescriptor]


@router.post("/similar-track", dependencies=[Depends(verify_key)])
async def navidrome_similar_tracks(
    body: SimilarTracksRequest,
    svc: Annotated[NavidromeService, Depends(get_navidrome_service)],
) -> SimilarTracksResponse:
    """Find tracks similar to a Navidrome song via vector ANN search."""
    logger.info(
        "[navidrome] similar-track request: title=%r artist=%r count=%d backbone=%s",
        body.seed.title,
        body.seed.artist,
        body.count,
        body.backbone_id,
    )
    try:
        results = await asyncio.to_thread(
            svc.get_similar_tracks,
            seed_descriptor=body.seed.model_dump(),
            count=body.count,
            backbone_id=body.backbone_id,
        )
    except ValueError as exc:
        logger.warning(
            "[navidrome] similar-track seed unresolved: title=%r artist=%r error=%s",
            body.seed.title,
            body.seed.artist,
            exc,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception(
            "[navidrome] similar-track unexpected error: title=%r artist=%r",
            body.seed.title,
            body.seed.artist,
        )
        raise

    return SimilarTracksResponse(
        songs=[
            SongDescriptor(
                title=r["title"],
                artist=r["artist"],
                album=r["album"],
                album_artist=r["album_artist"],
                duration_ms=r["duration_ms"],
                track_number=r["track_number"],
                disc_number=r["disc_number"],
                year=r["year"],
                nomarr_file_key=r["nomarr_file_key"],
                score=r["score"],
            )
            for r in results
        ],
    )


class TrackPlayInput(BaseModel):
    """Play history entry provided by the Navidrome plugin.

    ``file_id`` is the full ArangoDB document ID (e.g. ``library_files/<key>``)
    that the plugin resolves from a ``nomarr_file_key`` received in prior
    descriptor responses.
    """

    file_id: str
    playcount: int = Field(ge=0)
    last_played: int | None = None


class GeneratePlaylistsRequest(BaseModel):
    """Request body for personal playlist generation."""

    user_id: str
    top_plays: list[TrackPlayInput]
    max_songs: int | None = None
    enabled_types: list[str] | None = None
    min_songs: int | None = None
    max_genre_playlists: int | None = Field(default=None, ge=1, le=25)


class PlaylistResultResponse(BaseModel):
    """A single generated playlist in the response."""

    playlist_type: str
    playlist_name: str
    songs: list[SeedTrackDescriptor]
    track_count: int


class GeneratePlaylistsResponse(BaseModel):
    """Response for personal playlist generation."""

    status: str = "ok"
    message: str = ""
    playlists: list[PlaylistResultResponse]


@router.post("/playlist/generate", dependencies=[Depends(verify_key)])
async def navidrome_generate_playlists(
    body: GeneratePlaylistsRequest,
    svc: Annotated[NavidromeService, Depends(get_navidrome_service)],
) -> GeneratePlaylistsResponse:
    """Generate personal playlists for a Navidrome user.

    Accepts play history from the plugin as ``top_plays`` and returns
    portable track descriptors the plugin resolves to Navidrome mediafile IDs.
    """
    # Convert Pydantic models to TrackPlayData TypedDicts
    top_plays: list[TrackPlayData] = [
        TrackPlayData(
            file_id=p.file_id,
            playcount=p.playcount,
            last_played=p.last_played,
        )
        for p in body.top_plays
    ]

    logger.info(
        "[navidrome] playlist/generate request: user_id=%s top_plays=%d enabled_types=%s max_songs=%s",
        body.user_id,
        len(top_plays),
        body.enabled_types,
        body.max_songs,
    )
    try:
        result = await asyncio.to_thread(
            svc.generate_playlists,
            user_id=body.user_id,
            top_plays=top_plays,
            enabled_types=body.enabled_types,
            max_songs=body.max_songs,
            min_songs=body.min_songs,
            max_genre_playlists=body.max_genre_playlists,
        )
    except MisconfiguredError as exc:
        raise HTTPException(
            status_code=422,
            detail={"status": "misconfigured", "message": str(exc)},
        ) from exc

    if result.status == "misconfigured":
        raise HTTPException(
            status_code=422,
            detail={"status": result.status, "message": result.message},
        )

    if result.status == "no_data":
        return GeneratePlaylistsResponse(
            status=result.status,
            message=result.message,
            playlists=[],
        )

    # Resolve internal file_ids to portable descriptors for plugin-side
    # Navidrome mediafile-ID resolution.
    all_file_ids = list({fid for playlist in result.playlists for fid in playlist["file_ids"]})
    descriptor_map = await asyncio.to_thread(svc.resolve_files_to_descriptors, all_file_ids) if all_file_ids else {}

    return GeneratePlaylistsResponse(
        status=result.status,
        message=result.message,
        playlists=[
            PlaylistResultResponse(
                playlist_type=playlist["playlist_type"],
                playlist_name=playlist["playlist_name"],
                songs=[
                    SeedTrackDescriptor(**descriptor_map[fid]) for fid in playlist["file_ids"] if fid in descriptor_map
                ],
                track_count=len([fid for fid in playlist["file_ids"] if fid in descriptor_map]),
            )
            for playlist in result.playlists
        ],
    )
