"""Reconciliation operations for library_files collection.

Manages tag reconciliation state — checking whether ML tags in the DB have
been written to audio files on disk. Uses the ``tags_stale`` /
``tags_written`` / ``tags_current`` axes from ``file_has_state`` and
``worker_claims`` for claim locking.
"""

from typing import TYPE_CHECKING, Any, cast

from arango.exceptions import DocumentInsertError

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class LibraryFilesReconciliationMixin:
    """Reconciliation operations for library_files.

    Uses edge-based state axes:
    - ``tags_stale`` — file has ML tags in DB that have not been written to disk
    - ``tags_written`` — tags have been written to the audio file
    - ``tags_current`` — on-disk tags match the DB tags
    - ``worker_claims`` with ``claim_reconcile_`` prefix = write claim locking
    """

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def claim_files_for_reconciliation(
        self,
        library_id: str,
        worker_id: str,
        batch_size: int = 100,
        lease_ms: int = 60000,
    ) -> list[dict[str, Any]]:
        """Atomically claim files that need tag reconciliation.

        Discovers stale files (tags in DB not yet written to disk) via
        ``file_states.get_stale_file_ids`` and claims them through
        ``worker_claims``.

        Args:
            library_id: Library document _id
            worker_id: Worker claiming the files
            batch_size: Max files to claim
            lease_ms: Claim lease duration in milliseconds

        Returns:
            List of claimed file documents

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"

        # Get stale file IDs via edge-based state discovery
        stale_ids = self.parent_db.file_states.get_stale_file_ids(library_id=library_id)

        if not stale_ids:
            return []

        # Fetch full file documents for stale IDs
        candidates: list[dict[str, Any]] = [doc for doc in self.collection.get_many(stale_ids) if doc is not None]

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

    def set_file_written(self, file_key: str) -> None:
        """Update file state after successful tag write.

        Transitions the file to ``tags_written`` and ``tags_current`` axes,
        then releases the write claim.

        Args:
            file_key: Document _key or _id

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"

        # Normalize to _key and _id
        if file_key.startswith("library_files/"):
            file_id = file_key
            file_key = file_key.split("/")[1]
        else:
            file_id = f"library_files/{file_key}"

        # Transition state axes
        self.parent_db.file_states.set_tags_written(file_id)
        self.parent_db.file_states.set_tags_current(file_id)

        # Release the reconciliation claim
        claim_key = f"claim_reconcile_{file_key}"
        self.parent_db.worker_claims.collection.delete(claim_key, ignore_missing=True)

    def release_claim(self, file_key: str) -> None:
        """Release a write claim without updating state.

        Used when write fails — the file remains in ``tags_stale`` state
        for retry by another worker.

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
    ) -> int:
        """Count files that need tag reconciliation.

        Returns the number of files in the ``tags_stale`` state for
        the given library.

        Args:
            library_id: Library document _id

        Returns:
            Number of files needing reconciliation

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"
        return len(self.parent_db.file_states.get_stale_file_ids(library_id=library_id))
