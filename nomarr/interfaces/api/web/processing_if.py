"""Processing endpoints for web UI."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import encode_id
from nomarr.interfaces.api.types.processing_types import (
    BatchProcessRequest,
    BatchProcessResponse,
    ProcessFileRequest,
)
from nomarr.interfaces.api.types.queue_types import ListJobsResponse
from nomarr.interfaces.api.web.dependencies import get_queue_service
from nomarr.services.infrastructure.queue_svc import QueueService

router = APIRouter(prefix="/processing", tags=["Processing"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/process", dependencies=[Depends(verify_session)])
async def web_process(
    request: ProcessFileRequest,
    queue_service: QueueService = Depends(get_queue_service),
) -> dict[str, Any]:
    """Process a single file by adding to queue (web UI proxy)."""
    try:
        # Enqueue file for tagging
        result = queue_service.enqueue_files_for_tagging(
            paths=request.path,
            force=request.force,
            recursive=False,
        )

        if not result.job_ids:
            raise HTTPException(status_code=400, detail="Failed to add file to queue")

        # Return job info immediately (async processing)
        return {
            "job_id": encode_id(result.job_ids[0]),
            "files_queued": result.files_queued,
            "queue_depth": result.queue_depth,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"[Web API] Error processing {request.path}: {e}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to process file")) from e


@router.post("/batch-process", dependencies=[Depends(verify_session)])
async def web_batch_process(
    request: BatchProcessRequest,
    queue_service: QueueService = Depends(get_queue_service),
) -> BatchProcessResponse:
    """
    Add multiple paths to the database queue for processing (web UI proxy).
    Each path can be a file or directory - directories are recursively scanned for audio files.
    """
    batch_result = queue_service.batch_add_files(
        paths=request.paths,
        force=bool(request.force),
    )

    return BatchProcessResponse.from_dto(batch_result)


@router.get("/list", dependencies=[Depends(verify_session)])
async def web_list(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    queue_service: QueueService = Depends(get_queue_service),
) -> ListJobsResponse:
    """List jobs with pagination and filtering (web UI proxy)."""
    # Use QueueService to list jobs (returns ListJobsResult DTO)
    result = queue_service.list_jobs(limit=limit, offset=offset, status=status)

    # Transform DTO to Pydantic response
    return ListJobsResponse.from_dto(result)
