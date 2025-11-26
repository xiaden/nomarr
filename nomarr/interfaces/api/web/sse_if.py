"""Server-Sent Events (SSE) endpoint for real-time updates."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from nomarr.interfaces.api.auth import validate_session
from nomarr.interfaces.api.web.dependencies_if import get_event_broker

router = APIRouter(prefix="/events", tags=["SSE"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/status")
async def web_sse_status(token: str) -> StreamingResponse:
    """
    Server-Sent Events endpoint for real-time system status updates.
    Requires session token as query parameter for authentication.

    Provides real-time updates for:
    - Queue statistics (pending/running/completed counts)
    - Active job state (progress, current head being processed)
    - Worker state (files being processed, progress)
    """
    # Verify session token
    if not validate_session(token):
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Get event broker via manual call (can't use Depends in streaming response)
    event_broker = get_event_broker()

    if not event_broker:
        raise HTTPException(status_code=503, detail="Event broker not available")

    # Subscribe to state broker
    client_id, event_queue = event_broker.subscribe(["queue:status", "queue:jobs", "worker:*:status"])

    async def event_generator():
        """Generate SSE events from state broker."""
        try:
            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'message': 'Connected to status stream'})}\n\n"

            # Stream updates
            while True:
                try:
                    # Check for new events (non-blocking with timeout)
                    await asyncio.sleep(0.1)  # Prevent tight loop
                    try:
                        event = event_queue.get_nowait()

                        # Map internal event types to client-friendly events
                        event_type = event.get("type", "update")
                        if event_type in ("snapshot", "state_update"):
                            # Queue state update
                            yield f"event: queue_update\ndata: {json.dumps(event.get('state', {}))}\n\n"
                        elif event_type == "job_update":
                            # Job processing update
                            yield f"event: processing_update\ndata: {json.dumps(event.get('job', {}))}\n\n"
                        elif event_type == "worker_update":
                            # Worker status update
                            yield f"event: worker_update\ndata: {json.dumps(event.get('worker', {}))}\n\n"

                    except __import__("queue").Empty:
                        # No events, send periodic keepalive (every ~3 seconds)
                        await asyncio.sleep(3)
                        yield ": keepalive\n\n"

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logging.error(f"[Web SSE] Error in event stream: {e}")
                    break

        finally:
            # Cleanup subscription
            event_broker.unsubscribe(client_id)
            logging.info(f"[Web SSE] Client {client_id} disconnected")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
