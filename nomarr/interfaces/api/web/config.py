"""Configuration management endpoints for web UI."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_database
from nomarr.persistence.db import Database

router = APIRouter(prefix="/api/config", tags=["Config"])


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
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Get current configuration values (user-editable subset)."""
    from nomarr.app import application

    try:
        from nomarr.services.config import (
            INTERNAL_ALLOW_SHORT,
            INTERNAL_BLOCKING_MODE,
            INTERNAL_BLOCKING_TIMEOUT,
            INTERNAL_LIBRARY_SCAN_POLL_INTERVAL,
            INTERNAL_MIN_DURATION_S,
            INTERNAL_NAMESPACE,
            INTERNAL_POLL_INTERVAL,
            INTERNAL_VERSION_TAG,
            INTERNAL_WORKER_ENABLED,
        )

        config_service = application.get_service("config")
        config = config_service.get_config()

        # User-editable config from DB or config dict
        worker_enabled = db.meta.get("worker_enabled")
        if worker_enabled is None:
            worker_enabled = str(INTERNAL_WORKER_ENABLED).lower()

        return {
            # User-configurable settings
            "models_dir": config.get("models_dir", "/app/models"),
            "db_path": config.get("db_path", ""),
            "library_path": config.get("library_path", ""),
            "library_auto_tag": config.get("library_auto_tag", True),
            "library_ignore_patterns": config.get("library_ignore_patterns", ""),
            "file_write_mode": config.get("file_write_mode", "minimal"),
            "overwrite_tags": config.get("overwrite_tags", True),
            "admin_password": config.get("admin_password", ""),
            "cache_idle_timeout": config.get("cache_idle_timeout", 300),
            "calibrate_heads": config.get("calibrate_heads", False),
            "calibration_repo": config.get("calibration_repo", "https://github.com/xiaden/nom-cal"),
            # Internal constants (read-only, displayed for info)
            "namespace": INTERNAL_NAMESPACE,
            "version_tag": INTERNAL_VERSION_TAG,
            "min_duration_s": INTERNAL_MIN_DURATION_S,
            "allow_short": INTERNAL_ALLOW_SHORT,
            "worker_enabled": worker_enabled == "true",
            "poll_interval": INTERNAL_POLL_INTERVAL,
            "blocking_mode": INTERNAL_BLOCKING_MODE,
            "blocking_timeout": INTERNAL_BLOCKING_TIMEOUT,
            "library_scan_poll_interval": INTERNAL_LIBRARY_SCAN_POLL_INTERVAL,
        }

    except Exception as e:
        logging.exception("[Web API] Error getting config")
        raise HTTPException(status_code=500, detail=f"Error getting config: {e}") from e


@router.post("")
def update_config(
    request: ConfigUpdateRequest,
    _session: dict = Depends(verify_session),
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """
    Update a configuration value in the database.

    Changes are stored in the DB meta table and will override YAML/env config on restart.
    Only the 11 user-configurable keys can be updated.
    """
    try:
        key = request.key
        value = request.value

        # Whitelist of user-editable keys (matches config surface)
        editable_keys = {
            "models_dir",
            "db_path",
            "library_path",
            "library_auto_tag",
            "library_ignore_patterns",
            "file_write_mode",
            "overwrite_tags",
            "admin_password",
            "cache_idle_timeout",
            "calibrate_heads",
            "calibration_repo",
        }

        if key not in editable_keys:
            raise HTTPException(status_code=400, detail=f"Config key '{key}' is not editable (internal constant)")

        # Store in DB meta (prefixed with "config_")
        # The value will be parsed to correct type when loaded by compose()
        db.meta.set(f"config_{key}", value)

        # Special handling for worker_enabled - also update runtime state
        if key == "worker_enabled":
            db.meta.set("worker_enabled", value)

        return {
            "success": True,
            "message": f"Config '{key}' updated. Use 'Restart Server' for changes to take full effect.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error updating config")
        raise HTTPException(status_code=500, detail=f"Error updating config: {e}") from e
