"""Vector API request/response models.

Pydantic models for vector search and maintenance endpoints.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VectorSearchRequest(BaseModel):
    """Request model for vector similarity search."""

    backbone_id: str = Field(
        ..., description="Backbone identifier (e.g., 'effnet', 'yamnet')"
    )
    vector: list[float] = Field(..., description="Query embedding vector")
    limit: int = Field(10, description="Maximum number of results", ge=1, le=100)
    min_score: float = Field(
        0.0, description="Minimum similarity score threshold", ge=0.0
    )


class VectorSearchResultItem(BaseModel):
    """Single vector search result."""

    file_id: str = Field(..., description="Library file document ID")
    score: float = Field(..., description="Similarity score")
    vector: list[float] = Field(..., description="Stored embedding vector")


class VectorSearchResponse(BaseModel):
    """Response model for vector similarity search."""

    results: list[VectorSearchResultItem] = Field(
        ..., description="List of matching vectors"
    )


class VectorHotColdStats(BaseModel):
    """Hot/cold statistics for a single backbone."""

    backbone_id: str = Field(..., description="Backbone identifier")
    hot_count: int = Field(..., description="Number of vectors in hot collection")
    cold_count: int = Field(
        ..., description="Number of vectors in cold collection"
    )
    index_exists: bool = Field(
        ..., description="Whether cold collection has vector index"
    )


class VectorStatsResponse(BaseModel):
    """Response model for vector stats endpoint."""

    stats: list[VectorHotColdStats] = Field(
        ..., description="Stats for all backbones"
    )


class VectorPromoteRequest(BaseModel):
    """Request model for promote & rebuild operation."""

    backbone_id: str = Field(
        ..., description="Backbone identifier (e.g., 'effnet', 'yamnet')"
    )
    nlists: int | None = Field(
        None,
        description="Number of HNSW graph lists (auto-calculated if omitted)",
        ge=10,
        le=100,
    )


class VectorPromoteResponse(BaseModel):
    """Response model for promote & rebuild operation."""

    status: str = Field(..., description="Operation status")
    backbone_id: str = Field(..., description="Backbone identifier")
    message: str = Field(..., description="Human-readable result message")


class VectorGetResponse(BaseModel):
    """Response model for get track vector endpoint."""

    file_id: str = Field(..., description="Library file document ID")
    backbone_id: str = Field(..., description="Backbone identifier")
    vector: list[float] = Field(..., description="Embedding vector")
