"""Sessions operations for ArangoDB (web UI sessions with TTL)."""

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor


class SessionOperations:
    """Operations for the sessions collection (auto-expiring via TTL index)."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("sessions")

    def create_session(self, session_id: str, user_id: str, expiry_timestamp: int) -> str:
        """Create a new session.

        Args:
            session_id: Session ID (unique)
            user_id: User ID
            expiry_timestamp: Expiry timestamp (unix ms) - TTL index will auto-delete

        Returns:
            Session _id

        """
        result = cast(
            "dict[str, Any]",
            self.collection.insert(
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "expiry_timestamp": expiry_timestamp,
                    "created_at": now_ms().value,
                },
            ),
        )
        return str(result["_id"])

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session by session_id.

        Args:
            session_id: Session ID

        Returns:
            Session dict or None if not found/expired

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR session IN sessions
                FILTER session.session_id == @session_id
                SORT session._key
                LIMIT 1
                RETURN session
            """,
                bind_vars={"session_id": session_id},
            ),
        )
        return next(cursor, None)

    def delete_session(self, session_id: str) -> None:
        """Delete a session.

        Args:
            session_id: Session ID to delete

        """
        self.db.aql.execute(
            """
            FOR session IN sessions
                FILTER session.session_id == @session_id
                REMOVE session IN sessions
            """,
            bind_vars={"session_id": session_id},
        )

    def delete_user_sessions(self, user_id: str) -> int:
        """Delete all sessions for a user.

        Args:
            user_id: User ID

        Returns:
            Number of sessions deleted

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR session IN sessions
                FILTER session.user_id == @user_id
                REMOVE session IN sessions
                RETURN 1
            """,
                bind_vars={"user_id": user_id},
            ),
        )
        return len(list(cursor))

    def create(self, session_id: str, user_id: str, expiry_timestamp: int) -> str:
        """Alias for create_session() for backward compatibility."""
        return self.create_session(session_id=session_id, user_id=user_id, expiry_timestamp=expiry_timestamp)

    def delete(self, session_id: str) -> None:
        """Alias for delete_session() for backward compatibility."""
        self.delete_session(session_id=session_id)

    def cleanup_expired(self) -> int:
        """Alias for delete_expired_sessions() for backward compatibility."""
        return self.delete_expired_sessions()

    def load_all(self) -> list[dict[str, Any]]:
        """Load all non-expired sessions."""
        now = now_ms().value
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR session IN sessions
                FILTER session.expiry_timestamp > @now
                SORT session.created_at DESC
                RETURN session
            """,
                bind_vars=cast("dict[str, Any]", {"now": now}),
            ),
        )
        return list(cursor)

    def delete_expired_sessions(self) -> int:
        """Delete expired sessions.

        Returns:
            Number of sessions deleted

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR session IN sessions
                FILTER session.expiry_timestamp < @now
                REMOVE session IN sessions
                RETURN 1
            """,
                bind_vars=cast("dict[str, Any]", {"now": now_ms().value}),
            ),
        )
        return len(list(cursor))
