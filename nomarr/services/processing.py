"""
Processing service.
Shared business logic for audio file processing across all interfaces.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.services.coordinator import ProcessingCoordinator


class ProcessingService:
    """
    Audio processing operations - shared by all interfaces.

    This service encapsulates processing coordination logic, allowing
    CLI, API, and Web interfaces to process files without duplicating
    the orchestration code.
    """

    def __init__(self, coordinator: ProcessingCoordinator | None = None):
        """
        Initialize processing service.

        Args:
            coordinator: ProcessingCoordinator instance for parallel processing
                        If None, falls back to direct processing
        """
        self.coordinator = coordinator

    def process_file(self, path: str, force: bool = False) -> dict[str, Any]:
        """
        Process a single audio file with ML inference and tag writing.

        Args:
            path: Absolute path to audio file
            force: If True, reprocess even if already tagged

        Returns:
            Processing result dict with keys:
                - status: 'success' or 'error'
                - file_path: Path to processed file
                - tags: Dict of written tags (on success)
                - error: Error message (on error)
                - duration_ms: Processing time in milliseconds

        Raises:
            FileNotFoundError: If file doesn't exist
            RuntimeError: If coordinator is not available
            Exception: If processing fails critically
        """
        if not self.coordinator:
            raise RuntimeError("ProcessingCoordinator is not available - processing service is unavailable")

        # Use process pool coordinator for parallel processing
        logging.debug(f"[ProcessingService] Submitting {path} to coordinator")
        return self.coordinator.submit(path, force)

    def process_batch(self, paths: list[str], force: bool = False) -> list[dict[str, Any]]:
        """
        Process multiple audio files in parallel (if coordinator available).

        Args:
            paths: List of absolute paths to audio files
            force: If True, reprocess even if already tagged

        Returns:
            List of processing result dicts (one per file)
        """
        results = []
        for path in paths:
            try:
                result = self.process_file(path, force)
                results.append(result)
            except Exception as e:
                logging.error(f"[ProcessingService] Failed to process {path}: {e}")
                results.append(
                    {
                        "status": "error",
                        "file_path": path,
                        "error": str(e),
                    }
                )

        return results

    def get_worker_count(self) -> int:
        """
        Get current worker process count.

        Returns:
            Number of active worker processes (0 if no coordinator)
        """
        if self.coordinator:
            # Note: ProcessingCoordinator doesn't expose worker_count directly
            # This would need to be added if we want this feature
            return 1  # Placeholder: coordinator exists
        return 0

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
