"""Pydantic models for metadata entity API responses."""

from pydantic import BaseModel, Field

from nomarr.helpers.dto.metadata_dto import EntityDict, EntityListResult, SongListForEntityResult
from nomarr.interfaces.api.id_codec import encode_id


class EntityResponse(BaseModel):
    """Single entity response."""

    id: str = Field(description="Entity _id (e.g., 'artists:v1_abc123...')")
    key: str = Field(description="Entity _key")
    display_name: str = Field(description="Exact raw string for display")
    song_count: int | None = Field(None, description="Optional: count of songs for this entity")

    @classmethod
    def from_dto(cls, dto: EntityDict) -> "EntityResponse":
        return cls(
            id=encode_id(dto["_id"]),
            key=dto["_key"],
            display_name=dto["display_name"],
            song_count=dto.get("song_count"),
        )


class EntityListResponse(BaseModel):
    """List of entities response."""

    entities: list[EntityResponse]
    total: int = Field(description="Total count (before pagination)")
    limit: int
    offset: int

    @classmethod
    def from_dto(cls, dto: EntityListResult) -> "EntityListResponse":
        return cls(
            entities=[EntityResponse.from_dto(e) for e in dto["entities"]],
            total=dto["total"],
            limit=dto["limit"],
            offset=dto["offset"],
        )


class SongListResponse(BaseModel):
    """List of songs for an entity."""

    song_ids: list[str] = Field(description="Song _ids (encoded)")
    total: int = Field(description="Total count (before pagination)")
    limit: int
    offset: int

    @classmethod
    def from_dto(cls, dto: SongListForEntityResult) -> "SongListResponse":
        return cls(
            song_ids=[encode_id(sid) for sid in dto["song_ids"]],
            total=dto["total"],
            limit=dto["limit"],
            offset=dto["offset"],
        )


class EntityCountsResponse(BaseModel):
    """Total counts for all entity collections."""

    artists: int
    albums: int
    labels: int
    genres: int
    years: int
