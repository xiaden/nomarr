"""Processing endpoints for web UI."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from nomarr.components.queue import list_jobs as list_jobs_component
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.processing_types import (
    BatchProcessRequest,
    BatchProcessResponse,
    ProcessFileRequest,
    ProcessFileResponse,
)
from nomarr.interfaces.api.types.queue_types import ListJobsResponse
from nomarr.interfaces.api.web.dependencies import (
    get_database,
    get_processor_coordinator,
)
from nomarr.persistence.db import Database
from nomarr.services.coordinator_svc import CoordinatorService
from nomarr.workflows.queue import enqueue_files_workflow

router = APIRouter(prefix="/processing", tags=["Processing"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/process", dependencies=[Depends(verify_session)])
async def web_process(
    request: ProcessFileRequest,
    processor_coord: CoordinatorService | None = Depends(get_processor_coordinator),
) -> ProcessFileResponse:
    """Process a single file synchronously (web UI proxy)."""
    # Check if coordinator is available
    if not processor_coord:
        raise HTTPException(status_code=503, detail="Processing coordinator not initialized")

    # Submit job and wait for result
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: processor_coord.submit(request.path, request.force)
        )

        # If result is a dict (error case), extract error message
        if isinstance(result, dict):
            error_msg = result.get("error", "Unknown error")
            raise HTTPException(status_code=500, detail=error_msg)

        # Transform DTO to Pydantic response
        return ProcessFileResponse.from_dto(result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"File not found: {request.path}") from e
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"[Web API] Error processing {request.path}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/batch-process", dependencies=[Depends(verify_session)])
async def web_batch_process(
    request: BatchProcessRequest,
    db: Database = Depends(get_database),
) -> BatchProcessResponse:
    """
    Add multiple paths to the database queue for processing (web UI proxy).
    Each path can be a file or directory - directories are recursively scanned for audio files.
    """
    batch_result = enqueue_files_workflow(
        db=db,
        queue_type="tag",
        paths=request.paths,
        force=bool(request.force),
        recursive=True,
    )

    return BatchProcessResponse.from_dto(batch_result)


@router.get("/list", dependencies=[Depends(verify_session)])
async def web_list(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    db: Database = Depends(get_database),
) -> ListJobsResponse:
    """List jobs with pagination and filtering (web UI proxy)."""
    # Use queue component to list jobs (returns ListJobsResult DTO)
    result = list_jobs_component(db, queue_type="tag", limit=limit, offset=offset, status=status)  # type: ignore[arg-type]

    # Transform DTO to Pydantic response
    return ListJobsResponse.from_dto(result)
