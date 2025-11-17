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
        config_service = application.get_service("config")
        config = config_service.get_config()

        # Get user-editable config values
        # Some from DB meta, some from config dict
        worker_enabled = db.meta.get("worker_enabled")
        if worker_enabled is None:
            worker_enabled = str(config.get("worker_enabled", True)).lower()

        return {
            # Tag writing settings
            "namespace": config.get("namespace", "essentia"),
            "version_tag": config.get("version_tag", "essentia_at_version"),
            "overwrite_tags": config.get("overwrite_tags", True),
            # Processing rules
            "min_duration_s": config.get("min_duration_s", 7),
            "allow_short": config.get("allow_short", False),
            # Worker settings
            "worker_enabled": worker_enabled == "true",
            "worker_count": config.get("worker_count", 1),
            "poll_interval": config.get("poll_interval", 2),
            "cleanup_age_hours": config.get("cleanup_age_hours", 168),
            # API settings
            "blocking_mode": config.get("blocking_mode", True),
            "blocking_timeout": config.get("blocking_timeout", 3600),
            # Cache settings
            "cache_idle_timeout": config.get("cache_idle_timeout", 300),
            "cache_auto_evict": config.get("cache_auto_evict", True),
            # Library settings
            "library_path": config.get("library_path", ""),
            "library_scan_poll_interval": config.get("library_scan_poll_interval", 10),
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
    worker_enabled also updates immediately for live effect.
    """
    try:
        key = request.key
        value = request.value

        # Validate key is user-editable
        editable_keys = {
            "namespace",
            "version_tag",
            "overwrite_tags",
            "min_duration_s",
            "allow_short",
            "worker_enabled",
            "worker_count",
            "poll_interval",
            "cleanup_age_hours",
            "blocking_mode",
            "blocking_timeout",
            "cache_idle_timeout",
            "cache_auto_evict",
            "library_path",
            "library_scan_poll_interval",
        }

        if key not in editable_keys:
            raise HTTPException(status_code=400, detail=f"Config key '{key}' is not editable")

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
