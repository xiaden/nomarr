"""Config API types - Pydantic models for Config domain.

External API contracts for configuration endpoints.
These models are thin adapters around DTOs from helpers/dto/config_dto.py.

Architecture:
- ConfigResult DTO is intentionally a thin wrapper around dict[str, Any]
- This prevents cascading changes when config keys are added/removed
- ConfigResponse uses Pydantic's extra="allow" to accept arbitrary fields
- Services continue using DTOs (no Pydantic imports in services layer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from nomarr.helpers.dto.config_dto import WebConfigResult

# ──────────────────────────────────────────────────────────────────────
# Response Models
# ──────────────────────────────────────────────────────────────────────


class ConfigResponse(BaseModel):
    """Pydantic model for configuration response.

    Intentionally flexible to accept arbitrary config keys without schema changes.
    The underlying DTO is a thin dict wrapper by design.
    """

    model_config = ConfigDict(extra="allow")

    @classmethod
    def from_dto(cls, result: WebConfigResult) -> ConfigResponse:
        """Create ConfigResponse from WebConfigResult DTO.

        Args:
            result: WebConfigResult with config, internal_info, and worker_enabled

        Returns:
            ConfigResponse: Merged config with all fields flattened

        """
        # Merge config dict with internal info fields
        merged = {
            **result.config,
            "namespace": result.internal_info.namespace,
            "version_tag": result.internal_info.version_tag,
            "min_duration_s": result.internal_info.min_duration_s,
            "allow_short": result.internal_info.allow_short,
            "poll_interval": result.internal_info.poll_interval,
            "library_scan_poll_interval": result.internal_info.library_scan_poll_interval,
            "worker_enabled": result.worker_enabled,
        }
        return cls(**merged)


class ConfigUpdateResponse(BaseModel):
    """Response for config update endpoint."""

    status: str = Field(..., description="Update status")
    message: str = Field(..., description="Status message")


# ──────────────────────────────────────────────────────────────────────
# Request Models
# ──────────────────────────────────────────────────────────────────────


class ConfigUpdateRequest(BaseModel):
    """Request model for updating configuration values."""

    key: str = Field(..., description="Configuration key to update")
    value: str = Field(..., description="New configuration value")
