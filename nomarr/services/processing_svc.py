"""
Processing service.
Shared business logic for audio file processing across all interfaces.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.services.coordinator_svc import CoordinatorService


class ProcessingService:
    """
    Audio processing operations - shared by all interfaces.

    This service encapsulates processing coordination logic, allowing
    CLI, API, and Web interfaces to process files without duplicating
    the orchestration code.
    """

    def __init__(self, coordinator: CoordinatorService | None = None):
        """
        Initialize processing service.

        Args:
            coordinator: CoordinatorService instance for parallel processing
                        If None, falls back to direct processing
        """
        self.coordinator = coordinator

    def is_available(self) -> bool:
        """
        Check if processing service is available.

        Returns:
            True if coordinator is available and can accept jobs
        """
        return self.coordinator is not None

    def shutdown(self) -> None:
        """
        Gracefully shutdown the processing coordinator and worker pool.
        """
        if self.coordinator:
            logging.info("[ProcessingService] Shutting down processing coordinator")
            self.coordinator.stop()
            self.coordinator = None
