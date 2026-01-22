"""Worker claims operations for ArangoDB.

Manages ephemeral claim documents for discovery-based workers.
Claims are temporary leases, not authoritative state.
"""

from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase
from arango.exceptions import DocumentInsertError

from nomarr.helpers.time_helper import now_ms


class WorkerClaimsOperations:
    """Operations for the worker_claims collection.

    Claim documents represent temporary work leases:
    - _key: "claim_" + file._key (deterministic)
    - file_id: Full _id of claimed file
    - worker_id: Worker identifier (matches health.component_id)
    - claimed_at: Claim timestamp (milliseconds)
    """

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("worker_claims")

    def try_claim_file(self, file_id: str, worker_id: str) -> bool:
        """Attempt to claim a file for processing.

        Uses deterministic _key based on file._key to enforce uniqueness.
        ArangoDB document key uniqueness prevents duplicate claims.

        Args:
            file_id: Full file document _id (e.g., "library_files/12345")
            worker_id: Worker identifier (e.g., "worker:tag:0")

        Returns:
            True if claim successful, False if file already claimed
        """
        # Extract file _key from _id (e.g., "library_files/12345" -> "12345")
        file_key = file_id.split("/")[1] if "/" in file_id else file_id
        claim_key = f"claim_{file_key}"

        try:
            self.collection.insert(
                {
                    "_key": claim_key,
                    "file_id": file_id,
                    "worker_id": worker_id,
                    "claimed_at": now_ms(),
                }
            )
            return True
        except DocumentInsertError:
            # Unique key constraint violation - file already claimed
            return False

    def release_claim(self, file_id: str) -> bool:
        """Release claim on a file.

        Called after processing completes or on error.

        Args:
            file_id: Full file document _id

        Returns:
            True if claim was released, False if no claim existed
        """
        file_key = file_id.split("/")[1] if "/" in file_id else file_id
        claim_key = f"claim_{file_key}"

        try:
            self.collection.delete(claim_key, ignore_missing=True)
            return True
        except Exception:
            return False

    def get_claim(self, file_id: str) -> dict[str, Any] | None:
        """Get claim document for a file.

        Args:
            file_id: Full file document _id

        Returns:
            Claim document or None if not claimed
        """
        file_key = file_id.split("/")[1] if "/" in file_id else file_id
        claim_key = f"claim_{file_key}"

        try:
            return cast(dict[str, Any], self.collection.get(claim_key))
        except Exception:
            return None

    def cleanup_inactive_worker_claims(self, heartbeat_cutoff_ms: int) -> int:
        """Remove claims from workers with stale heartbeats.

        Args:
            heartbeat_cutoff_ms: Timestamp threshold - workers with
                last_heartbeat before this are considered inactive

        Returns:
            Number of claims removed
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                LET active_workers = (
                    FOR h IN health
                        FILTER h.component_type == "worker"
                        FILTER h.last_heartbeat > @heartbeat_cutoff
                        RETURN h.component_id
                )
                FOR claim IN worker_claims
                    FILTER claim.worker_id NOT IN active_workers
                    REMOVE claim IN worker_claims
                    RETURN 1
                """,
                bind_vars=cast(dict[str, Any], {"heartbeat_cutoff": heartbeat_cutoff_ms}),
            ),
        )
        return sum(cursor)

    def cleanup_completed_file_claims(self) -> int:
        """Remove claims for files that are already tagged.

        Returns:
            Number of claims removed
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR claim IN worker_claims
                    LET file = DOCUMENT(claim.file_id)
                    FILTER file.tagged == 1 OR file.needs_tagging == 0
                    REMOVE claim IN worker_claims
                    RETURN 1
                """
            ),
        )
        return sum(cursor)

    def cleanup_ineligible_file_claims(self) -> int:
        """Remove claims for files that no longer need processing.

        Removes claims where:
        - File document no longer exists
        - File no longer needs tagging
        - File is marked invalid

        Returns:
            Number of claims removed
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR claim IN worker_claims
                    LET file = DOCUMENT(claim.file_id)
                    FILTER file == null OR file.needs_tagging == 0 OR file.is_valid == 0
                    REMOVE claim IN worker_claims
                    RETURN 1
                """
            ),
        )
        return sum(cursor)

    def cleanup_all_stale_claims(self, heartbeat_timeout_ms: int) -> int:
        """Run all claim cleanup operations.

        Combines:
        1. Claims from inactive workers
        2. Claims for completed files
        3. Claims for ineligible files

        Args:
            heartbeat_timeout_ms: How long before a worker heartbeat is stale

        Returns:
            Total number of claims removed
        """
        heartbeat_cutoff = now_ms().value - heartbeat_timeout_ms
        removed = 0
        removed += self.cleanup_inactive_worker_claims(heartbeat_cutoff)
        removed += self.cleanup_completed_file_claims()
        removed += self.cleanup_ineligible_file_claims()
        return removed

    def get_active_claim_count(self) -> int:
        """Get count of active claims.

        Returns:
            Number of active claim documents
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                RETURN LENGTH(worker_claims)
                """
            ),
        )
        return next(cursor, 0)

    def get_claims_for_worker(self, worker_id: str) -> list[dict[str, Any]]:
        """Get all claims held by a specific worker.

        Args:
            worker_id: Worker identifier

        Returns:
            List of claim documents
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR claim IN worker_claims
                    FILTER claim.worker_id == @worker_id
                    RETURN claim
                """,
                bind_vars=cast(dict[str, Any], {"worker_id": worker_id}),
            ),
        )
        return list(cursor)
