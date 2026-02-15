"""Reconciliation operations for library_files collection."""

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesReconciliationMixin:
    """Reconciliation operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def claim_files_for_reconciliation(
        self,
        library_id: str,
        target_mode: str,
        calibration_hash: str | None,
        worker_id: str,
        batch_size: int = 100,
        lease_ms: int = 60000,
    ) -> list[dict[str, Any]]:
        """Atomically claim files that need tag reconciliation.

        Files need reconciliation when:
        - last_written_mode != target_mode (mode mismatch)
        - calibration_hash mismatch for modes using mood tags (minimal, full)
        - has_nomarr_namespace = true but never tracked (bootstrap case)

        Claims are released after lease_ms expires (stale claim recovery).

        Args:
            library_id: Library document _id
            target_mode: Desired write mode ("none", "minimal", "full")
            calibration_hash: Current calibration hash (None if no calibration)
            worker_id: Worker claiming the files
            batch_size: Max files to claim
            lease_ms: Claim lease duration in milliseconds

        Returns:
            List of claimed file documents

        """
        now = now_ms().value
        lease_expiry = now - lease_ms

        # Build mismatch conditions
        # Mode mismatch: recorded mode differs from target
        # Calibration mismatch: applies only when target uses mood tags
        # Bootstrap: has namespace but never tracked
        calibration_condition = ""
        use_calibration = calibration_hash and target_mode in ("minimal", "full")

        if use_calibration:
            calibration_condition = """
                OR (f.last_written_calibration_hash != @calibration_hash)
            """

        bind_vars: dict[str, Any] = {
            "library_id": library_id,
            "target_mode": target_mode,
            "worker_id": worker_id,
            "batch_size": batch_size,
            "now": now,
            "lease_expiry": lease_expiry,
        }
        if use_calibration:
            bind_vars["calibration_hash"] = calibration_hash

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                f"""
                LET now = @now
                LET lease_expiry = @lease_expiry

                FOR f IN library_files
                    FILTER f.library_id == @library_id
                    FILTER f.is_valid == true
                    FILTER f.tagged == true  // Only reconcile files with ML tags

                    // Unclaimed or stale claim
                    FILTER f.write_claimed_by == null
                        OR f.write_claimed_at < lease_expiry

                    // Mismatch conditions (needs reconciliation)
                    FILTER (
                        // Mode mismatch
                        f.last_written_mode != @target_mode

                        // Calibration mismatch (only for modes using mood tags)
                        {calibration_condition}

                        // Bootstrap: namespace exists but never tracked
                        OR (f.has_nomarr_namespace == true AND f.last_written_mode == null)
                    )

                    SORT f._key
                    LIMIT @batch_size

                    // Atomically claim
                    UPDATE f WITH {{
                        write_claimed_by: @worker_id,
                        write_claimed_at: now
                    }} IN library_files

                    RETURN NEW
                """,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        return list(cursor)

    def set_file_written(self, file_key: str, mode: str, calibration_hash: str | None) -> None:
        """Update file projection state after successful tag write.

        Clears write claim and updates last_written_* fields.

        Args:
            file_key: Document _key or _id
            mode: Write mode used ("none", "minimal", "full")
            calibration_hash: Calibration hash at time of write

        """
        # Normalize to just _key if full _id provided
        if file_key.startswith("library_files/"):
            file_key = file_key.split("/")[1]

        self.db.aql.execute(
            """
            UPDATE @file_key WITH {
                last_written_mode: @mode,
                last_written_calibration_hash: @calibration_hash,
                last_written_at: @timestamp,
                write_claimed_by: null,
                write_claimed_at: null
            } IN library_files
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"file_key": file_key, "mode": mode, "calibration_hash": calibration_hash, "timestamp": now_ms().value},
            ),
        )

    def release_claim(self, file_key: str) -> None:
        """Release a write claim without updating projection state.

        Used when write fails - file remains mismatched for retry.

        Args:
            file_key: Document _key or _id

        """
        # Normalize to just _key if full _id provided
        if file_key.startswith("library_files/"):
            file_key = file_key.split("/")[1]

        self.db.aql.execute(
            """
            UPDATE @file_key WITH {
                write_claimed_by: null,
                write_claimed_at: null
            } IN library_files
            """,
            bind_vars={"file_key": file_key},
        )

    def count_files_needing_reconciliation(
        self,
        library_id: str,
        target_mode: str,
        calibration_hash: str | None,
    ) -> int:
        """Count files that need tag reconciliation.

        Args:
            library_id: Library document _id
            target_mode: Desired write mode
            calibration_hash: Current calibration hash

        Returns:
            Number of files needing reconciliation

        """
        calibration_condition = ""
        use_calibration = calibration_hash and target_mode in ("minimal", "full")

        if use_calibration:
            calibration_condition = """
                OR (f.last_written_calibration_hash != @calibration_hash)
            """

        bind_vars: dict[str, Any] = {
            "library_id": library_id,
            "target_mode": target_mode,
        }
        if use_calibration:
            bind_vars["calibration_hash"] = calibration_hash

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                f"""
                FOR f IN library_files
                    FILTER f.library_id == @library_id
                    FILTER f.is_valid == true
                    FILTER f.tagged == true

                    FILTER (
                        f.last_written_mode != @target_mode
                        {calibration_condition}
                        OR (f.has_nomarr_namespace == true AND f.last_written_mode == null)
                    )

                    COLLECT WITH COUNT INTO count
                    RETURN count
                """,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        result = next(cursor, 0)
        return int(result) if result else 0

    def update_nomarr_namespace_flag(self, file_key: str, has_namespace: bool) -> None:
        """Update the has_nomarr_namespace flag during scanning.

        Args:
            file_key: Document _key or _id
            has_namespace: Whether file has essentia:* namespace tags

        """
        if file_key.startswith("library_files/"):
            file_key = file_key.split("/")[1]

        self.db.aql.execute(
            """
            UPDATE @file_key WITH {
                has_nomarr_namespace: @has_namespace
            } IN library_files
            """,
            bind_vars={"file_key": file_key, "has_namespace": has_namespace},
        )

    def infer_last_written_mode(self, file_key: str, mode: str) -> None:
        """Infer and set last_written_mode from on-disk tag patterns during scan.

        Used during bootstrap to infer projection state from existing files.

        Args:
            file_key: Document _key or _id
            mode: Inferred mode ("none", "minimal", "full", "unknown")

        """
        if file_key.startswith("library_files/"):
            file_key = file_key.split("/")[1]

        self.db.aql.execute(
            """
            UPDATE @file_key WITH {
                last_written_mode: @mode
            } IN library_files
            """,
            bind_vars={"file_key": file_key, "mode": mode},
        )
