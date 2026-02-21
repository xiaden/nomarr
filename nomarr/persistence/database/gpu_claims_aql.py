"""GPU warmup claim operations for ArangoDB.

Manages a singleton claim document that serializes GPU cache warming
across multiple discovery worker processes. Only one worker may warm
the GPU cache at a time; other workers skip to CPU-only processing.

Collection: gpu_warmup_claims (single document, _key="singleton")
"""

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor


class GpuClaimOperations:
    """Operations for the gpu_warmup_claims collection.

    Singleton claim document:
    - _key: "singleton" (enforces at most one claim via unique key)
    - worker_id: Worker identifier holding the claim
    - claimed_at: Timestamp when claim was acquired (milliseconds)
    - heartbeat_at: Timestamp of last heartbeat (milliseconds)
    """

    SINGLETON_KEY = "singleton"

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("gpu_warmup_claims")

    def acquire_claim(self, worker_id: str, stale_timeout_s: int = 60) -> bool:
        """Attempt to acquire the singleton GPU warmup claim.

        Succeeds if:
        - No claim exists (collection empty), or
        - Existing claim is stale (heartbeat older than stale_timeout_s)

        Uses AQL to atomically check-and-insert/replace.

        Args:
            worker_id: Worker identifier (e.g., "worker:tag:0").
            stale_timeout_s: Seconds after which a claim without heartbeat
                is considered stale and can be stolen.

        Returns:
            True if claim was acquired, False if another worker holds a fresh claim.

        """
        now = now_ms().value
        stale_cutoff_ms = now - (stale_timeout_s * 1000)

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                LET existing = DOCUMENT("gpu_warmup_claims/singleton")
                LET can_acquire = (
                    existing == null
                    OR existing.heartbeat_at <= @stale_cutoff_ms
                )
                FILTER can_acquire
                UPSERT { _key: "singleton" }
                INSERT {
                    _key: "singleton",
                    worker_id: @worker_id,
                    claimed_at: @now,
                    heartbeat_at: @now
                }
                UPDATE {
                    worker_id: @worker_id,
                    claimed_at: @now,
                    heartbeat_at: @now
                }
                IN gpu_warmup_claims
                RETURN true
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "worker_id": worker_id,
                        "stale_cutoff_ms": stale_cutoff_ms,
                        "now": now,
                    },
                ),
            ),
        )
        results = list(cursor)
        return len(results) > 0

    def heartbeat_claim(self, worker_id: str) -> bool:
        """Update heartbeat timestamp on a held claim.

        Only updates if the caller is the current holder. Returns False
        if the claim was lost (stolen by another worker after going stale).

        Args:
            worker_id: Worker identifier that should hold the claim.

        Returns:
            True if heartbeat was updated, False if claim is not held
            by this worker (or doesn't exist).

        """
        now = now_ms().value

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                LET existing = DOCUMENT("gpu_warmup_claims/singleton")
                FILTER existing != null AND existing.worker_id == @worker_id
                UPDATE "singleton" WITH { heartbeat_at: @now } IN gpu_warmup_claims
                RETURN true
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "worker_id": worker_id,
                        "now": now,
                    },
                ),
            ),
        )
        results = list(cursor)
        return len(results) > 0

    def release_claim(self, worker_id: str) -> bool:
        """Release a held claim.

        Only deletes if the caller is the current holder. Safe to call
        even if the caller does not hold the claim (no-op).

        Args:
            worker_id: Worker identifier releasing the claim.

        Returns:
            True if claim was released, False if not held by this worker.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                LET existing = DOCUMENT("gpu_warmup_claims/singleton")
                FILTER existing != null AND existing.worker_id == @worker_id
                REMOVE "singleton" IN gpu_warmup_claims
                RETURN true
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"worker_id": worker_id},
                ),
            ),
        )
        results = list(cursor)
        return len(results) > 0

    def get_claim(self) -> dict[str, Any] | None:
        """Get the current claim document.

        Returns:
            Claim document dict or None if no claim exists.

        """
        try:
            doc = self.collection.get(self.SINGLETON_KEY)
            return cast("dict[str, Any] | None", doc)
        except Exception:
            return None
