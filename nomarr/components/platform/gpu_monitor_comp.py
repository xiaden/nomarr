"""
GPU Health Monitor - Independent process for non-blocking GPU availability tracking.

Runs nvidia-smi probes in a completely separate OS process to ensure that
kernel-level driver deadlocks cannot stall the main application.

Architecture:
- Extends multiprocessing.Process for complete isolation
- Writes GPU resource snapshot to DB (NO TIMESTAMPS)
- Sends heartbeat frames via pipe to HealthMonitorService for liveness tracking
- If probe hangs despite timeout, HealthMonitorService detects and restarts
"""

from __future__ import annotations

import contextlib
import json
import logging
import multiprocessing
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

# Monitor configuration constants
GPU_PROBE_INTERVAL_SECONDS = 15.0  # Time between GPU probes
GPU_PROBE_TIMEOUT_SECONDS = 5.0  # Hard timeout for nvidia-smi subprocess

# Health frame format for HealthMonitorService
HEALTH_FRAME_PREFIX = "HEALTH|"


class GPUHealthMonitor(multiprocessing.Process):
    """
    Independent GPU health monitoring process.

    Continuously probes GPU availability using nvidia-smi and writes results
    to DB gpu_resources collection. Sends heartbeat frames to HealthMonitorService
    for liveness tracking.

    If nvidia-smi hangs (even unkillably), this process may become stuck,
    but HealthMonitorService will detect missed heartbeats and trigger restart
    via InfoService callback.

    Process boundary ensures kernel-level driver deadlocks cannot propagate
    to the main application.
    """

    def __init__(
        self,
        probe_interval: float = GPU_PROBE_INTERVAL_SECONDS,
        health_pipe: Connection | None = None,
    ):
        """
        Initialize GPU health monitor.

        Args:
            probe_interval: Seconds between GPU probes (default: 15.0)
            health_pipe: Child end of pipe to send heartbeats to HealthMonitorService
        """
        super().__init__(daemon=True, name="GPUHealthMonitor")
        self.probe_interval = probe_interval
        self._health_pipe = health_pipe
        self._shutdown = multiprocessing.Event()

    def _send_heartbeat(self, status: str = "healthy") -> None:
        """Send heartbeat frame to HealthMonitorService via pipe.

        Frames use JSON format: HEALTH|{"component_id": "gpu_monitor", "status": "..."}
        """
        if self._health_pipe is None:
            return

        try:
            frame = HEALTH_FRAME_PREFIX + json.dumps(
                {
                    "component_id": "gpu_monitor",
                    "status": status,
                }
            )
            self._health_pipe.send(frame)
        except Exception as e:
            logging.warning(f"[GPUHealthMonitor] Failed to send heartbeat: {e}")

    def run(self) -> None:
        """
        Main monitoring loop (runs in separate process).

        Continuously probes GPU, writes resource snapshot to DB, and sends
        heartbeat frames to HealthMonitorService.
        """
        # Import here to avoid issues with multiprocessing fork/spawn
        from nomarr.components.platform import probe_gpu_availability
        from nomarr.persistence.db import Database

        logging.info("[GPUHealthMonitor] Starting GPU health monitoring process")

        # Create process-local DB connection from environment
        try:
            db = Database()
        except Exception as e:
            logging.error(f"[GPUHealthMonitor] Failed to create DB connection: {e}")
            self._send_heartbeat("unhealthy")
            return

        consecutive_errors = 0
        max_consecutive_errors = 5

        while not self._shutdown.is_set():
            try:
                # Run GPU probe with timeout (this may hang despite timeout in extreme cases)
                result = probe_gpu_availability(timeout=GPU_PROBE_TIMEOUT_SECONDS)

                # Build GPU resource snapshot - NO TIMESTAMPS per architectural invariant
                resource_snapshot = {
                    "gpu_available": result["gpu_available"],
                    "error_summary": result.get("error_summary"),
                }

                # Write resource snapshot via persistence layer
                try:
                    db.meta.write_gpu_resources(resource_snapshot)
                    consecutive_errors = 0  # Reset error counter on success

                    # Send healthy heartbeat after successful probe + write
                    self._send_heartbeat("healthy")

                except Exception as db_error:
                    logging.error(f"[GPUHealthMonitor] Failed to write GPU state to DB: {db_error}")
                    consecutive_errors += 1
                    self._send_heartbeat("unhealthy")

                # Check for repeated failures (might indicate DB issues)
                if consecutive_errors >= max_consecutive_errors:
                    logging.error(f"[GPUHealthMonitor] {consecutive_errors} consecutive DB write failures")
                    # Continue running but report unhealthy
                    self._send_heartbeat("unhealthy")

            except Exception as e:
                logging.error(f"[GPUHealthMonitor] Unexpected error during probe loop: {e}")
                consecutive_errors += 1
                self._send_heartbeat("unhealthy")

            # Wait for next probe interval or shutdown signal
            self._shutdown.wait(timeout=self.probe_interval)

        logging.info("[GPUHealthMonitor] GPU health monitoring process stopped")

        # Close pipe on exit
        if self._health_pipe:
            with contextlib.suppress(Exception):
                self._health_pipe.close()

    def stop(self) -> None:
        """Signal monitor to stop gracefully."""
        self._shutdown.set()
