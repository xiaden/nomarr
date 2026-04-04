"""Pydantic models for ArangoDB persistence layer."""

from nomarr.persistence.models.base import ArangoDocument, ArangoEdge
from nomarr.persistence.models.tag import SongHasTagsEdge, Tag, TagModelOutputEdge

__all__ = [
    "ArangoDocument",
    "ArangoEdge",
    "SongHasTagsEdge",
    "Tag",
    "TagModelOutputEdge",
]
