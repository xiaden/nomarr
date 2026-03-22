"""Pydantic response models for API key endpoints."""

from pydantic import BaseModel, Field


class ApiKeyResponse(BaseModel):
    """Response containing the Nomarr API key."""

    api_key: str = Field(..., description="The API key for external integrations")
