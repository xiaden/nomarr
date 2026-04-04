"""Consolidated lock operations for ArangoDB.

Provides a unified locking mechanism for all lock types:
- capacity_probe: ML capacity probing coordination
- vector_promotion: Vector index promotion coordination

Uses the `locks` collection created in V021 schema refactor.
"""

from typing import TYPE_CHECKING, Any, cast

from arango.exceptions import DocumentInsertError

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.arango_client import DatabaseLike


class LocksOperations:
    """Unified lock operations for all lock types.

    Lock types:
      - capacity_probe: One-time probes per model_set_hash
      - vector_promotion: Prevents concurrent promotions per backbone+library

    Document schema:
      {
        _key: "{lock_type}:{resource_id}",
        lock_type: str,
        resource_id: str,
        holder: str,
        expires_at: int (ms since epoch),
        acquired_at: int (ms since epoch),
        status: "active" | "complete" (optional, for probes)
      }
    """

    def __init__(self, db: "DatabaseLike") -> None:
        """Initialize with database handle.

        Args:
            db: ArangoDB database handle

        """
        self.db = db

    @staticmethod
    def _make_key(lock_type: str, resource_id: str) -> str:
        """Generate deterministic key for a lock."""
        return f"{lock_type}:{resource_id}"

    def try_acquire(
        self,
        lock_type: str,
        resource_id: str,
        holder: str,
        ttl_seconds: int,
    ) -> bool:
        """Attempt to acquire a time-limited lock.

        Uses ArangoDB unique constraint on _key to prevent race conditions.
        If a lock exists but has expired, it will be replaced.

        Args:
            lock_type: Type of lock (e.g., 'capacity_probe', 'vector_promotion')
            resource_id: Resource being locked (e.g., model_set_hash, backbone__library)
            holder: Identifier of the holder (e.g., worker_id)
            ttl_seconds: Time-to-live in seconds

        Returns:
            True if lock acquired, False if another holder owns an active lock

        """
        key = self._make_key(lock_type, resource_id)
        now = now_ms().value
        expires_at = now + (ttl_seconds * 1000)

        try:
            # UPSERT: acquire if not exists or expired
            cursor = cast(
                "Cursor",
                self.db.aql.execute(
                    """
                    LET key = @key
                    LET now = @now
                    LET doc = {
                        _key: key,
                        lock_type: @lock_type,
                        resource_id: @resource_id,
                        holder: @holder,
                        expires_at: @expires_at,
                        acquired_at: @now,
                        status: "active"
                    }

                    UPSERT { _key: key }
                    INSERT doc
                    UPDATE (
                        OLD.expires_at < now OR OLD.holder == @holder
                        ? doc
                        : OLD
                    )
                    IN locks
                    OPTIONS { exclusive: true }
                    RETURN { acquired: NEW.holder == @holder }
                    """,
                    bind_vars=cast(
                        "dict[str, Any]",
                        {
                            "key": key,
                            "lock_type": lock_type,
                            "resource_id": resource_id,
                            "holder": holder,
                            "expires_at": expires_at,
                            "now": now,
                        },
                    ),
                ),
            )
            result = next(cursor, None)
            return result is not None and result.get("acquired", False)
        except DocumentInsertError:
            return False

    def release(self, lock_type: str, resource_id: str, holder: str) -> bool:
        """Release a lock held by the specified holder.

        Args:
            lock_type: Type of lock
            resource_id: Resource being unlocked
            holder: Identifier of the holder releasing the lock

        Returns:
            True if lock was released, False if not found or not owned

        """
        key = self._make_key(lock_type, resource_id)

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR lock IN locks
                    FILTER lock._key == @key
                    FILTER lock.holder == @holder
                    REMOVE lock IN locks
                    RETURN true
                """,
                bind_vars={"key": key, "holder": holder},
            ),
        )
        return next(cursor, False) is True

    def force_release(self, lock_type: str, resource_id: str) -> bool:
        """Force-release a lock regardless of holder.

        Used for stale lock cleanup by supervisors.

        Args:
            lock_type: Type of lock
            resource_id: Resource being unlocked

        Returns:
            True if lock was released, False if not found

        """
        key = self._make_key(lock_type, resource_id)

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR lock IN locks
                    FILTER lock._key == @key
                    REMOVE lock IN locks
                    RETURN true
                """,
                bind_vars={"key": key},
            ),
        )
        return next(cursor, False) is True

    def cleanup_expired(self) -> int:
        """Remove all expired locks.

        Returns:
            Number of locks removed

        """
        now = now_ms().value

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR lock IN locks
                    FILTER lock.expires_at < @now
                    REMOVE lock IN locks
                    RETURN true
                """,
                bind_vars=cast("dict[str, Any]", {"now": now}),
            ),
        )
        return sum(1 for _ in cursor)

    def is_locked(self, lock_type: str, resource_id: str) -> bool:
        """Check if a resource is currently locked (not expired).

        Args:
            lock_type: Type of lock
            resource_id: Resource to check

        Returns:
            True if an active (non-expired) lock exists

        """
        key = self._make_key(lock_type, resource_id)
        now = now_ms().value

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR lock IN locks
                    FILTER lock._key == @key
                    FILTER lock.expires_at >= @now
                    RETURN true
                """,
                bind_vars=cast("dict[str, Any]", {"key": key, "now": now}),
            ),
        )
        return next(cursor, False) is True

    def get_stale_locks(
        self,
        lock_type: str,
        stale_after_ms: int,
    ) -> list[tuple[str, str]]:
        """Find locks older than the threshold.

        Used for reaping locks from crashed workers.

        Args:
            lock_type: Type of locks to check
            stale_after_ms: Age threshold in milliseconds

        Returns:
            List of (lock_type, resource_id) tuples for stale locks

        """
        stale_threshold = now_ms().value - stale_after_ms

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR lock IN locks
                    FILTER lock.lock_type == @lock_type
                    FILTER lock.acquired_at < @threshold
                    RETURN { lock_type: lock.lock_type, resource_id: lock.resource_id }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "lock_type": lock_type,
                        "threshold": stale_threshold,
                    },
                ),
            ),
        )
        return [(doc["lock_type"], doc["resource_id"]) for doc in cursor]

    def complete_lock(self, lock_type: str, resource_id: str) -> None:
        """Mark a lock as complete (for probes that need to persist but not block).

        Args:
            lock_type: Type of lock
            resource_id: Resource being marked complete

        """
        key = self._make_key(lock_type, resource_id)
        now = now_ms().value

        self.db.aql.execute(
            """
            UPDATE { _key: @key }
            WITH { status: "complete", completed_at: @now }
            IN locks
            OPTIONS { ignoreErrors: true }
            """,
            bind_vars=cast("dict[str, Any]", {"key": key, "now": now}),
        )

    def get_lock_status(
        self,
        lock_type: str,
        resource_id: str,
    ) -> dict[str, Any] | None:
        """Get the full lock document.

        Args:
            lock_type: Type of lock
            resource_id: Resource to check

        Returns:
            Lock document or None if not found

        """
        key = self._make_key(lock_type, resource_id)

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR lock IN locks
                    FILTER lock._key == @key
                    RETURN lock
                """,
                bind_vars={"key": key},
            ),
        )
        return next(cursor, None)
