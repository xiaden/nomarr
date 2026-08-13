"""TypedDict DTOs for the VectorRepo return types.

These mirror the SQLAlchemy ``Embedding`` model columns from Part A and
provide type-safe return types for vector repository methods.  Import
only from ``typing``.
"""

from __future__ import annotations

from typing import TypedDict


class EmbeddingRecord(TypedDict):
    """Single row from the ``embeddings`` table."""

    id: int
    song_id: int
    backbone_id: str
    tier: str
    embed_dim: int
    model_suite_hash: str | None
    num_segments: int | None
    segmentation_hash: str | None
    genres: list[str] | None
    created_at: int
    updated_at: int


class SimilarResult(TypedDict):
    """Result from an ANN similarity search."""

    song_id: int
    backbone_id: str
    distance: float


__all__ = ["EmbeddingRecord", "SimilarResult"]
