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
from nomarr.interfaces.api.web.dependencies import get_config_service

if TYPE_CHECKING:
    from nomarr.services.infrastructure.config_svc import ConfigService

router = APIRouter(prefix="/config", tags=["Config"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("")
def get_config(
    _session: dict = Depends(verify_session),
    config_service: Any = Depends(get_config_service),
) -> ConfigResponse:
    """Get current configuration values (Web UI editable subset only)."""
    try:
        result = config_service.get_config_for_web(worker_service=None)

        # Only return Web UI appropriate config fields (runtime settings)
        # Infrastructure paths excluded - must be set via config.yaml or env vars
        editable_keys = {
            "file_write_mode",
            "overwrite_tags",
            "library_auto_tag",
            "library_ignore_patterns",
            "tagger_worker_count",
            "cache_idle_timeout",
            "calibrate_heads",
            "calibration_repo",
            "admin_password",
        }

        # Filter config dict to only editable keys
        filtered_config = {k: v for k, v in result.config.items() if k in editable_keys}

        # Create filtered result
        from nomarr.helpers.dto.config_dto import WebConfigResult

        filtered_result = WebConfigResult(
            config=filtered_config,
            internal_info=result.internal_info,
            worker_enabled=result.worker_enabled,
        )

        return ConfigResponse.from_dto(filtered_result)
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
    Only runtime settings appropriate for Web UI can be updated.
    Infrastructure paths (models_dir, db_path, library_root) must be set via config file.
    """
    try:
        key = request.key
        value = request.value

        # Whitelist of Web UI editable keys (runtime settings only)
        # Infrastructure paths excluded - must be set via config.yaml or env vars
        editable_keys = {
            "file_write_mode",
            "overwrite_tags",
            "library_auto_tag",
            "library_ignore_patterns",
            "tagger_worker_count",
            "cache_idle_timeout",
            "calibrate_heads",
            "calibration_repo",
            "admin_password",
        }

        if key not in editable_keys:
            raise HTTPException(
                status_code=400,
                detail=f"Config key '{key}' cannot be edited via Web UI (set via config file or environment)",
            )

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
