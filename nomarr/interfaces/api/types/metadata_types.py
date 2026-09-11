"""Pydantic models for metadata entity API responses."""

from pydantic import BaseModel, Field

from nomarr.helpers.dto.metadata_dto import EntityDict, EntityListResult, SongListForEntityResult


class EntityResponse(BaseModel):
    """Single entity response."""

    entity_id: int | str = Field(description="Entity natural value or external handle")
    display_name: str = Field(description="Exact raw string for display")
    song_count: int | None = Field(None, description="Optional: count of songs for this entity")

    @classmethod
    def from_dto(cls, dto: EntityDict) -> "EntityResponse":
        return cls(
            entity_id=dto["id"],
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

    song_ids: list[str] = Field(description="Opaque SongLocator tokens")
    total: int = Field(description="Total count (before pagination)")
    limit: int
    offset: int

    @classmethod
    def from_dto(cls, dto: SongListForEntityResult) -> "SongListResponse":
        return cls(
            song_ids=list(dto["song_ids"]),
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
