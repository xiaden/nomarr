"""Metadata entity API endpoints for web UI (session-authenticated).

Routes: /api/web/metadata/*
Provides entity listing, song-entity relationships, and traversal queries
for the web frontend using session authentication.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id
from nomarr.interfaces.api.types.metadata_types import (
    EntityCountsResponse,
    EntityListResponse,
    EntityResponse,
    SongListResponse,
)
from nomarr.interfaces.api.web.dependencies import get_metadata_service
from nomarr.services.domain.metadata_svc import MetadataService

# Router instance (will be included under /api/web/metadata)
router = APIRouter(tags=["metadata"], prefix="/metadata")

# Type alias for entity collection names
EntityCollection = Literal["artists", "albums", "labels", "genres", "years"]


# ----------------------------------------------------------------------
#  GET /metadata/counts
# ----------------------------------------------------------------------
@router.get("/counts", dependencies=[Depends(verify_session)])
async def get_entity_counts(
    metadata_service: Annotated[MetadataService, Depends(get_metadata_service)],
) -> EntityCountsResponse:
    """Get total counts for all entity collections (artists, albums, etc.)."""
    counts = metadata_service.get_entity_counts()
    return EntityCountsResponse(**counts)


# ----------------------------------------------------------------------
#  GET /metadata/{collection}
# ----------------------------------------------------------------------
@router.get("/{collection}", dependencies=[Depends(verify_session)])
async def list_entities(
    collection: EntityCollection,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(description="Substring search on display_name")] = None,
    metadata_service: MetadataService = Depends(get_metadata_service),
) -> EntityListResponse:
    """List entities from a collection (artists, albums, labels, genres, years)."""
    result = metadata_service.list_entities(collection, limit=limit, offset=offset, search=search)
    return EntityListResponse.from_dto(result)


# ----------------------------------------------------------------------
#  GET /metadata/{collection}/{entity_id}
# ----------------------------------------------------------------------
@router.get("/{collection}/{entity_id}", dependencies=[Depends(verify_session)])
async def get_entity(
    collection: EntityCollection,
    entity_id: str,
    metadata_service: Annotated[MetadataService, Depends(get_metadata_service)],
) -> EntityResponse:
    """Get entity details by _id.

    Note: entity_id should be encoded (e.g., artists:v1_abc123).
    Collection parameter is informational only (entity_id already contains collection).
    """
    entity_id = decode_path_id(entity_id)
    entity = metadata_service.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityResponse.from_dto(entity)


# ----------------------------------------------------------------------
#  GET /metadata/{collection}/{entity_id}/songs
# ----------------------------------------------------------------------
@router.get("/{collection}/{entity_id}/songs", dependencies=[Depends(verify_session)])
async def list_songs_for_entity(
    collection: EntityCollection,
    entity_id: str,
    rel: Annotated[str, Query(description="Relation type (artist, artists, album, label, genres, year)")],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    metadata_service: MetadataService = Depends(get_metadata_service),
) -> SongListResponse:
    """List songs connected to an entity.

    Example: GET /metadata/artists/artists:v1_abc.../songs?rel=artist
    Returns all songs where this artist is the primary credited artist.
    """
    entity_id = decode_path_id(entity_id)
    result = metadata_service.list_songs_for_entity(entity_id, rel, limit=limit, offset=offset)
    return SongListResponse.from_dto(result)


# ----------------------------------------------------------------------
#  GET /metadata/albums/{album_id}/artists
# ----------------------------------------------------------------------
@router.get("/albums/{album_id}/artists", dependencies=[Depends(verify_session)])
async def list_artists_for_album(
    album_id: str,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    metadata_service: MetadataService = Depends(get_metadata_service),
) -> list[EntityResponse]:
    """List artists for an album via traversal (album→songs→artists).

    Returns deduplicated artists sorted by display_name.
    """
    album_id = decode_path_id(album_id)
    artists = metadata_service.list_artists_for_album(album_id, limit=limit)
    return [EntityResponse.from_dto(a) for a in artists]


# ----------------------------------------------------------------------
#  GET /metadata/artists/{artist_id}/albums
# ----------------------------------------------------------------------
@router.get("/artists/{artist_id}/albums", dependencies=[Depends(verify_session)])
async def list_albums_for_artist(
    artist_id: str,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    metadata_service: MetadataService = Depends(get_metadata_service),
) -> list[EntityResponse]:
    """List albums for an artist via traversal (artist→songs→albums).

    Returns deduplicated albums sorted by display_name.
    Each album includes song_count (number of songs by this artist on that album).
    """
    artist_id = decode_path_id(artist_id)
    albums = metadata_service.list_albums_for_artist(artist_id, limit=limit)
    return [EntityResponse.from_dto(a) for a in albums]
