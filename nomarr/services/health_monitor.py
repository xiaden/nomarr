"""
Health monitoring service.
Monitors worker health and automatically restarts crashed workers.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass
class HealthMonitorConfig:
    """Configuration for HealthMonitor."""

    check_interval: int


class HealthMonitor:
    """
    Universal worker health monitor.

    Monitors any registered workers and automatically restarts them if they crash.
    Worker-agnostic - works with any object that has `is_alive()` method or
    `.thread.is_alive()` attribute.
    """

    def __init__(self, cfg: HealthMonitorConfig):
        """
        Initialize health monitor.

        Args:
            cfg: Health monitor configuration
        """
        self.cfg = cfg
        self.workers: list[dict[str, Any]] = []
        self.thread: threading.Thread | None = None
        self._stop_requested = False

    def register_worker(
        self,
        worker: Any,
        on_death: Callable[[], None] | None = None,
        name: str | None = None,
    ) -> None:
        """
        Register a worker to monitor.

        Args:
            worker: Worker instance to monitor (must have is_alive() or .thread.is_alive())
            on_death: Optional callback to execute when worker dies (for cleanup)
            name: Optional name for logging (defaults to worker.name or repr)
        """
        worker_name = name or getattr(worker, "name", None) or repr(worker)
        self.workers.append({"worker": worker, "on_death": on_death, "name": worker_name})
        logging.debug(f"[HealthMonitor] Registered worker: {worker_name}")

    def start(self) -> None:
        """Start health monitoring background thread."""
        if self.thread and self.thread.is_alive():
            logging.warning("[HealthMonitor] Already running")
            return

        self._stop_requested = False
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True, name="HealthMonitor")
        self.thread.start()
        logging.info(f"[HealthMonitor] Started (checking every {self.cfg.check_interval}s)")

    def stop(self) -> None:
        """Stop health monitoring background thread."""
        if not self.thread or not self.thread.is_alive():
            return

        logging.info("[HealthMonitor] Stopping...")
        self._stop_requested = True
        self.thread.join(timeout=5)
        logging.info("[HealthMonitor] Stopped")

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while not self._stop_requested:
            try:
                self._check_health()
            except Exception as e:
                logging.error(f"[HealthMonitor] Health check failed: {e}")

            # Sleep in 1s intervals for faster shutdown response
            for _ in range(self.cfg.check_interval):
                if self._stop_requested:
                    break
                time.sleep(1)

    def _check_health(self) -> None:
        """Check all registered workers and restart dead ones."""
        for entry in self.workers:
            worker = entry["worker"]
            name = entry["name"]
            on_death = entry["on_death"]

            # Determine if worker is alive
            is_alive = self._is_worker_alive(worker)

            if not is_alive:
                logging.warning(f"[HealthMonitor] Worker dead: {name}, restarting...")

                # Execute cleanup callback if provided
                if on_death:
                    try:
                        on_death()
                    except Exception as e:
                        logging.error(f"[HealthMonitor] Cleanup callback failed for {name}: {e}")

                # Restart worker
                try:
                    worker.start()
                    logging.info(f"[HealthMonitor] Worker restarted: {name}")
                except Exception as e:
                    logging.error(f"[HealthMonitor] Failed to restart {name}: {e}")

    def _is_worker_alive(self, worker: Any) -> bool:
        """
        Check if worker is alive.

        Handles both threading.Thread workers (has is_alive() method directly)
        and workers that wrap a thread (has .thread.is_alive()).

        Args:
            worker: Worker instance to check

        Returns:
            True if worker is alive, False otherwise
        """
        # Check for direct is_alive() method (TaggerWorker extends Thread)
        if hasattr(worker, "is_alive") and callable(worker.is_alive):
            return bool(worker.is_alive())

        # Check for .thread.is_alive() (LibraryScanWorker wraps a thread)
        if hasattr(worker, "thread") and worker.thread and hasattr(worker.thread, "is_alive"):
            return bool(worker.thread.is_alive())

        # Unknown worker type - assume alive (avoid false positives)
        logging.warning(f"[HealthMonitor] Cannot determine liveness for worker: {worker}")
        return True
