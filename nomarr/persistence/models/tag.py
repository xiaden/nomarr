"""Pydantic models for tag-related ArangoDB documents and edges."""

from pydantic import Field

from nomarr.persistence.models.base import ArangoDocument, ArangoEdge


class Tag(ArangoDocument):
    """Tag vertex document.

    Represents a tag in the unified tag schema (name, value pairs).
    Examples: genre/rock, year/2023, mood/energetic
    """

    name: str = Field(..., description="Tag relation type (e.g., 'genre', 'year', 'mood')")
    value: str | int | float | bool = Field(..., description="Tag value")


class SongHasTagsEdge(ArangoEdge):
    """Edge from library_files to tags.

    Bare edge with no additional properties — only _from/_to.
    Used for song→tag relationships.
    """
