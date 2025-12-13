"""
Events Service - Manages SSE event streaming and subscriptions.

Coordinates between event broker and interface layer for SSE connections.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from queue import Queue

    from nomarr.components.events.event_broker_comp import StateBroker


class EventsService:
    """
    Service for managing SSE event streams and subscriptions.

    Provides clean interface between event broker and API endpoints.
    Handles subscription lifecycle and event stream generation.
    """

    def __init__(self, event_broker: StateBroker | None):
        """
        Initialize EventsService.

        Args:
            event_broker: StateBroker instance for event subscriptions (optional)
        """
        self.event_broker = event_broker

    def is_available(self) -> bool:
        """Check if event broker is available."""
        return self.event_broker is not None

    def parse_topics(self, topics_str: str) -> list[str]:
        """
        Parse comma-separated topics string into list.

        Args:
            topics_str: Comma-separated topic patterns (e.g., "queue:status,worker:*:status")

        Returns:
            List of topic pattern strings
        """
        topic_list = [t.strip() for t in topics_str.split(",") if t.strip()]
        if not topic_list:
            # Default topics
            topic_list = ["queue:status", "queue:jobs", "worker:tag:*:status"]
        return topic_list

    def subscribe_to_events(self, topics: list[str]) -> tuple[str, Queue[dict[str, Any]]]:
        """
        Subscribe to event topics and get event queue.

        Args:
            topics: List of topic patterns to subscribe to

        Returns:
            Tuple of (client_id, event_queue)

        Raises:
            RuntimeError: If event broker not available
        """
        if not self.event_broker:
            raise RuntimeError("Event broker not available")

        client_id, event_queue = self.event_broker.subscribe(topics)
        logging.info(f"[Events Service] Client {client_id} subscribed to topics: {topics}")
        return client_id, event_queue

    def unsubscribe_from_events(self, client_id: str) -> None:
        """
        Unsubscribe client from events.

        Args:
            client_id: Client ID to unsubscribe
        """
        if not self.event_broker:
            return

        self.event_broker.unsubscribe(client_id)
        logging.info(f"[Events Service] Client {client_id} unsubscribed")

    async def stream_events(self, topics: list[str]) -> AsyncGenerator[str, None]:
        """
        Generate SSE event stream for given topics.

        Subscribes to topics, generates SSE formatted events, and handles cleanup.

        Args:
            topics: List of topic patterns to subscribe to

        Yields:
            SSE formatted event strings

        Raises:
            RuntimeError: If event broker not available
        """
        from nomarr.components.events.sse_stream_comp import generate_sse_stream

        # Subscribe to event topics
        client_id, event_queue = self.subscribe_to_events(topics)

        # Create cleanup callback
        def cleanup():
            self.unsubscribe_from_events(client_id)

        # Generate SSE stream
        async for sse_event in generate_sse_stream(event_queue, cleanup_callback=cleanup):
            yield sse_event
