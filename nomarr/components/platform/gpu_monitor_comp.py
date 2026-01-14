"""
GPU Health Monitor - Independent process for non-blocking GPU availability tracking.

Runs nvidia-smi probes in a completely separate OS process to ensure that
kernel-level driver deadlocks cannot stall the main application or StateBroker.

Architecture:
- Extends multiprocessing.Process for complete isolation
- Writes probe results to DB meta table (IPC via DB)
- If probe hangs despite timeout, monitor continues (process boundary protection)
- StateBroker reads cached results, never probes directly
"""

from __future__ import annotations

import logging
import multiprocessing
import time

# Monitor configuration constants
GPU_PROBE_INTERVAL_SECONDS = 15.0  # Time between GPU probes
GPU_PROBE_TIMEOUT_SECONDS = 5.0  # Hard timeout for nvidia-smi subprocess
GPU_HEALTH_STALENESS_THRESHOLD_SECONDS = 45.0  # If no update in 45s, mark as UNKNOWN


class GPUHealthMonitor(multiprocessing.Process):
    """
    Independent GPU health monitoring process.

    Continuously probes GPU availability using nvidia-smi and writes results
    to DB meta table for consumption by StateBroker and workers.

    If nvidia-smi hangs (even unkillably), this process may become stuck,
    but the main application continues normally. StateBroker will detect
    stale health data and transition GPU status to UNKNOWN.

    Process boundary ensures kernel-level driver deadlocks cannot propagate
    to the main application or StateBroker polling thread.
    """

    def __init__(self, probe_interval: float = GPU_PROBE_INTERVAL_SECONDS):
        """
        Initialize GPU health monitor.

        Args:
            probe_interval: Seconds between GPU probes (default: 15.0)
        """
        super().__init__(daemon=True, name="GPUHealthMonitor")
        self.probe_interval = probe_interval
        self._shutdown = multiprocessing.Event()

    def run(self) -> None:
        """
        Main monitoring loop (runs in separate process).

        Continuously probes GPU and writes results to DB meta table.
        If a probe hangs, this process may become stuck, but the main
        application is protected by the process boundary.
        """
        # Import here to avoid issues with multiprocessing fork/spawn
        import uuid

        from nomarr.components.platform import probe_gpu_availability
        from nomarr.persistence.db import Database

        logging.info("[GPUHealthMonitor] Starting GPU health monitoring process")

        # Create process-local DB connection from environment
        try:
            db = Database()
        except Exception as e:
            logging.error(f"[GPUHealthMonitor] Failed to create DB connection: {e}")
            return

        consecutive_errors = 0
        max_consecutive_errors = 5

        while not self._shutdown.is_set():
            try:
                # Run GPU probe with timeout (this may hang despite timeout in extreme cases)
                result = probe_gpu_availability(timeout=GPU_PROBE_TIMEOUT_SECONDS)

                # Build atomic health JSON blob
                health_dict = {
                    "probe_id": str(uuid.uuid4()),
                    "status": "available" if result["available"] else "unavailable",
                    "available": result["available"],
                    "probe_time": result["probe_time"],
                    "last_ok_at": result["probe_time"] if result["available"] else None,
                    "error_summary": result.get("error_summary"),
                    "duration_ms": result["duration_ms"],
                }

                # Write atomic JSON blob via persistence layer
                try:
                    db.meta.write_gpu_health_atomic(health_dict)
                    consecutive_errors = 0  # Reset error counter on success

                    if result["available"]:
                        logging.debug(f"[GPUHealthMonitor] GPU available ({result['duration_ms']:.1f}ms)")
                    else:
                        logging.warning(f"[GPUHealthMonitor] GPU unavailable: {result['error_summary']}")

                except Exception as db_error:
                    logging.error(f"[GPUHealthMonitor] Failed to write GPU state to DB: {db_error}")
                    consecutive_errors += 1

                # Check for repeated failures (might indicate DB issues)
                if consecutive_errors >= max_consecutive_errors:
                    logging.error(
                        f"[GPUHealthMonitor] {consecutive_errors} consecutive DB write failures, "
                        "monitor may be unhealthy"
                    )
                    # Continue running but log the issue

            except Exception as e:
                logging.error(f"[GPUHealthMonitor] Unexpected error during probe loop: {e}")
                consecutive_errors += 1

            # Wait for next probe interval or shutdown signal
            self._shutdown.wait(timeout=self.probe_interval)

        logging.info("[GPUHealthMonitor] GPU health monitoring process stopped")

    def stop(self) -> None:
        """Signal monitor to stop gracefully."""
        self._shutdown.set()


def check_gpu_health_staleness(last_check_at: float | None) -> bool:
    """
    Check if GPU health data is stale.

    Args:
        last_check_at: Unix timestamp of last GPU probe (None if never probed)

    Returns:
        True if health data is stale (older than threshold)
    """
    if last_check_at is None:
        return True

    age = time.time() - last_check_at
    return age >= GPU_HEALTH_STALENESS_THRESHOLD_SECONDS
