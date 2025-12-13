"""Server-Sent Events (SSE) endpoint for real-time updates."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from nomarr.interfaces.api.auth import validate_session
from nomarr.interfaces.api.web.dependencies import get_events_service

router = APIRouter(prefix="/events", tags=["SSE"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/status")
async def web_sse_status(
    token: str,
    topics: str = "queue:status,queue:jobs,worker:tag:*:status",
) -> StreamingResponse:
    """
    Server-Sent Events endpoint for real-time system status updates.
    Requires session token as query parameter for authentication.

    Provides real-time updates for:
    - Queue statistics (pending/running/completed counts)
    - Active job state (progress, current head being processed)
    - Worker state (files being processed, progress)

    Args:
        token: Session token for authentication
        topics: Comma-separated list of topic patterns to subscribe to
                Default: "queue:status,queue:jobs,worker:tag:*:status"
                Examples:
                - "queue:status,queue:jobs" - Only queue stats and jobs
                - "worker:tag:*:status" - Only tag workers
                - "worker:*:status" - All workers (all queue types)

    Returns:
        StreamingResponse with SSE formatted events

    Raises:
        HTTPException: 401 for invalid token, 503 if events service unavailable
    """
    # Verify session token
    if not validate_session(token):
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Get events service
    events_service = get_events_service()

    if not events_service or not events_service.is_available():
        raise HTTPException(status_code=503, detail="Events service not available")

    # Parse topics and generate stream
    topic_list = events_service.parse_topics(topics)

    return StreamingResponse(
        events_service.stream_events(topic_list),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
