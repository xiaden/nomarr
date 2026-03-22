"""Vector promotion lock operations for ArangoDB.

Manages DB-level locks for hot→cold vector promotion coordination.
Prevents multiple workers from running the expensive promote-and-rebuild
workflow for the same backbone+library simultaneously.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)


class VectorPromotionLockOperations:
    """Operations for the vector_promotion_locks collection.

    Lock documents represent exclusive promotion leases:
    - _key: "{backbone_id}__{library_key}" (deterministic)
    - locked_by: Worker identifier (e.g., "worker:tag:0")
    - locked_at: Lock acquisition timestamp (epoch milliseconds)
    """

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("vector_promotion_locks")

    @staticmethod
    def _make_key(backbone_id: str, library_key: str) -> str:
        """Build a deterministic lock key from backbone and library.

        Args:
            backbone_id: Backbone identifier (e.g., "effnet").
            library_key: ArangoDB ``_key`` of the library document.

        Returns:
            Lock document ``_key``.

        """
        return f"{backbone_id}__{library_key}"

    def try_acquire_lock(
        self, backbone_id: str, library_key: str, worker_id: str
    ) -> bool:
        """Attempt to acquire a promotion lock for a backbone+library pair.

        Uses AQL INSERT with ``ignoreErrors: true`` for atomic lock acquisition.
        If the document already exists (another worker holds the lock), the
        INSERT is silently skipped.

        Args:
            backbone_id: Backbone identifier.
            library_key: ArangoDB ``_key`` of the library document.
            worker_id: Worker identifier claiming the lock.

        Returns:
            ``True`` if lock was acquired, ``False`` if already held.

        """
        key = self._make_key(backbone_id, library_key)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                INSERT {
                    _key: @key,
                    locked_by: @worker_id,
                    locked_at: @locked_at
                } INTO vector_promotion_locks
                OPTIONS { ignoreErrors: true }
                RETURN NEW
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "key": key,
                        "worker_id": worker_id,
                        "locked_at": now_ms().value,
                    },
                ),
            ),
        )
        # If INSERT succeeded, cursor yields the new document; otherwise empty
        result = list(cursor)
        return len(result) > 0

    def release_lock(
        self, backbone_id: str, library_key: str, worker_id: str
    ) -> None:
        """Release a promotion lock, guarded by worker ownership.

        Only the worker that acquired the lock can release it.
        If the lock does not exist or is held by a different worker,
        this is a no-op.

        Args:
            backbone_id: Backbone identifier.
            library_key: ArangoDB ``_key`` of the library document.
            worker_id: Worker identifier releasing the lock.

        """
        key = self._make_key(backbone_id, library_key)
        self.db.aql.execute(
            """
            FOR doc IN vector_promotion_locks
                FILTER doc._key == @key AND doc.locked_by == @worker_id
                REMOVE doc IN vector_promotion_locks
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"key": key, "worker_id": worker_id},
            ),
        )

    def force_release_lock(self, backbone_id: str, library_key: str) -> None:
        """Unconditionally release a promotion lock.

        Used for expiry cleanup of stale locks left by crashed workers.
        No ``locked_by`` guard — removes the lock regardless of owner.

        Args:
            backbone_id: Backbone identifier.
            library_key: ArangoDB ``_key`` of the library document.

        """
        key = self._make_key(backbone_id, library_key)
        self.db.aql.execute(
            """
            FOR doc IN vector_promotion_locks
                FILTER doc._key == @key
                REMOVE doc IN vector_promotion_locks
            """,
            bind_vars=cast("dict[str, Any]", {"key": key}),
        )

    def get_stale_locks(self, stale_after_ms: int) -> list[tuple[str, str]]:
        """Find locks older than a threshold.

        Used by idle promotion to detect and reap locks left by crashed
        workers. The returned tuples can be passed directly to
        ``force_release_lock``.

        Args:
            stale_after_ms: Duration in milliseconds. Locks whose
                ``locked_at`` is more than this many ms in the past
                are considered stale.

        Returns:
            List of ``(backbone_id, library_key)`` tuples for stale locks.

        """
        cutoff = now_ms().value - stale_after_ms
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR doc IN vector_promotion_locks
                    FILTER doc.locked_at < @cutoff
                    RETURN doc._key
                """,
                bind_vars=cast("dict[str, Any]", {"cutoff": cutoff}),
            ),
        )
        results: list[tuple[str, str]] = []
        for key in cursor:
            parts = key.split("__", 1)
            if len(parts) == 2:
                results.append((parts[0], parts[1]))
        return results
