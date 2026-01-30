"""Configuration management endpoints for web UI."""
import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.config_types import ConfigResponse, ConfigUpdateRequest, ConfigUpdateResponse
from nomarr.interfaces.api.web.dependencies import get_config_service

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.infrastructure.config_svc import ConfigService
router = APIRouter(prefix="/config", tags=["Config"])

@router.get("")
def get_config(_session: Annotated[dict, Depends(verify_session)], config_service: Annotated[Any, Depends(get_config_service)]) -> ConfigResponse:
    """Get current configuration values (Web UI editable subset only)."""
    try:
        result = config_service.get_config_for_web(worker_service=None)
        editable_keys = {"file_write_mode", "overwrite_tags", "library_auto_tag", "library_ignore_patterns", "tagger_worker_count", "cache_idle_timeout", "calibrate_heads", "calibration_repo"}
        filtered_config = {k: v for k, v in result.config.items() if k in editable_keys}
        from nomarr.helpers.dto.config_dto import WebConfigResult
        filtered_result = WebConfigResult(config=filtered_config, internal_info=result.internal_info, worker_enabled=result.worker_enabled)
        return ConfigResponse.from_dto(filtered_result)
    except Exception as e:
        logger.exception("[Web API] Error getting config")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get configuration")) from e

@router.post("")
def update_config(request: ConfigUpdateRequest, _session: Annotated[dict, Depends(verify_session)], config_service: Annotated["ConfigService", Depends(get_config_service)]) -> ConfigUpdateResponse:
    """Update a configuration value in the database.

    Changes are stored in the DB meta table and will override YAML/env config on restart.
    Only runtime settings appropriate for Web UI can be updated.
    Infrastructure paths (models_dir, db_path, library_root) must be set via config file.
    """
    try:
        key = request.key
        value = request.value
        editable_keys = {"file_write_mode", "overwrite_tags", "library_auto_tag", "library_ignore_patterns", "tagger_worker_count", "cache_idle_timeout", "calibrate_heads", "calibration_repo"}
        if key not in editable_keys:
            raise HTTPException(status_code=400, detail=f"Config key '{key}' cannot be edited via Web UI (set via config file or environment)")
        config_service.set_config_value(key, value)
        return ConfigUpdateResponse(status="success", message=f"Config '{key}' updated. Use 'Restart Server' for changes to take full effect.")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Web API] Error updating config")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to update configuration")) from e
