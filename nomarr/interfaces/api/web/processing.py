"""Processing endpoints for web UI."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.helpers.logging import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import (
    get_processor_coordinator,
    get_queue_service,
)
from nomarr.services.coordinator_service import CoordinatorService
from nomarr.services.queue_service import QueueService

router = APIRouter(prefix="/api", tags=["Processing"])


# ──────────────────────────────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────────────────────────────


class ProcessRequest(BaseModel):
    """Request to process a single file."""

    path: str
    force: bool = False


class BatchProcessRequest(BaseModel):
    """Request to batch process multiple paths."""

    paths: list[str]
    force: bool = False


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/process", dependencies=[Depends(verify_session)])
async def web_process(
    request: ProcessRequest,
    processor_coord: CoordinatorService | None = Depends(get_processor_coordinator),
) -> dict[str, Any]:
    """Process a single file synchronously (web UI proxy)."""
    # Check if coordinator is available
    if not processor_coord:
        raise HTTPException(status_code=503, detail="Processing coordinator not initialized")

    # Submit job and wait for result
    try:
        future = processor_coord.submit(request.path, request.force)  # type: ignore[misc]
        result = await asyncio.get_event_loop().run_in_executor(None, lambda: future.result(300))  # type: ignore[attr-defined]
        return result  # type: ignore[no-any-return]
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"File not found: {request.path}") from e
    except Exception as e:
        logging.exception(f"[Web API] Error processing {request.path}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/batch-process", dependencies=[Depends(verify_session)])
async def web_batch_process(
    request: BatchProcessRequest,
    queue_service: QueueService = Depends(get_queue_service),
) -> dict[str, Any]:
    """
    Add multiple paths to the database queue for processing (web UI proxy).
    Each path can be a file or directory - directories are recursively scanned for audio files.
    """
    results = []
    queued = 0
    errors = 0

    for path in request.paths:
        try:
            # Use QueueService for consistent queue operations
            result = queue_service.add_files(
                paths=[path],
                force=bool(request.force),
                recursive=True,  # Always scan directories recursively
            )

            # result contains: job_ids (list), files_queued (int), queue_depth, paths
            files_count = result["files_queued"]
            job_ids = result["job_ids"]

            if files_count > 1:
                # Directory with multiple files
                results.append(
                    {
                        "path": path,
                        "status": "queued",
                        "message": f"Added {files_count} files to queue (jobs {job_ids[0]}-{job_ids[-1]})",
                    }
                )
            else:
                # Single file
                results.append(
                    {
                        "path": path,
                        "status": "queued",
                        "message": f"Added to queue as job {job_ids[0]}",
                    }
                )

            queued += files_count

        except HTTPException as e:
            results.append({"path": path, "status": "error", "message": e.detail})
            errors += 1
        except Exception as e:
            # Sanitize exception to avoid leaking sensitive information
            safe_msg = sanitize_exception_message(e, "Failed to process path")
            results.append({"path": path, "status": "error", "message": safe_msg})
            errors += 1

    return {"queued": queued, "skipped": 0, "errors": errors, "results": results}


@router.get("/list", dependencies=[Depends(verify_session)])
async def web_list(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    queue_service: QueueService = Depends(get_queue_service),
) -> dict[str, Any]:
    """List jobs with pagination and filtering (web UI proxy)."""
    # Use QueueService to list jobs
    return queue_service.list_jobs(limit=limit, offset=offset, status=status)
