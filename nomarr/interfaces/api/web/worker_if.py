"""Worker management endpoints for web UI."""

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.admin_types import WorkerOperationResponse
from nomarr.interfaces.api.types.queue_types import OperationResult
from nomarr.interfaces.api.web.dependencies import (
    get_event_broker,
    get_worker_pool,
    get_worker_service,
)

router = APIRouter(prefix="/worker", tags=["worker"])


# Background task storage for restart
_RESTART_TASKS: set = set()


# ──────────────────────────────────────────────────────────────────────
# Worker Control Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/pause", dependencies=[Depends(verify_session)])
async def web_admin_worker_pause(
    worker_service: Any | None = Depends(get_worker_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> WorkerOperationResponse:
    """Pause the worker (web UI proxy)."""
    if not worker_service:
        raise HTTPException(status_code=503, detail="Worker service not available")

    result = worker_service.pause_workers_for_admin(event_broker)
    return WorkerOperationResponse.from_dto(result)


@router.post("/resume", dependencies=[Depends(verify_session)])
async def web_admin_worker_resume(
    worker_service: Any | None = Depends(get_worker_service),
    worker_pool: list[Any] = Depends(get_worker_pool),
    event_broker: Any | None = Depends(get_event_broker),
) -> WorkerOperationResponse:
    """Resume the worker (web UI proxy)."""
    if not worker_service:
        raise HTTPException(status_code=503, detail="Worker service not available")

    result = worker_service.resume_workers_for_admin(worker_pool, event_broker)
    return WorkerOperationResponse.from_dto(result)


# ──────────────────────────────────────────────────────────────────────
# System Control Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/restart", dependencies=[Depends(verify_session)])
async def web_admin_restart() -> OperationResult:
    """Restart the API server (useful after config changes)."""
    import sys

    logging.info("[Web API] Restart requested - restarting server...")

    # Use a background task to allow the response to be sent before restart
    async def do_restart():
        await asyncio.sleep(1)  # Give time for response to be sent
        logging.info("[Web API] Executing restart now")
        os.execv(sys.executable, [sys.executable, *sys.argv])

    # Store task to prevent garbage collection
    task = asyncio.create_task(do_restart())
    _RESTART_TASKS.add(task)
    task.add_done_callback(_RESTART_TASKS.discard)

    return OperationResult(
        status="success",
        message="API server is restarting... Please refresh the page in a few seconds.",
    )
