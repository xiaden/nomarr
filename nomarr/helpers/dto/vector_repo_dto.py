"""TypedDict DTOs for the VectorRepo return types.

These mirror the SQLAlchemy ``Embedding`` model columns from Part A and
provide type-safe return types for vector repository methods.  Import
only from ``typing``.

These DTOs are PERSISTENCE-INTERNAL ONLY.  The corrected caller-facing vector
read surface returns the domain types ``SongVector``/``VectorMatch``/\
``EmbeddingCounts`` from ``nomarr.helpers.dataclasses.vector_dataclass``; no
``EmbeddingRecord``/``SimilarResult`` may cross ``MlDb`` or reach callers on the
typed read paths.  This module is retained for the write path
(``insert_embedding`` RETURNING mapping) and the retained legacy
``list_song_vectors``/``search_vectors`` dependency-gate methods that still
delegate to the storage-shaped repo reads.
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
    """Result from an ANN search with cosine similarity in ``[-1, 1]``.

    The persistence layer converts pgvector's cosine distance with the single
    canonical formula ``similarity = clamp(1 - distance, -1, 1)``. ``distance``
    remains available for repository diagnostics; consumers filter and rank by
    ``score``.
    """

    song_id: int
    backbone_id: str
    distance: float
    score: float


__all__ = ["EmbeddingRecord", "SimilarResult"]
