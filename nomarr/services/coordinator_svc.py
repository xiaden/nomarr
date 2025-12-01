"""
Processing coordinator for parallel file processing using multiprocessing.
Manages a pool of worker processes, each with independent model caches.
Generic coordinator that can run any ProcessingBackend in a process pool.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
from collections.abc import Callable
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any

from nomarr.helpers.dto.processing_dto import ProcessFileResult

# Set multiprocessing start method to 'spawn' to avoid CUDA context issues
mp.set_start_method("spawn", force=True)


@dataclass
class CoordinatorConfig:
    """Configuration for ProcessingCoordinator."""

    worker_count: int
    event_broker: Any | None


# Type alias for processing backend callables
ProcessingBackend = Callable[[str, bool], ProcessFileResult | dict[str, Any]]


class CoordinatorService:
    """
    Coordinates job submission to the process pool.
    Generic coordinator that runs a ProcessingBackend in a process pool.
    Does not manage models - each worker process loads independently.
    """

    def __init__(self, cfg: CoordinatorConfig, processing_backend: ProcessingBackend):
        """
        Initialize coordinator with processing backend to execute.

        Args:
            cfg: Coordinator configuration
            processing_backend: Callable with signature (path: str, force: bool) -> ProcessFileResult | dict
        """
        self.cfg = cfg
        self._pool: ProcessPoolExecutor | None = None
        self._shutdown = False  # Track shutdown state
        self._backend = processing_backend

    @property
    def worker_count(self) -> int:
        """Get the number of worker processes in the pool."""
        return self.cfg.worker_count

    def start(self):
        """Start the process pool."""
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=self.cfg.worker_count, mp_context=mp.get_context("spawn"))
            logging.info(f"[ProcessingCoordinator] Started process pool with {self.cfg.worker_count} workers")

    def _recreate_pool(self):
        """Recreate the process pool after a crash. Called when BrokenProcessPool is detected."""
        logging.warning("[ProcessingCoordinator] Recreating process pool after worker crash")
        # Clean up broken pool
        if self._pool is not None:
            try:
                self._pool.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                logging.warning(f"[ProcessingCoordinator] Error shutting down broken pool: {e}")
            self._pool = None

        # Restart fresh pool
        self.start()
        logging.info("[ProcessingCoordinator] Process pool recreated successfully")

    def submit(self, path: str, force: bool) -> ProcessFileResult | dict[str, Any]:
        """
        Submit a job and return immediately.

        Args:
            path: File path to process
            force: Force reprocessing

        Returns:
            ProcessFileResult on success, or dict with error/skip info

        Raises:
            RuntimeError: If pool is not available or shutting down
        """
        if self._pool is None:
            raise RuntimeError("ProcessingCoordinator not started")
        if self._shutdown:
            raise RuntimeError("ProcessingCoordinator is shutting down")

        try:
            future = self._pool.submit(self._backend, path, force)
            # Add timeout to prevent jobs from hanging forever
            # Use a generous timeout (3600s = 1 hour per file)
            try:
                result = future.result(timeout=3600)
            except TimeoutError:
                logging.error(f"[ProcessingCoordinator] Processing timeout for {path}")
                return {"error": "Processing timeout (>1 hour)", "status": "error"}
            except BrokenExecutor as e:
                # Worker process crashed - recreate pool and retry once
                logging.error(f"[ProcessingCoordinator] Worker process crashed (BrokenExecutor) for {path}: {e}")
                self._recreate_pool()
                # Retry once with fresh pool
                try:
                    if self._pool is None:
                        raise RuntimeError("Failed to recreate process pool")
                    future = self._pool.submit(self._backend, path, force)
                    result = future.result(timeout=3600)
                except Exception as retry_error:
                    logging.error(f"[ProcessingCoordinator] Retry failed for {path}: {retry_error}")
                    return {"error": f"Worker crash (retry failed): {retry_error}", "status": "error"}
            except Exception as e:
                # Check if it's a worker crash (process pool broken)
                if "abruptly" in str(e).lower() or "process pool" in str(e).lower():
                    # Worker process crashed - recreate pool and retry once
                    logging.error(f"[ProcessingCoordinator] Worker process crashed for {path}: {e}")
                    self._recreate_pool()
                    # Retry once with fresh pool
                    try:
                        if self._pool is None:
                            raise RuntimeError("Failed to recreate process pool")
                        future = self._pool.submit(self._backend, path, force)
                        result = future.result(timeout=3600)
                    except Exception as retry_error:
                        logging.error(f"[ProcessingCoordinator] Retry failed for {path}: {retry_error}")
                        return {"error": f"Worker crash (retry failed): {retry_error}", "status": "error"}
                else:
                    # Other exception
                    logging.error(f"[ProcessingCoordinator] Processing exception for {path}: {e}")
                    return {"error": str(e), "status": "error"}

            return result
        finally:
            pass  # No worker tracking to clean up

    def stop(self):
        """Shutdown the process pool gracefully."""
        self._shutdown = True  # Mark as shutting down before actual shutdown
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=False)
            logging.info("[ProcessingCoordinator] Process pool shut down")
