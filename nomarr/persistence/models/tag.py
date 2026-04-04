"""Pydantic models for tag-related ArangoDB documents and edges."""

from datetime import datetime

from pydantic import Field

from nomarr.persistence.models.base import ArangoDocument, ArangoEdge


class Tag(ArangoDocument):
    """Tag vertex document.

    Represents a tag in the unified tag schema (rel, value pairs).
    Examples: genre/rock, year/2023, mood/energetic
    """

    rel: str = Field(..., description="Tag relation type (e.g., 'genre', 'year', 'mood')")
    value: str | int | float | bool = Field(..., description="Tag value")


class SongHasTagsEdge(ArangoEdge):
    """Edge from library_files to tags.

    Bare edge with no additional properties — only _from/_to.
    Used for song→tag relationships.
    """


class TagModelOutputEdge(ArangoEdge):
    """Edge from tags to ml_model_outputs.

    Links tags to their corresponding ML model output activations.
    """

    score: float = Field(..., description="Activation score from ML model")
    created_at: datetime | None = Field(default=None, description="Edge creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")
