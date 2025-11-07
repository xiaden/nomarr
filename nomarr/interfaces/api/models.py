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


# Internal API request models
class InternalProcessRequest(BaseModel):
    """Request to process a file via internal API."""

    path: str
    force: bool | None = False


class InternalBatchRequest(BaseModel):
    """Request to process multiple files via internal API."""

    paths: list[str]
    force: bool | None = False
