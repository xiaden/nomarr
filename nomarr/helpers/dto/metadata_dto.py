"""DTOs for metadata entity navigation (hybrid entity graph)."""

from typing import TypedDict


class EntityDict(TypedDict):
    """Entity result (artist, album, genre, label, year)."""

    _id: str  # ArangoDB _id (e.g., "artists/v1_abc123...")
    _key: str  # ArangoDB _key (e.g., "v1_abc123...")
    display_name: str  # Exact raw string
    song_count: int | None  # Optional: count of songs for this entity


class EntityListResult(TypedDict):
    """Result for list_entities()."""

    entities: list[EntityDict]
    total: int
    limit: int
    offset: int


class SongListForEntityResult(TypedDict):
    """Result for list_songs_for_entity()."""

    song_ids: list[str]  # Song _ids
    total: int
    limit: int
    offset: int
