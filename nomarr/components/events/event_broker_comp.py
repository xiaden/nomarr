"""
State-based SSE broker for real-time system state synchronization.

Maintains current state of queue, workers, and jobs. Sends state snapshots
on subscription followed by incremental updates.

Phase 3.6: DB Polling for Multiprocessing IPC
- StateBroker polls DB meta table for worker updates
- Workers write to DB meta table instead of calling broker methods
- Enables proper IPC when workers are separate processes
"""

from __future__ import annotations

import fnmatch
import json
import logging
import queue
import threading
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.events_state_dto import GPUHealthState, JobState, QueueState, SystemHealthState, WorkerState

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class StateBroker:
    """
    Thread-safe state broker for SSE-based state synchronization.

    Maintains current system state and broadcasts updates to subscribed clients.
    Clients receive a state snapshot on connection, then incremental updates.

    Phase 3.6: Polls DB meta table for updates from worker processes.

    State topics:
    - queue:status - Global aggregated queue statistics (all queues)
    - queue:{queue_type}:status - Per-queue statistics (tag/library/calibration)
    - queue:*:status - All per-queue statistics
    - queue:jobs - All active jobs with current state
    - worker:{queue_type}:{id}:status - Specific worker state (includes queue type to avoid ID collisions)
    - worker:{queue_type}:*:status - All workers for a specific queue type
    - worker:*:status - All worker states (all queue types)
    - system:health - System health and errors
    - system:gpu - GPU availability and health
    """

    def __init__(self, db: Database | None = None, poll_interval: float = 2.0):
        """
        Initialize StateBroker.

        Args:
            db: Database instance for polling worker state (Phase 3.6)
            poll_interval: How often to poll DB for updates (seconds, default: 2.0)
        """
        self._lock = threading.Lock()
        self._clients: dict[str, dict[str, Any]] = {}  # client_id -> {queue, topics, created_at}
        self._next_client_id = 0

        # System state using DTOs
        # Per-queue state (keyed by queue_type: "tag", "library", "calibration")
        self._queue_state_by_type: dict[str, QueueState] = {}

        # Global aggregated queue state (derived from per-queue stats)
        self._queue_state_global = QueueState(
            queue_type=None,
            pending=0,
            running=0,
            completed=0,
            avg_time=0.0,
            eta=0.0,
        )

        self._jobs_state: dict[int, JobState] = {}  # job_id -> JobState DTO

        # Worker state keyed by full component ID to avoid collisions (e.g., "worker:tag:0")
        self._worker_state: dict[str, WorkerState] = {}  # component -> WorkerState DTO

        # GPU health state (initially unknown, read from DB written by GPUHealthMonitor)
        self._gpu_health = GPUHealthState(
            status="unknown",  # Initially unknown until first update
            available=False,  # Assume unavailable until first update
            last_check_at=None,
            last_ok_at=None,
            consecutive_failures=0,
            error_summary="GPU health not yet initialized",
        )

        self._system_health = SystemHealthState(status="healthy", errors=[], gpu=self._gpu_health)

        # Phase 3.6: DB polling for multiprocessing IPC
        self._db = db
        self._poll_interval = poll_interval
        self._poll_thread: threading.Thread | None = None
        self._shutdown = False

        # Start polling thread if DB is provided
        if self._db:
            self._poll_thread = threading.Thread(target=self._poll_worker_state, daemon=True, name="StateBrokerPoller")
            self._poll_thread.start()
            logging.info("[StateBroker] Started DB polling thread (reads GPU state from GPUHealthMonitor)")

    def _poll_worker_state(self) -> None:
        """
        Poll DB meta table for worker state updates (Phase 3.6: multiprocessing IPC).

        Runs in background thread, reads state written by worker processes,
        and broadcasts to SSE clients via normal update methods.
        """
        if not self._db:
            return

        logging.info("[StateBroker] DB polling thread started")

        while not self._shutdown:
            try:
                # Poll for all queue types (tag, library, calibration)
                for queue_type in ["tag", "library", "calibration"]:
                    # Get queue stats
                    stats_json = self._db.meta.get(f"queue:{queue_type}:stats")
                    if stats_json:
                        try:
                            stats = json.loads(stats_json)
                            # Update per-queue state and broadcast to per-queue topic
                            self.update_queue_state_for_type(queue_type, **stats)
                        except json.JSONDecodeError:
                            pass

                # Poll health table for worker states
                workers = self._db.health.get_all_workers()
                for worker in workers:
                    component = worker.get("component", "")
                    if not isinstance(component, str) or not component.startswith("worker:"):
                        continue

                    # Parse worker component ID: "worker:tag:0"
                    parts = component.split(":")
                    if len(parts) == 3:
                        queue_type, worker_id_str = parts[1], parts[2]
                        try:
                            worker_id = int(worker_id_str)

                            # Get current job from health table
                            current_job_id = worker.get("current_job")

                            worker_state = {
                                "id": worker_id,
                                "queue_type": queue_type,
                                "status": worker.get("status", "unknown"),
                                "pid": worker.get("pid"),
                                "current_job": current_job_id,
                            }

                            # If worker has a current job, get job details from meta table
                            if current_job_id and isinstance(current_job_id, int):
                                job_status = self._db.meta.get(f"job:{current_job_id}:status")
                                job_path = self._db.meta.get(f"job:{current_job_id}:path")
                                job_error = self._db.meta.get(f"job:{current_job_id}:error")
                                job_results_json = self._db.meta.get(f"job:{current_job_id}:results")

                                if job_status:
                                    job_update = {
                                        "id": current_job_id,
                                        "path": job_path,
                                        "status": job_status,
                                    }
                                    if job_error:
                                        job_update["error"] = job_error
                                    if job_results_json:
                                        try:
                                            job_update["results"] = json.loads(job_results_json)
                                        except json.JSONDecodeError:
                                            pass

                                    # Broadcast job update
                                    self.update_job_state(current_job_id, **job_update)

                            # Broadcast worker state update (using component as key)
                            self.update_worker_state(component, **worker_state)

                        except (ValueError, KeyError):
                            pass

                # Read GPU health state from DB (written by GPUHealthMonitor process)
                # This is a fast DB read, never blocks on nvidia-smi
                self._read_gpu_health_from_db()

            except Exception as e:
                logging.error(f"[StateBroker] Error polling worker state: {e}")

            time.sleep(self._poll_interval)

        logging.info("[StateBroker] DB polling thread stopped")

    def stop(self) -> None:
        """Stop the StateBroker and polling thread."""
        self._shutdown = True
        if self._poll_thread:
            self._poll_thread.join(timeout=2)

    def _read_gpu_health_from_db(self) -> None:
        """
        Read GPU health state from DB meta table (written by GPUHealthMonitor).

        This is a fast DB read operation that never blocks on nvidia-smi.
        If GPUHealthMonitor process hangs, this will detect stale data and
        transition GPU status to UNKNOWN.
        """
        import json

        from nomarr.components.platform import check_gpu_health_staleness

        if not self._db:
            return

        try:
            # Read atomic GPU health JSON from DB (written by GPUHealthMonitor)
            health_json = self._db.meta.get("gpu:health")

            with self._lock:
                if not health_json:
                    # No health data yet - monitor not running or hasn't written yet
                    self._gpu_health.status = "unknown"
                    self._gpu_health.available = False
                    self._gpu_health.last_check_at = None
                    self._gpu_health.last_ok_at = None
                    self._gpu_health.consecutive_failures = 0
                    self._gpu_health.error_summary = "GPU health not yet initialized"
                else:
                    # Parse JSON blob
                    health_data = json.loads(health_json)
                    last_check_at = health_data.get("probe_time")

                    # Check for staleness (monitor may be stuck)
                    is_stale = check_gpu_health_staleness(last_check_at)

                    if is_stale:
                        # Data too old - monitor may be stuck (nvidia-smi hung)
                        self._gpu_health.status = "unknown"
                        self._gpu_health.available = False
                        self._gpu_health.last_check_at = last_check_at
                        self._gpu_health.last_ok_at = health_data.get("last_ok_at")
                        self._gpu_health.consecutive_failures = 0
                        self._gpu_health.error_summary = "GPU health data stale (monitor may be stuck)"
                        self._gpu_health.probe_id = health_data.get("probe_id")
                        self._gpu_health.duration_ms = health_data.get("duration_ms")
                    else:
                        # Fresh data from monitor - use reported status
                        self._gpu_health.status = health_data.get("status", "unknown")
                        self._gpu_health.available = health_data.get("available", False)
                        self._gpu_health.last_check_at = last_check_at
                        self._gpu_health.last_ok_at = health_data.get("last_ok_at")
                        self._gpu_health.consecutive_failures = 0
                        self._gpu_health.error_summary = health_data.get("error_summary")
                        self._gpu_health.probe_id = health_data.get("probe_id")
                        self._gpu_health.duration_ms = health_data.get("duration_ms")

                # Update system health GPU facet
                self._system_health.gpu = self._gpu_health

                # Broadcast GPU health update
                self._broadcast_to_topic("system:gpu", {"type": "state_update", "gpu": asdict(self._gpu_health)})

        except Exception as e:
            logging.error(f"[StateBroker] Error reading GPU health from DB: {e}")

    def update_gpu_health(self, **kwargs) -> None:
        """
        Update GPU health state and broadcast to subscribers.

        Args:
            **kwargs: GPU health fields (available, error_summary, etc.)
        """
        with self._lock:
            if "available" in kwargs:
                self._gpu_health.available = kwargs["available"]
            if "last_check_at" in kwargs:
                self._gpu_health.last_check_at = kwargs["last_check_at"]
            if "last_ok_at" in kwargs:
                self._gpu_health.last_ok_at = kwargs["last_ok_at"]
            if "consecutive_failures" in kwargs:
                self._gpu_health.consecutive_failures = kwargs["consecutive_failures"]
            if "error_summary" in kwargs:
                self._gpu_health.error_summary = kwargs["error_summary"]

            # Update system health GPU facet
            self._system_health.gpu = self._gpu_health

            # Broadcast update
            self._broadcast_to_topic("system:gpu", {"type": "state_update", "gpu": asdict(self._gpu_health)})

    def get_gpu_health(self) -> GPUHealthState:
        """
        Get current GPU health state (read-only snapshot).

        Returns:
            GPUHealthState DTO with current GPU availability
        """
        with self._lock:
            return GPUHealthState(
                status=self._gpu_health.status,
                available=self._gpu_health.available,
                last_check_at=self._gpu_health.last_check_at,
                last_ok_at=self._gpu_health.last_ok_at,
                consecutive_failures=self._gpu_health.consecutive_failures,
                error_summary=self._gpu_health.error_summary,
                probe_id=getattr(self._gpu_health, "probe_id", None),
                duration_ms=getattr(self._gpu_health, "duration_ms", None),
            )

    def update_queue_state_for_type(self, queue_type: str, **kwargs):
        """
        Update per-queue statistics and broadcast to per-queue topic.

        Args:
            queue_type: Queue type ("tag", "library", "calibration")
            **kwargs: Queue state fields (pending, running, completed, avg_time, eta)
        """
        with self._lock:
            # Update or create per-queue state DTO
            if queue_type not in self._queue_state_by_type:
                self._queue_state_by_type[queue_type] = QueueState(
                    queue_type=queue_type,
                    pending=0,
                    running=0,
                    completed=0,
                    avg_time=0.0,
                    eta=0.0,
                )

            # Track if state actually changed
            state = self._queue_state_by_type[queue_type]
            changed = False

            if "pending" in kwargs and state.pending != kwargs["pending"]:
                state.pending = kwargs["pending"]
                changed = True
            if "running" in kwargs and state.running != kwargs["running"]:
                state.running = kwargs["running"]
                changed = True
            if "completed" in kwargs and state.completed != kwargs["completed"]:
                state.completed = kwargs["completed"]
                changed = True
            if "avg_time" in kwargs and state.avg_time != kwargs["avg_time"]:
                state.avg_time = kwargs["avg_time"]
                changed = True
            if "eta" in kwargs and state.eta != kwargs["eta"]:
                state.eta = kwargs["eta"]
                changed = True

            # Only broadcast if state actually changed
            if changed:
                self._broadcast_to_topic(
                    f"queue:{queue_type}:status",
                    {"type": "state_update", "state": asdict(state)},
                )

                # Recompute global aggregate and broadcast
                self._recompute_global_queue_state()

    def _recompute_global_queue_state(self):
        """
        Recompute global aggregated queue state from per-queue stats.
        Must be called with self._lock held.
        """
        # Aggregate counts across all queues (working with QueueState DTOs)
        total_pending = sum(q.pending for q in self._queue_state_by_type.values())
        total_running = sum(q.running for q in self._queue_state_by_type.values())
        total_completed = sum(q.completed for q in self._queue_state_by_type.values())

        # Weighted average of avg_time (by number of completed jobs)
        total_weighted_time = sum(q.avg_time * q.completed for q in self._queue_state_by_type.values())
        avg_time = total_weighted_time / total_completed if total_completed > 0 else 0.0

        # Total ETA is max of all queue ETAs (pessimistic estimate)
        eta = max((q.eta for q in self._queue_state_by_type.values()), default=0.0)

        # Update global state DTO
        self._queue_state_global.pending = total_pending
        self._queue_state_global.running = total_running
        self._queue_state_global.completed = total_completed
        self._queue_state_global.avg_time = avg_time
        self._queue_state_global.eta = eta

        # Broadcast global queue status (serialize DTO to dict, omit queue_type since it's None)
        global_state = asdict(self._queue_state_global)
        del global_state["queue_type"]  # Remove null field from global aggregation
        self._broadcast_to_topic("queue:status", {"type": "state_update", "state": global_state})

    def update_queue_state(self, **kwargs):
        """
        Update global queue statistics and broadcast to subscribers.

        DEPRECATED: Use update_queue_state_for_type() for per-queue updates.
        This method is kept for backward compatibility.

        Args:
            **kwargs: Queue state fields (pending, running, completed, avg_time, eta)
        """
        with self._lock:
            # Update global DTO fields from kwargs
            if "pending" in kwargs:
                self._queue_state_global.pending = kwargs["pending"]
            if "running" in kwargs:
                self._queue_state_global.running = kwargs["running"]
            if "completed" in kwargs:
                self._queue_state_global.completed = kwargs["completed"]
            if "avg_time" in kwargs:
                self._queue_state_global.avg_time = kwargs["avg_time"]
            if "eta" in kwargs:
                self._queue_state_global.eta = kwargs["eta"]

            self._broadcast_to_topic(
                "queue:status", {"type": "state_update", "state": asdict(self._queue_state_global)}
            )

    def update_job_state(self, job_id: int, **kwargs):
        """
        Update individual job state and broadcast to subscribers.

        Args:
            job_id: Job ID
            **kwargs: Job state fields (path, status, error, results)
        """
        with self._lock:
            if job_id not in self._jobs_state:
                self._jobs_state[job_id] = JobState(
                    id=job_id,
                    path=None,
                    status="unknown",
                    error=None,
                    results=None,
                )

            # Track if state actually changed
            job = self._jobs_state[job_id]
            changed = False

            if "path" in kwargs and job.path != kwargs["path"]:
                job.path = kwargs["path"]
                changed = True
            if "status" in kwargs and job.status != kwargs["status"]:
                job.status = kwargs["status"]
                changed = True
            if "error" in kwargs and job.error != kwargs["error"]:
                job.error = kwargs["error"]
                changed = True
            if "results" in kwargs and job.results != kwargs["results"]:
                job.results = kwargs["results"]
                changed = True

            # Only broadcast if state actually changed
            if changed:
                self._broadcast_to_topic("queue:jobs", {"type": "job_update", "job": asdict(job)})

            # Clean up completed jobs after a short delay (they've been broadcast)
            if job.status in ("done", "error", "completed"):
                # Remove from state to prevent duplicate broadcasts
                del self._jobs_state[job_id]

    def update_worker_state(self, component: str, **kwargs):
        """
        Update worker state and broadcast to subscribers.

        Args:
            component: Worker component ID (e.g., "worker:tag:0")
            **kwargs: Worker state fields (id, queue_type, status, pid, current_job)
        """
        with self._lock:
            if component not in self._worker_state:
                # Parse component to extract id and queue_type if not provided
                parts = component.split(":")
                worker_id: int | None = None
                queue_type: str | None = None
                if len(parts) == 3:
                    queue_type = parts[1]
                    try:
                        worker_id = int(parts[2])
                    except ValueError:
                        pass

                self._worker_state[component] = WorkerState(
                    component=component,
                    id=worker_id,
                    queue_type=queue_type,
                    status="unknown",
                    pid=None,
                    current_job=None,
                )

            # Track if state actually changed
            worker = self._worker_state[component]
            changed = False

            if "id" in kwargs and worker.id != kwargs["id"]:
                worker.id = kwargs["id"]
                changed = True
            if "queue_type" in kwargs and worker.queue_type != kwargs["queue_type"]:
                worker.queue_type = kwargs["queue_type"]
                changed = True
            if "status" in kwargs and worker.status != kwargs["status"]:
                worker.status = kwargs["status"]
                changed = True
            if "pid" in kwargs and worker.pid != kwargs["pid"]:
                worker.pid = kwargs["pid"]
                changed = True
            if "current_job" in kwargs and worker.current_job != kwargs["current_job"]:
                worker.current_job = kwargs["current_job"]
                changed = True

            # Only broadcast if state actually changed
            if changed:
                # Extract queue_type and id from component for topic construction
                # component format: "worker:{queue_type}:{id}"
                parts = component.split(":")
                if len(parts) == 3:
                    queue_type = parts[1]
                    worker_id_str = parts[2]
                    topic = f"worker:{queue_type}:{worker_id_str}:status"
                else:
                    # Fallback if component format is unexpected
                    topic = f"{component}:status"

                # Broadcast to worker-specific topic (serialize DTO to dict)
                self._broadcast_to_topic(topic, {"type": "worker_update", "worker": asdict(worker)})

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

            client_queue: queue.Queue = queue.Queue(maxsize=10000)
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

        Supports:
        - queue:status - Global aggregated queue stats
        - queue:{queue_type}:status - Per-queue stats (tag/library/calibration)
        - queue:*:status - All per-queue stats
        - queue:jobs - All jobs
        - worker:{queue_type}:{id}:status - Specific worker
        - worker:{queue_type}:*:status - All workers for a queue type
        - worker:*:status - All workers (all queue types)
        - system:health - System health

        Args:
            topic: Topic pattern (may include wildcards)

        Returns:
            State snapshot event or None
        """
        # Global queue status snapshot
        if topic == "queue:status":
            return {"topic": "queue:status", "type": "snapshot", "state": asdict(self._queue_state_global)}

        # Per-queue status snapshots
        if topic.startswith("queue:") and topic.endswith(":status"):
            parts = topic.split(":")
            if len(parts) == 3:
                queue_type = parts[1]
                if queue_type == "*":
                    # All per-queue stats (serialize all QueueState DTOs)
                    return {
                        "topic": "queue:*:status",
                        "type": "snapshot",
                        "queues": {qt: asdict(state) for qt, state in self._queue_state_by_type.items()},
                    }
                elif queue_type in self._queue_state_by_type:
                    # Specific queue type (serialize QueueState DTO)
                    return {
                        "topic": topic,
                        "type": "snapshot",
                        "state": asdict(self._queue_state_by_type[queue_type]),
                    }

        # Queue jobs snapshot (serialize all JobState DTOs)
        if topic == "queue:jobs":
            return {
                "topic": "queue:jobs",
                "type": "snapshot",
                "jobs": [asdict(job) for job in self._jobs_state.values()],
            }

        # Worker status snapshots (serialize WorkerState DTOs)
        if topic.startswith("worker:"):
            parts = topic.split(":")

            if topic == "worker:*:status":
                # All workers (all queue types)
                return {
                    "topic": "worker:*:status",
                    "type": "snapshot",
                    "workers": [asdict(w) for w in self._worker_state.values()],
                }
            elif len(parts) == 4 and parts[2] == "*" and parts[3] == "status":
                # All workers for specific queue type: worker:{queue_type}:*:status
                queue_type = parts[1]
                workers_for_type = [asdict(w) for w in self._worker_state.values() if w.queue_type == queue_type]
                return {
                    "topic": topic,
                    "type": "snapshot",
                    "workers": workers_for_type,
                }
            elif len(parts) == 4 and parts[3] == "status":
                # Specific worker: worker:{queue_type}:{id}:status
                component = f"worker:{parts[1]}:{parts[2]}"
                if component in self._worker_state:
                    return {
                        "topic": topic,
                        "type": "snapshot",
                        "worker": asdict(self._worker_state[component]),
                    }

        # System health snapshot (serialize SystemHealthState DTO)
        if topic == "system:health":
            return {"topic": "system:health", "type": "snapshot", "health": asdict(self._system_health)}

        # GPU health snapshot (serialize GPUHealthState DTO)
        if topic == "system:gpu":
            return {"topic": "system:gpu", "type": "snapshot", "gpu": asdict(self._gpu_health)}

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
        for _client_id, client_info in self._clients.items():
            if self._topic_matches(topic, client_info["topics"]):
                try:
                    client_info["queue"].put_nowait(event)
                    matched_clients += 1
                except queue.Full:
                    # Queue full (e.g., inactive browser tab)
                    # Drop oldest event and add new one (state updates are idempotent)
                    try:
                        client_info["queue"].get_nowait()  # Remove oldest
                        client_info["queue"].put_nowait(event)  # Add newest
                        matched_clients += 1
                    except (queue.Empty, queue.Full):
                        # Race condition or still full - just drop this event
                        pass

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
