"""Configuration management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.config_types import (
    ConfigResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
)
from nomarr.interfaces.api.web.dependencies import get_config_service, get_worker_service

if TYPE_CHECKING:
    from nomarr.services.config_svc import ConfigService

router = APIRouter(prefix="/config", tags=["Config"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("")
def get_config(
    _session: dict = Depends(verify_session),
    config_service: Any = Depends(get_config_service),
    worker_service: Any | None = Depends(get_worker_service),
) -> ConfigResponse:
    """Get current configuration values (user-editable subset)."""
    try:
        result = config_service.get_config_for_web(worker_service=worker_service)
        return ConfigResponse.from_dto(result)
    except Exception as e:
        logging.exception("[Web API] Error getting config")
        raise HTTPException(status_code=500, detail=f"Error getting config: {e}") from e


@router.post("")
def update_config(
    request: ConfigUpdateRequest,
    _session: dict = Depends(verify_session),
    config_service: "ConfigService" = Depends(get_config_service),
) -> ConfigUpdateResponse:
    """
    Update a configuration value in the database.

    Changes are stored in the DB meta table and will override YAML/env config on restart.
    Only user-configurable keys can be updated.
    Note: library_root is infrastructure-level config, use /api/library/libraries endpoints instead.
    """
    try:
        key = request.key
        value = request.value

        # Whitelist of user-editable keys (matches config surface)
        # Note: library_root excluded - use libraries API for multi-library management
        editable_keys = {
            "models_dir",
            "db_path",
            "library_auto_tag",
            "library_ignore_patterns",
            "file_write_mode",
            "overwrite_tags",
            "admin_password",
            "cache_idle_timeout",
            "worker_count",
            "calibrate_heads",
            "calibration_repo",
        }

        if key not in editable_keys:
            raise HTTPException(status_code=400, detail=f"Config key '{key}' is not editable (internal constant)")

        # Store in DB meta via ConfigService
        config_service.set_config_value(key, value)

        return ConfigUpdateResponse(
            status="success",
            message=f"Config '{key}' updated. Use 'Restart Server' for changes to take full effect.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error updating config")
        raise HTTPException(status_code=500, detail=f"Error updating config: {e}") from e
