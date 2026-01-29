"""Processing API response types.

External API contracts for processing and worker endpoints.
These are Pydantic models that transform internal DTOs into API responses.

Architecture:
- These types are owned by the interface layer
- They define what external clients see (REST API shapes)
- They transform internal DTOs via .from_dto() classmethods
- Services and lower layers should NOT import from this module
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel

if TYPE_CHECKING:
    from nomarr.helpers.dto.processing_dto import (
        ProcessFileResult,
    )

# ──────────────────────────────────────────────────────────────────────
# Processing Response Types (DTO → Pydantic mappings)
# ──────────────────────────────────────────────────────────────────────


class ProcessFileResponse(BaseModel):
    """Response for process file operation.

    Maps to ProcessFileResult DTO from helpers/dto/processing_dto.py
    """

    file_path: str
    elapsed: float
    duration: float | None
    heads_processed: int
    tags_written: int
    head_results: dict[str, dict[str, Any]]
    mood_aggregations: dict[str, int] | None
    tags: dict[str, Any]

    @classmethod
    def from_dto(cls, result: ProcessFileResult) -> Self:
        """Transform internal ProcessFileResult DTO to external API response.

        Args:
            result: Internal process result from workflow

        Returns:
            API response model

        """
        return cls(
            file_path=result.file_path,
            elapsed=result.elapsed,
            duration=result.duration,
            heads_processed=result.heads_processed,
            tags_written=result.tags_written,
            head_results=result.head_results,
            mood_aggregations=result.mood_aggregations,
            tags=result.tags.to_dict(),
        )


# ──────────────────────────────────────────────────────────────────────
# Processing Request Types
# ──────────────────────────────────────────────────────────────────────


class ProcessFileRequest(BaseModel):
    """Request to process a single file."""

    path: str
    force: bool = False


class BatchProcessRequest(BaseModel):
    """Request to batch process multiple paths."""

    paths: list[str]
    force: bool = False


# ──────────────────────────────────────────────────────────────────────
# Batch Processing Response Types
# ──────────────────────────────────────────────────────────────────────


class BatchPathResult(BaseModel):
    """Result for a single path in batch processing."""

    path: str
    status: str
    message: str


class BatchProcessResponse(BaseModel):
    """Response from batch processing operation."""

    queued: int
    skipped: int
    errors: int
    results: list[BatchPathResult]
