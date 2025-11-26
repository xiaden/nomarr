"""Worker management endpoints for web UI."""

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.queue_types import OperationResult
from nomarr.interfaces.api.web.dependencies_if import (
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
) -> OperationResult:
    """Pause the worker (web UI proxy)."""
    # Use WorkerService to disable workers (handles meta, idle wait, and stopping)
    if worker_service:
        worker_service.disable()

    # Publish worker state update
    if event_broker:
        event_broker.update_worker_state("main", {"enabled": False})

    return OperationResult(
        status="success",
        message="Worker paused successfully",
    )


@router.post("/resume", dependencies=[Depends(verify_session)])
async def web_admin_worker_resume(
    worker_service: Any | None = Depends(get_worker_service),
    worker_pool: list[Any] = Depends(get_worker_pool),
    event_broker: Any | None = Depends(get_event_broker),
) -> OperationResult:
    """Resume the worker (web UI proxy)."""
    # Use WorkerService to resume workers
    if worker_service:
        worker_service.enable()
        new_workers = worker_service.start_workers(event_broker=event_broker)
        worker_pool.clear()
        worker_pool.extend(new_workers)

    # Publish worker state update
    if event_broker:
        event_broker.update_worker_state("main", {"enabled": True})

    return OperationResult(
        status="success",
        message="Worker resumed successfully",
    )


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
