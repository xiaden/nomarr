"""
Worker pool service.
Generic worker pool management for any worker type (tagger, scanner, recalibration).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.processing_backends import ProcessingBackend
    from nomarr.services.queue_svc import BaseQueue
    from nomarr.services.workers.base import BaseWorker


@dataclass
class WorkerPoolConfig:
    """Configuration for WorkerPoolService."""

    worker_count: int
    poll_interval: int


# Type alias for worker factory function
WorkerFactory = Callable[[Database, BaseQueue, ProcessingBackend, Any, int, int], "BaseWorker"]


class WorkerPoolService:
    """
    Generic worker pool management service.

    Manages a pool of workers for any worker type (TaggerWorker, LibraryScanWorker,
    RecalibrationWorker). Provides lifecycle management: start, stop, status checking.

    This service is generic and does NOT know about:
    - What kind of jobs are being processed
    - What the processing backend does
    - Queue-specific details

    It only knows:
    - How to create worker instances (via factory function)
    - How to start/stop them
    - How to check their status
    """

    def __init__(
        self,
        db: Database,
        queue: BaseQueue,
        processing_backend: ProcessingBackend,
        event_broker: Any,
        cfg: WorkerPoolConfig,
        worker_factory: WorkerFactory,
        name: str,
    ):
        """
        Initialize worker pool service.

        Args:
            db: Database instance (passed to workers)
            queue: Queue instance (passed to workers)
            processing_backend: Backend function for processing (passed to workers)
            event_broker: Event broker for SSE updates (passed to workers)
            cfg: Worker pool configuration (worker_count, poll_interval)
            worker_factory: Function that creates worker instances (signature: (db, queue, backend, broker, interval, worker_id) -> BaseWorker)
            name: Pool name for logging (e.g., "TaggerPool", "ScannerPool")
        """
        self.db = db
        self.queue = queue
        self.processing_backend = processing_backend
        self.event_broker = event_broker
        self.cfg = cfg
        self.worker_factory = worker_factory
        self.name = name
        self.worker_pool: list[BaseWorker] = []

    def start_workers(self) -> list[BaseWorker]:
        """
        Start all workers in the pool.

        Creates worker instances using the factory and starts them.

        Returns:
            List of started worker instances
        """
        if self.worker_pool:
            logging.warning(f"[{self.name}] Workers already running")
            return self.worker_pool

        logging.info(
            f"[{self.name}] Starting {self.cfg.worker_count} workers (poll_interval={self.cfg.poll_interval}s)"
        )

        for i in range(self.cfg.worker_count):
            worker = self.worker_factory(
                self.db,
                self.queue,
                self.processing_backend,
                self.event_broker,
                self.cfg.poll_interval,
                i,
            )
            worker.start()
            self.worker_pool.append(worker)

        logging.info(f"[{self.name}] All workers started")
        return self.worker_pool

    def stop_all_workers(self) -> None:
        """
        Stop all workers in the pool.

        Signals all workers to stop and waits for them to finish.
        """
        if not self.worker_pool:
            logging.debug(f"[{self.name}] No workers to stop")
            return

        logging.info(f"[{self.name}] Stopping {len(self.worker_pool)} workers...")

        for worker in self.worker_pool:
            worker.stop()

        for worker in self.worker_pool:
            worker.join(timeout=5)

        self.worker_pool.clear()
        logging.info(f"[{self.name}] All workers stopped")

    def are_workers_running(self) -> bool:
        """
        Check if any workers are currently running.

        Returns:
            True if at least one worker is running
        """
        return len(self.worker_pool) > 0 and any(w.is_alive() for w in self.worker_pool)

    def are_workers_idle(self) -> bool:
        """
        Check if all workers are idle (not processing jobs).

        Returns:
            True if all workers are idle (not busy)
        """
        if not self.worker_pool:
            return True
        return all(not w.is_busy() for w in self.worker_pool)

    def wait_until_workers_idle(self, timeout: int = 60, poll_interval: float = 0.5) -> bool:
        """
        Wait for all workers to become idle (finish current jobs).

        Checks worker busy state and waits for all to finish.

        Args:
            timeout: Maximum seconds to wait (default: 60)
            poll_interval: Seconds between status checks (default: 0.5)

        Returns:
            True if all jobs completed within timeout, False if timeout exceeded
        """
        if not self.worker_pool:
            return True

        start_time = time.time()
        while time.time() - start_time < timeout:
            workers_idle = all(not w.is_busy() for w in self.worker_pool)

            if workers_idle:
                return True

            time.sleep(poll_interval)

        return False

    def get_status(self) -> dict[str, Any]:
        """
        Get current status of the worker pool.

        Returns:
            Dict with worker count, running status, and idle status
        """
        return {
            "worker_count": len(self.worker_pool),
            "running": self.are_workers_running(),
            "idle": self.are_workers_idle(),
        }
