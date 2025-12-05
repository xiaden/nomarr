"""Worker management endpoints for web UI."""

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.admin_types import WorkerOperationResponse
from nomarr.interfaces.api.types.queue_types import OperationResult
from nomarr.interfaces.api.web.dependencies import (
    get_event_broker,
    get_workers_coordinator,
)

router = APIRouter(prefix="/worker", tags=["worker"])


# Background task storage for restart
_RESTART_TASKS: set = set()


# ──────────────────────────────────────────────────────────────────────
# Worker Control Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/pause", dependencies=[Depends(verify_session)])
async def web_admin_worker_pause(
    workers_coordinator=Depends(get_workers_coordinator),
    event_broker: Any | None = Depends(get_event_broker),
) -> WorkerOperationResponse:
    """Pause all workers (web UI proxy)."""
    result = workers_coordinator.pause_all_workers(event_broker)
    return WorkerOperationResponse.from_dto(result)


@router.post("/resume", dependencies=[Depends(verify_session)])
async def web_admin_worker_resume(
    workers_coordinator=Depends(get_workers_coordinator),
    event_broker: Any | None = Depends(get_event_broker),
) -> WorkerOperationResponse:
    """Resume all workers (web UI proxy)."""
    result = workers_coordinator.resume_all_workers(event_broker)
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
