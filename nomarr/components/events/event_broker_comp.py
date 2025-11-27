"""
State-based SSE broker for real-time system state synchronization.

Maintains current state of queue, workers, and jobs. Sends state snapshots
on subscription followed by incremental updates.
"""

from __future__ import annotations

import fnmatch
import logging
import queue
import threading
import time
from typing import Any


class StateBroker:
    """
    Thread-safe state broker for SSE-based state synchronization.

    Maintains current system state and broadcasts updates to subscribed clients.
    Clients receive a state snapshot on connection, then incremental updates.

    State topics:
    - queue:status - Queue statistics (pending/running/completed counts, ETA)
    - queue:jobs - All active jobs with current state
    - worker:{id}:status - Specific worker state (current file, progress)
    - worker:*:status - All worker states
    - system:health - System health and errors
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._clients: dict[str, dict[str, Any]] = {}  # client_id -> {queue, topics, created_at}
        self._next_client_id = 0

        # System state
        self._queue_state = {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "avg_time": 0.0,
            "eta": 0.0,
        }
        self._jobs_state: dict[int, dict[str, Any]] = {}  # job_id -> {path, status, progress, ...}
        self._worker_state: dict[int, dict[str, Any]] = {}  # worker_id -> {current_file, progress, ...}
        self._system_health = {"status": "healthy", "errors": []}

    def update_queue_state(self, **kwargs):
        """
        Update queue statistics and broadcast to subscribers.

        Args:
            **kwargs: Queue state fields (pending, running, completed, avg_time, eta)
        """
        with self._lock:
            self._queue_state.update(kwargs)
            self._broadcast_to_topic("queue:status", {"type": "state_update", "state": self._queue_state.copy()})

    def update_job_state(self, job_id: int, **kwargs):
        """
        Update individual job state and broadcast to subscribers.

        Args:
            job_id: Job ID
            **kwargs: Job state fields (path, status, progress, head, etc.)
        """
        with self._lock:
            if job_id not in self._jobs_state:
                self._jobs_state[job_id] = {"id": job_id}
            self._jobs_state[job_id].update(kwargs)

            # Broadcast job state update
            self._broadcast_to_topic("queue:jobs", {"type": "job_update", "job": self._jobs_state[job_id].copy()})

    def update_worker_state(self, worker_id: int, **kwargs):
        """
        Update worker state and broadcast to subscribers.

        Args:
            worker_id: Worker ID
            **kwargs: Worker state fields (current_file, progress, head, state, etc.)
        """
        with self._lock:
            if worker_id not in self._worker_state:
                self._worker_state[worker_id] = {"id": worker_id}
            self._worker_state[worker_id].update(kwargs)

            # Broadcast to worker-specific and wildcard topics
            self._broadcast_to_topic(
                f"worker:{worker_id}:status",
                {"type": "worker_update", "worker": self._worker_state[worker_id].copy()},
            )

    def remove_job(self, job_id: int):
        """Remove job from state (when completed/cleaned up)."""
        with self._lock:
            if job_id in self._jobs_state:
                del self._jobs_state[job_id]
                self._broadcast_to_topic("queue:jobs", {"type": "job_removed", "job_id": job_id})

    def subscribe(self, topics: list[str]) -> tuple[str, queue.Queue]:
        """
        Subscribe to topics and get initial state snapshot + event queue.

        Args:
            topics: List of topic patterns to subscribe to (supports wildcards)

        Returns:
            Tuple of (client_id, event_queue)
        """
        with self._lock:
            client_id = f"client_{self._next_client_id}"
            self._next_client_id += 1

            client_queue: queue.Queue = queue.Queue(maxsize=1000)
            self._clients[client_id] = {
                "queue": client_queue,
                "topics": topics,
                "created_at": time.time(),
            }

            # Send initial state snapshot for subscribed topics
            for topic in topics:
                snapshot = self._get_state_snapshot(topic)
                if snapshot:
                    client_queue.put(snapshot)

            logging.info(f"[StateBroker] Client {client_id} subscribed to topics: {topics}")
            return client_id, client_queue

    def unsubscribe(self, client_id: str):
        """
        Unsubscribe and clean up client resources.

        Args:
            client_id: Client ID to remove
        """
        with self._lock:
            if client_id in self._clients:
                del self._clients[client_id]
                logging.info(f"[StateBroker] Client {client_id} unsubscribed")

    def _get_state_snapshot(self, topic: str) -> dict[str, Any] | None:
        """
        Get current state snapshot for a topic.

        Args:
            topic: Topic pattern (may include wildcards)

        Returns:
            State snapshot event or None
        """
        # Queue status snapshot
        if fnmatch.fnmatch("queue:status", topic):
            return {"topic": "queue:status", "type": "snapshot", "state": self._queue_state.copy()}

        # Queue jobs snapshot
        if fnmatch.fnmatch("queue:jobs", topic):
            return {
                "topic": "queue:jobs",
                "type": "snapshot",
                "jobs": list(self._jobs_state.values()),
            }

        # Worker status snapshot
        if topic.startswith("worker:"):
            if topic == "worker:*:status":
                # All workers
                return {
                    "topic": "worker:*:status",
                    "type": "snapshot",
                    "workers": list(self._worker_state.values()),
                }
            else:
                # Specific worker
                parts = topic.split(":")
                if len(parts) == 3 and parts[2] == "status":
                    try:
                        worker_id = int(parts[1])
                        if worker_id in self._worker_state:
                            return {
                                "topic": topic,
                                "type": "snapshot",
                                "worker": self._worker_state[worker_id].copy(),
                            }
                    except ValueError:
                        pass

        # System health snapshot
        if fnmatch.fnmatch("system:health", topic):
            return {"topic": "system:health", "type": "snapshot", "health": self._system_health.copy()}

        return None

    def _broadcast_to_topic(self, topic: str, event: dict[str, Any]):
        """
        Broadcast event to all clients subscribed to topic.

        Args:
            topic: Event topic
            event: Event data
        """
        event["topic"] = topic
        event["timestamp"] = int(time.time() * 1000)

        matched_clients = 0
        for client_id, client_info in self._clients.items():
            if self._topic_matches(topic, client_info["topics"]):
                try:
                    client_info["queue"].put_nowait(event)
                    matched_clients += 1
                except queue.Full:
                    logging.warning(f"[StateBroker] Client {client_id} queue full, dropping event for topic {topic}")

        if matched_clients > 0:
            logging.debug(f"[StateBroker] Broadcast {topic} to {matched_clients} clients")

    def _topic_matches(self, topic: str, patterns: list[str]) -> bool:
        """
        Check if topic matches any subscription pattern.

        Args:
            topic: Event topic (e.g., "worker:0:status")
            patterns: List of subscription patterns (e.g., ["worker:*:status", "queue:jobs"])

        Returns:
            True if topic matches any pattern
        """
        return any(fnmatch.fnmatch(topic, pattern) for pattern in patterns)
