"""Calibration operations for library_files collection."""

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesCalibrationMixin:
    """Calibration operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def update_calibration_hash(self, file_id: str, calibration_hash: str) -> None:
        """Update the calibration version hash for a file.

        CALIBRATION_HASH SEMANTICS:
        - NULL: File never recalibrated (initial processing with raw scores)
        - Hash value: MD5 of all calibration_state.calibration_def_hash values
          at the time this file's mood tags were last computed via recalibration

        Used to determine if recalibration is needed by comparing against
        meta.calibration_version (current global hash).

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            calibration_hash: Global calibration version hash from meta collection

        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                calibration_hash: @calibration_hash
            } IN library_files
            """,
            bind_vars={"file_id": file_id, "calibration_hash": calibration_hash},
        )

    def clear_all_calibration_hashes(self) -> int:
        """Set calibration_hash and last_written_calibration_hash to null on all files.

        Used when clearing calibration data to mark all files as needing recalibration.

        Returns:
            Number of files updated.

        """
        cursor = self.db.aql.execute(
            """
            FOR f IN library_files
                FILTER f.calibration_hash != null OR f.last_written_calibration_hash != null
                UPDATE f WITH {
                    calibration_hash: null,
                    last_written_calibration_hash: null
                } IN library_files
                RETURN 1
            """,
        )
        return len(list(cursor))  # type: ignore[arg-type]

    def get_calibration_status_by_library(self, expected_hash: str) -> list[dict[str, Any]]:
        """Get calibration status counts grouped by library.

        Returns count of files with current calibration hash vs outdated/missing.

        Args:
            expected_hash: Expected global calibration version hash

        Returns:
            List of {library_id, total_files, current_count, outdated_count}

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR f IN library_files
                    COLLECT lib_id = f.library_id
                    AGGREGATE
                        total = COUNT(1),
                        current = SUM(f.calibration_hash == @expected_hash ? 1 : 0)
                    LET outdated = total - current
                    RETURN {
                        library_id: lib_id,
                        total_files: total,
                        current_count: current,
                        outdated_count: outdated
                    }
                """,
                bind_vars=cast("dict[str, Any]", {"expected_hash": expected_hash}),
            ),
        )
        return list(cursor)
