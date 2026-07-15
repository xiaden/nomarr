"""TypedDict DTOs for the EmbeddingStreamRepository return types.

These mirror the SQLAlchemy ``MlEmbeddingStream`` model columns from
Part A and provide type-safe return types for embedding stream
repository methods.  Import only from ``typing``.
"""

from __future__ import annotations

from typing import TypedDict


class EmbeddingStreamRecord(TypedDict):
    """Single row from the ``ml_embedding_streams`` table."""

    id: int
    file_id: int
    backbone: str
    patches_emb: bytes
    created_at: int
    updated_at: int | None


__all__ = ["EmbeddingStreamRecord"]
