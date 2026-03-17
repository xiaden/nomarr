"""Reconciliation operations for library_files collection.

Manages tag reconciliation state — checking whether ML tags in the DB have
been written to audio files on disk. Uses edge-based state from
``file_has_state`` and ``worker_claims`` for claim locking.
"""

from typing import TYPE_CHECKING, Any, cast

from arango.exceptions import DocumentInsertError

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:

    from nomarr.persistence.db import Database


class LibraryFilesReconciliationMixin:
    """Reconciliation operations for library_files.

    Uses edge-based state:
    - ``ml_tagged`` edge = file has ML tags in DB
    - ``reconciled`` edge = tags have been written to disk with specific mode/hash
    - ``worker_claims`` with ``claim_reconcile_`` prefix = write claim locking
    """

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

        Uses edge-based state to find files needing reconciliation:
        - Has ``ml_tagged`` edge (file has ML tags in DB)
        - Missing ``reconciled`` edge, or reconciled edge has wrong mode/hash
        - No active reconciliation claim in ``worker_claims``

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
        assert self.parent_db is not None, "parent_db required for edge-based state"

        # Get files needing reconciliation via edge-based query
        candidates = self.parent_db.file_states.get_files_needing_reconciliation(
            library_id=library_id,
            target_mode=target_mode,
            calibration_hash=calibration_hash,
            batch_size=batch_size * 2,  # Over-fetch since some may be claimed
        )

        # Try to claim each candidate via worker_claims
        claimed: list[dict[str, Any]] = []
        now = now_ms().value
        worker_claims = self.parent_db.worker_claims

        for candidate in candidates:
            if len(claimed) >= batch_size:
                break

            file_id = candidate["_id"]
            file_key = candidate["_key"]
            claim_key = f"claim_reconcile_{file_key}"

            try:
                worker_claims.collection.insert(
                    {
                        "_key": claim_key,
                        "file_id": file_id,
                        "worker_id": worker_id,
                        "claimed_at": now,
                        "claim_type": "reconcile",
                    },
                )
                claimed.append(candidate)
            except DocumentInsertError:
                # Already claimed — check if stale
                existing = cast("dict[str, Any] | None", worker_claims.collection.get(claim_key))
                if existing and existing.get("claimed_at", 0) < (now - lease_ms):
                    # Stale claim — replace it
                    worker_claims.collection.update(
                        {
                            "_key": claim_key,
                            "file_id": file_id,
                            "worker_id": worker_id,
                            "claimed_at": now,
                            "claim_type": "reconcile",
                        },
                    )
                    claimed.append(candidate)

        return claimed

    def set_file_written(self, file_key: str, mode: str, calibration_hash: str | None) -> None:
        """Update file state after successful tag write.

        Creates/updates the ``reconciled`` edge and releases the write claim.

        Args:
            file_key: Document _key or _id
            mode: Write mode used ("none", "minimal", "full")
            calibration_hash: Calibration hash at time of write

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"

        # Normalize to _key and _id
        if file_key.startswith("library_files/"):
            file_id = file_key
            file_key = file_key.split("/")[1]
        else:
            file_id = f"library_files/{file_key}"

        # Create/update reconciled edge
        self.parent_db.file_states.set_reconciled(
            file_id=file_id,
            mode=mode,
            calibration_hash=calibration_hash,
        )

        # Release the reconciliation claim
        claim_key = f"claim_reconcile_{file_key}"
        self.parent_db.worker_claims.collection.delete(claim_key, ignore_missing=True)

    def release_claim(self, file_key: str) -> None:
        """Release a write claim without updating state.

        Used when write fails — file remains mismatched for retry.

        Args:
            file_key: Document _key or _id

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"

        if file_key.startswith("library_files/"):
            file_key = file_key.split("/")[1]

        claim_key = f"claim_reconcile_{file_key}"
        self.parent_db.worker_claims.collection.delete(claim_key, ignore_missing=True)

    def count_files_needing_reconciliation(
        self,
        library_id: str,
        target_mode: str,
        calibration_hash: str | None,
    ) -> int:
        """Count files that need tag reconciliation.

        Delegates to edge-based query in ``FileStatesOperations``.

        Args:
            library_id: Library document _id
            target_mode: Desired write mode
            calibration_hash: Current calibration hash

        Returns:
            Number of files needing reconciliation

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"
        return self.parent_db.file_states.count_files_needing_reconciliation(
            library_id=library_id,
            target_mode=target_mode,
            calibration_hash=calibration_hash,
        )
