"""
Pydantic models for API request/response schemas.
"""

from __future__ import annotations

from pydantic import BaseModel


# Public API request models
class TagRequest(BaseModel):
    """Request to tag a single audio file."""

    path: str
    force: bool | None = False


class RemoveJobRequest(BaseModel):
    """Request to remove a specific job from the queue."""

    job_id: int


class FlushRequest(BaseModel):
    """Request to flush jobs by status."""

    statuses: list[str] | None = None  # e.g., ["pending","error"]; None => default


# Legacy processing request models (kept for backward compatibility)
# These were originally for internal API endpoints (now deleted)
class InternalProcessRequest(BaseModel):
    """Request to process a file (legacy model)."""

    path: str
    force: bool | None = False


class InternalBatchRequest(BaseModel):
    """Request to process multiple files (legacy model)."""

    paths: list[str]
    force: bool | None = False
