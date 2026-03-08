"""Calibration operations for library_files collection."""

from typing import TYPE_CHECKING, Any

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:

    from nomarr.persistence.db import Database


class LibraryFilesCalibrationMixin:
    """Calibration operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def update_calibration_hash(self, file_id: str, calibration_hash: str) -> None:
        """Update the calibration version hash for a file.

        Delegates to edge-based state via ``db.file_states.set_calibrated()``.
        Upserts a ``file_has_state`` edge to ``file_states/calibrated``.

        CALIBRATION_HASH SEMANTICS:
        - NULL (no edge): File never recalibrated (initial processing with raw scores)
        - Hash value (edge): MD5 of all calibration_state.calibration_def_hash values
          at the time this file's mood tags were last computed via recalibration

        Used to determine if recalibration is needed by comparing against
        meta.calibration_version (current global hash).

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            calibration_hash: Global calibration version hash from meta collection

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"
        self.parent_db.file_states.set_calibrated(file_id, calibration_hash)

    def update_calibration_hashes_batch(self, items: list[tuple[str, str]]) -> None:
        """Update calibration_hash for multiple files in a single AQL query.

        Delegates to edge-based state via ``db.file_states.set_calibrated_batch()``.

        Args:
            items: List of (file_id, calibration_hash) tuples.
                   file_id is the full _id (e.g., "library_files/abc123").

        """
        if not items:
            return
        assert self.parent_db is not None, "parent_db required for edge-based state"
        self.parent_db.file_states.set_calibrated_batch(items)

    def clear_all_calibration_hashes(self) -> int:
        """Clear calibration state for all files.

        Removes all ``calibrated`` edges from ``file_has_state``.
        Used when clearing calibration data to mark all files as needing recalibration.

        Returns:
            Number of calibrated edges removed.
        """
        assert self.parent_db is not None, "parent_db required for edge-based state"
        return self.parent_db.file_states.clear_all_calibrated()

    def get_calibration_status_by_library(self, expected_hash: str) -> list[dict[str, Any]]:
        """Get calibration status counts grouped by library.

        Delegates to edge-based state via
        ``db.file_states.get_calibration_status_by_library()``.

        Returns count of files with current calibration hash vs outdated/missing.

        Args:
            expected_hash: Expected global calibration version hash

        Returns:
            List of {library_id, total_files, current_count, outdated_count}

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"
        return self.parent_db.file_states.get_calibration_status_by_library(expected_hash)
