"""ML management endpoints for web UI."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id
from nomarr.interfaces.api.types.info_types import WorkStatusResponse
from nomarr.interfaces.api.types.ml_types import (
    MarkConfiguredRequest,
    MlModelOutputResponse,
    MlModelResponse,
    UpdateOutputLabelRequest,
)
from nomarr.interfaces.api.web.dependencies import get_library_service, get_ml_service
from nomarr.services.domain.library_svc import LibraryService
from nomarr.services.infrastructure.ml_svc import MLService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/machine-learning", tags=["Machine Learning"])


class RecentFileItem(BaseModel):
    """A recently processed file."""

    file_id: str
    path: str
    title: str | None
    artist: str | None
    album: str | None
    scanned_at: int


class RecentFilesResponse(BaseModel):
    """Response for recently processed files."""

    files: list[RecentFileItem]


@router.get("/model", dependencies=[Depends(verify_session)])
async def ml_list_models(
    ml_service: Annotated[MLService, Depends(get_ml_service)],
) -> list[MlModelResponse]:
    """Return all registered ML model vertices with their configuration status."""
    try:
        docs = ml_service.list_all_models()
        return [MlModelResponse.from_doc(doc) for doc in docs]
    except Exception as e:
        logger.exception("[ml_if] Failed to list models")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to list models"),
        ) from e


@router.get("/model/{model_id}/output", dependencies=[Depends(verify_session)])
async def ml_get_model_outputs(
    model_id: str,
    ml_service: Annotated[MLService, Depends(get_ml_service)],
) -> list[MlModelOutputResponse]:
    """Return all output activation vertices for a model."""
    decoded_model_id = decode_path_id(model_id)
    try:
        docs = ml_service.get_model_outputs(decoded_model_id)
        return [MlModelOutputResponse.from_doc(doc) for doc in docs]
    except Exception as e:
        logger.exception("[ml_if] Failed to get model outputs for %s", model_id)
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get model outputs"),
        ) from e


@router.patch("/model/{model_id}/output/{output_id}", dependencies=[Depends(verify_session)])
async def ml_update_output_label(
    model_id: str,
    output_id: str,
    body: UpdateOutputLabelRequest,
    ml_service: Annotated[MLService, Depends(get_ml_service)],
) -> dict[str, str]:
    """Assign a human-readable label to a model output activation."""
    decode_path_id(model_id)  # validate format; model_id not used directly
    decoded_output_id = decode_path_id(output_id)
    try:
        ml_service.update_output_label(output_id=decoded_output_id, label=body.label)
        return {"status": "updated"}
    except Exception as e:
        logger.exception("[ml_if] Failed to update output label for %s", output_id)
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to update output label"),
        ) from e


@router.post("/model/{model_id}/mark-configured", dependencies=[Depends(verify_session)])
async def ml_mark_model_configured(
    model_id: str,
    body: MarkConfiguredRequest,
    ml_service: Annotated[MLService, Depends(get_ml_service)],
) -> dict[str, str]:
    """Set the fully_configured flag on a model, enabling or disabling it for inference."""
    decoded_model_id = decode_path_id(model_id)
    try:
        ml_service.mark_model_configured(model_id=decoded_model_id, value=body.value)
        return {"status": "updated", "fully_configured": str(body.value).lower()}
    except Exception as e:
        logger.exception("[ml_if] Failed to mark model configured for %s", model_id)
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to update model configuration"),
        ) from e


@router.post("/vram-probe", dependencies=[Depends(verify_session)])
async def ml_trigger_vram_probe(
    ml_service: Annotated[MLService, Depends(get_ml_service)],
) -> dict[str, str]:
    """Clear per-model VRAM measurements so the next worker startup re-probes.

    The probe runs automatically on the next discovery worker GPU warmup cycle.
    This endpoint only schedules the re-probe by clearing the existing measurements.
    """
    try:
        ml_service.clear_vram_measurements()
        return {"status": "probe_scheduled"}
    except Exception as e:
        logger.exception("[ml_if] Failed to clear VRAM measurements")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to schedule VRAM probe"),
        ) from e


@router.get("/work-status", dependencies=[Depends(verify_session)])
async def web_work_status(
    library_service: Annotated[LibraryService, Depends(get_library_service)],
) -> WorkStatusResponse:
    """Get unified work status for the system.

    Returns status of:
    - Scanning: Any library currently being scanned
    - Processing: ML inference on audio files (pending/processed counts)

    This endpoint is designed for frontend polling to show activity indicators.
    Poll at 1s intervals when busy, 30s when idle.
    """
    try:
        result = library_service.get_work_status()
        return WorkStatusResponse.from_dto(result)
    except Exception as e:
        logger.exception("[ml_if] Failed to get work status")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get work status"),
        ) from e


@router.get("/recent-activity", dependencies=[Depends(verify_session)])
async def web_recent_activity(
    library_service: Annotated[LibraryService, Depends(get_library_service)],
    limit: int = Query(default=20, ge=1, le=100, description="Number of recent files to return"),
    library_id: str | None = Query(default=None, description="Optional library ID to filter by"),
) -> RecentFilesResponse:
    """Get recently processed files.

    Returns files sorted by scanned_at descending.
    """
    try:
        decoded_library_id = decode_path_id(library_id) if library_id else None
        files = library_service.get_recently_processed(limit=limit, library_id=decoded_library_id)
        return RecentFilesResponse(files=[RecentFileItem(**file_doc) for file_doc in files])
    except Exception as e:
        logger.exception("[ml_if] Failed to get recent activity")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get recent activity"),
        ) from e
