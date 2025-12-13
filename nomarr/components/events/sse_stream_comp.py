"""
Component for generating Server-Sent Events (SSE) formatted output.

Transforms internal event data into SSE protocol format with proper
event types and data serialization.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from queue import Empty
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from queue import Queue


def format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """
    Format a single SSE event.

    Args:
        event_type: SSE event type (e.g., "queue_update", "connected")
        data: Event data to serialize as JSON

    Returns:
        Formatted SSE event string with proper protocol formatting
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def format_sse_comment(comment: str) -> str:
    """
    Format an SSE comment (used for keepalives).

    Args:
        comment: Comment text

    Returns:
        Formatted SSE comment string
    """
    return f": {comment}\n\n"


def map_event_to_sse(event: dict[str, Any]) -> str | None:
    """
    Map internal event structure to SSE formatted output.

    Args:
        event: Internal event dict with "type" and type-specific data

    Returns:
        SSE formatted string, or None if event should be skipped
    """
    event_type = event.get("type", "update")

    if event_type in ("snapshot", "state_update"):
        # Queue state update
        return format_sse_event("queue_update", event.get("state", {}))

    elif event_type == "job_update":
        # Job processing update
        return format_sse_event("processing_update", event.get("job", {}))

    elif event_type == "worker_update":
        # Worker status update
        return format_sse_event("worker_update", event.get("worker", {}))

    else:
        # Unknown event type - log and skip
        logging.warning(f"[SSE Stream] Unknown event type: {event_type}")
        return None


async def generate_sse_stream(
    event_queue: Queue[dict[str, Any]],
    cleanup_callback: callable | None = None,
    keepalive_interval: float = 3.0,
) -> AsyncGenerator[str, None]:
    """
    Generate SSE formatted event stream from event queue.

    Continuously polls event queue and yields SSE formatted events.
    Sends periodic keepalive comments to maintain connection.

    Args:
        event_queue: Queue of internal event dicts to process
        cleanup_callback: Optional callback to run on stream completion
        keepalive_interval: Seconds between keepalive comments (default: 3.0)

    Yields:
        SSE formatted event strings
    """
    try:
        # Send initial connection event
        yield format_sse_event("connected", {"message": "Connected to status stream"})

        last_keepalive = asyncio.get_event_loop().time()

        # Stream updates
        while True:
            try:
                # Prevent tight loop
                await asyncio.sleep(0.1)

                # Check for new events (non-blocking)
                try:
                    event = event_queue.get_nowait()

                    # Map and format event
                    sse_output = map_event_to_sse(event)
                    if sse_output:
                        yield sse_output

                except Empty:
                    # No events - check if keepalive needed
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_keepalive >= keepalive_interval:
                        yield format_sse_comment("keepalive")
                        last_keepalive = current_time

            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.exception(f"[SSE Stream] Error in event stream: {e}")
                break

    finally:
        # Run cleanup callback if provided
        if cleanup_callback:
            try:
                cleanup_callback()
            except Exception as e:
                logging.error(f"[SSE Stream] Error in cleanup callback: {e}")
