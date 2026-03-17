"""ML management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id
from nomarr.interfaces.api.types.ml_types import (
    MarkConfiguredRequest,
    MlModelOutputResponse,
    MlModelResponse,
    UpdateOutputLabelRequest,
)
from nomarr.interfaces.api.web.dependencies import get_ml_service

if TYPE_CHECKING:
    from nomarr.services.infrastructure.ml_svc import MLService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ml", tags=["ml"])


@router.get("/models", dependencies=[Depends(verify_session)])
async def ml_list_models(
    ml_service: Annotated["MLService", Depends(get_ml_service)],
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


@router.get("/models/{model_id}/outputs", dependencies=[Depends(verify_session)])
async def ml_get_model_outputs(
    model_id: str,
    ml_service: Annotated["MLService", Depends(get_ml_service)],
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


@router.patch("/models/{model_id}/outputs/{output_id}", dependencies=[Depends(verify_session)])
async def ml_update_output_label(
    model_id: str,
    output_id: str,
    body: UpdateOutputLabelRequest,
    ml_service: Annotated["MLService", Depends(get_ml_service)],
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


@router.post("/models/{model_id}/mark-configured", dependencies=[Depends(verify_session)])
async def ml_mark_model_configured(
    model_id: str,
    body: MarkConfiguredRequest,
    ml_service: Annotated["MLService", Depends(get_ml_service)],
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
    ml_service: Annotated["MLService", Depends(get_ml_service)],
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
