"""
Workers coordinator service.
Coordinates all three worker pools (tagger, scanner, recalibration) for unified operations.

This service provides a facade over the three WorkerPoolService instances, handling:
- Global pause/resume operations (affects all pools)
- Unified status reporting across all pools
- Global worker_enabled flag management

Architecture:
- WorkersCoordinator knows about the three pool types but not their implementation details
- Each pool is managed through WorkerPoolService (generic interface)
- Admin endpoints and InfoService use this coordinator, not individual pools
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.admin_dto import WorkerOperationResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.worker_pool_svc import WorkerPoolService


class WorkersCoordinator:
    """
    Coordinates operations across all worker pools.

    This service provides a unified interface for:
    - Starting/stopping all worker pools
    - Pausing/resuming all workers (via global worker_enabled flag)
    - Getting status across all pools

    The coordinator manages the global worker_enabled flag in DB meta,
    which controls whether any workers should be running.
    """

    def __init__(
        self,
        db: Database,
        tagger_pool_service: WorkerPoolService,
        scanner_pool_service: WorkerPoolService | None,
        recalibration_pool_service: WorkerPoolService,
        default_enabled: bool = True,
    ):
        """
        Initialize workers coordinator.

        Args:
            db: Database instance (for worker_enabled meta flag)
            tagger_pool_service: Tagger worker pool service
            scanner_pool_service: Scanner worker pool service (optional, depends on library_root)
            recalibration_pool_service: Recalibration worker pool service
            default_enabled: Default value for worker_enabled if not set in DB
        """
        self.db = db
        self.tagger_pool = tagger_pool_service
        self.scanner_pool = scanner_pool_service
        self.recalibration_pool = recalibration_pool_service
        self.default_enabled = default_enabled

    def is_worker_system_enabled(self) -> bool:
        """
        Check if worker system is globally enabled.

        Returns:
            True if worker system is enabled in DB meta or default config
        """
        meta = self.db.meta.get("worker_enabled")
        if meta is None:
            return self.default_enabled
        return bool(meta == "true")

    def enable_worker_system(self) -> None:
        """Enable worker system (sets global worker_enabled flag)."""
        self.db.meta.set("worker_enabled", "true")
        logging.info("[WorkersCoordinator] Worker system globally enabled")

    def disable_worker_system(self) -> None:
        """
        Disable worker system (sets global worker_enabled flag).

        This prevents new workers from starting but does not stop running workers.
        Use stop_all_worker_pools() to actually stop running workers.
        """
        self.db.meta.set("worker_enabled", "false")
        logging.info("[WorkersCoordinator] Worker system globally disabled")

    def start_all_worker_pools(self) -> None:
        """
        Start all worker pools.

        Only starts pools if worker system is globally enabled.
        """
        if not self.is_worker_system_enabled():
            logging.info("[WorkersCoordinator] Worker system disabled, not starting pools")
            return

        logging.info("[WorkersCoordinator] Starting all worker pools...")

        # Start tagger pool
        self.tagger_pool.start_workers()

        # Start scanner pool (if configured)
        if self.scanner_pool:
            self.scanner_pool.start_workers()

        # Start recalibration pool
        self.recalibration_pool.start_workers()

        logging.info("[WorkersCoordinator] All worker pools started")

    def stop_all_worker_pools(self) -> None:
        """
        Stop all worker pools.

        Signals all workers to stop and waits for them to finish.
        """
        logging.info("[WorkersCoordinator] Stopping all worker pools...")

        # Stop tagger pool
        self.tagger_pool.stop_all_workers()

        # Stop scanner pool (if configured)
        if self.scanner_pool:
            self.scanner_pool.stop_all_workers()

        # Stop recalibration pool
        self.recalibration_pool.stop_all_workers()

        logging.info("[WorkersCoordinator] All worker pools stopped")

    def wait_until_workers_idle(self, timeout: int = 60) -> bool:
        """
        Wait for all worker pools to become idle.

        Args:
            timeout: Maximum seconds to wait (default: 60)

        Returns:
            True if all pools became idle within timeout, False otherwise
        """
        logging.info("[WorkersCoordinator] Waiting for all pools to become idle...")

        # Wait for each pool sequentially (could be parallelized if needed)
        pools = [self.tagger_pool]
        if self.scanner_pool:
            pools.append(self.scanner_pool)
        pools.append(self.recalibration_pool)

        for pool in pools:
            if not pool.wait_until_workers_idle(timeout=timeout):
                logging.warning(f"[WorkersCoordinator] Pool {pool.name} did not become idle within timeout")
                return False

        logging.info("[WorkersCoordinator] All pools idle")
        return True

    def pause_all_workers(self, event_broker: Any | None = None) -> WorkerOperationResult:
        """
        Pause all workers.

        Sets worker_enabled=false, waits for workers to finish current jobs,
        then stops all worker pools.

        Args:
            event_broker: Optional event broker for SSE updates

        Returns:
            WorkerOperationResult with status message
        """
        logging.info("[WorkersCoordinator] Pause all workers requested")

        # Disable worker system
        self.disable_worker_system()

        # Wait for active jobs to complete
        if not self.wait_until_workers_idle(timeout=60):
            logging.warning("[WorkersCoordinator] Timeout waiting for jobs to complete - forcing shutdown")

        # Stop all pools
        self.stop_all_worker_pools()

        # Emit SSE event
        if event_broker:
            event_broker.update_worker_state({"enabled": False})

        return WorkerOperationResult(status="success", message="All workers paused")

    def resume_all_workers(self, event_broker: Any | None = None) -> WorkerOperationResult:
        """
        Resume all workers.

        Sets worker_enabled=true and starts all worker pools.

        Args:
            event_broker: Optional event broker for SSE updates

        Returns:
            WorkerOperationResult with status message
        """
        logging.info("[WorkersCoordinator] Resume all workers requested")

        # Enable worker system
        self.enable_worker_system()

        # Start all pools
        self.start_all_worker_pools()

        # Emit SSE event
        if event_broker:
            event_broker.update_worker_state({"enabled": True})

        return WorkerOperationResult(status="success", message="All workers resumed")

    def get_workers_status(self) -> dict[str, Any]:
        """
        Get unified status across all worker pools.

        Returns:
            Dict with:
                - enabled: Global worker_enabled flag
                - pools: Dict of pool statuses (tagger, scanner, recalibration)
                    - Each pool: worker_count, running, idle
        """
        status: dict[str, Any] = {
            "enabled": self.is_worker_system_enabled(),
            "pools": {
                "tagger": self.tagger_pool.get_status(),
                "recalibration": self.recalibration_pool.get_status(),
            },
        }

        # Add scanner pool if configured
        if self.scanner_pool:
            status["pools"]["scanner"] = self.scanner_pool.get_status()

        return status
