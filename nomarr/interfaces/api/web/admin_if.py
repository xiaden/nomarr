"""Admin endpoints for web UI."""

import asyncio
import logging
import os
import sys

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from nomarr.interfaces.api.auth import verify_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])
_RESTART_TASKS: set = set()


class RestartResponse(BaseModel):
    """Response for restart operation."""

    status: str
    message: str


@router.post("/restart", dependencies=[Depends(verify_session)])
async def web_admin_restart() -> RestartResponse:
    """Restart the API server (useful after config changes)."""
    logger.info("[Web API] Restart requested - restarting server...")

    async def do_restart() -> None:
        """Delay long enough to send the HTTP response, then restart in-place.

        Call `application.stop()` first so worker processes and background tasks shut down
        cleanly before `os.execv()` replaces this process image with a fresh interpreter,
        preserving the current PID.
        """
        await asyncio.sleep(1)
        logger.info("[Web API] Shutting down before restart")
        from nomarr.app import application

        application.stop()
        logger.info("[Web API] Executing restart now")
        os.execv(sys.executable, [sys.executable, *sys.argv])

    task = asyncio.create_task(do_restart())
    _RESTART_TASKS.add(task)
    task.add_done_callback(_RESTART_TASKS.discard)
    return RestartResponse(
        status="success", message="API server is restarting... Please refresh the page in a few seconds."
    )
