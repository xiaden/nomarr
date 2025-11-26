"""Configuration management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies_if import get_config_service, get_worker_service

if TYPE_CHECKING:
    from nomarr.services.config_svc import ConfigService

router = APIRouter(prefix="/config", tags=["Config"])


# ──────────────────────────────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────────────────────────────


class ConfigUpdateRequest(BaseModel):
    """Request model for updating configuration values."""

    key: str
    value: str


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("")
def get_config(
    _session: dict = Depends(verify_session),
    config_service: Any = Depends(get_config_service),
    worker_service: Any | None = Depends(get_worker_service),
) -> dict[str, Any]:
    """Get current configuration values (user-editable subset)."""
    try:
        # Get internal constants from service
        internal_info = config_service.get_internal_info()

        config = config_service.get_config()

        # User-editable config from DB or config dict
        worker_enabled = worker_service.is_enabled() if worker_service else internal_info["worker_enabled"]

        return {
            # User-configurable settings
            "models_dir": config.get("models_dir", "/app/models"),
            "db_path": config.get("db_path", ""),
            "library_root": config.get("library_root", ""),
            "library_auto_tag": config.get("library_auto_tag", True),
            "library_ignore_patterns": config.get("library_ignore_patterns", ""),
            "file_write_mode": config.get("file_write_mode", "minimal"),
            "overwrite_tags": config.get("overwrite_tags", True),
            "admin_password": config.get("admin_password", ""),
            "cache_idle_timeout": config.get("cache_idle_timeout", 300),
            "worker_count": config.get("worker_count", 1),
            "calibrate_heads": config.get("calibrate_heads", False),
            "calibration_repo": config.get("calibration_repo", "https://github.com/xiaden/nom-cal"),
            # Internal constants (read-only, displayed for info)
            "namespace": internal_info["namespace"],
            "version_tag": internal_info["version_tag"],
            "min_duration_s": internal_info["min_duration_s"],
            "allow_short": internal_info["allow_short"],
            "worker_enabled": worker_enabled,
            "poll_interval": internal_info["poll_interval"],
            "library_scan_poll_interval": internal_info["library_scan_poll_interval"],
        }

    except Exception as e:
        logging.exception("[Web API] Error getting config")
        raise HTTPException(status_code=500, detail=f"Error getting config: {e}") from e


@router.post("")
def update_config(
    request: ConfigUpdateRequest,
    _session: dict = Depends(verify_session),
    config_service: "ConfigService" = Depends(get_config_service),
) -> dict[str, Any]:
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

        return {
            "success": True,
            "message": f"Config '{key}' updated. Use 'Restart Server' for changes to take full effect.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error updating config")
        raise HTTPException(status_code=500, detail=f"Error updating config: {e}") from e
