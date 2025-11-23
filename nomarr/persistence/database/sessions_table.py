"""Session persistence operations for Web UI."""

import sqlite3
import time


class SessionOperations:
    """Operations for the sessions table (Web UI session persistence)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, session_token: str, expiry: float) -> None:
        """
        Insert a new session into the database.

        Args:
            session_token: Unique session token
            expiry: Expiry timestamp (Unix time)
        """
        self.conn.execute(
            "INSERT INTO sessions (session_token, expiry_timestamp, created_at) VALUES (?, ?, ?)",
            (session_token, expiry, time.time()),
        )
        self.conn.commit()

    def get(self, session_token: str) -> float | None:
        """
        Get session expiry timestamp from database.

        Args:
            session_token: Session token to look up

        Returns:
            Expiry timestamp if found, None otherwise
        """
        cur = self.conn.execute("SELECT expiry_timestamp FROM sessions WHERE session_token=?", (session_token,))
        row = cur.fetchone()
        return row[0] if row else None

    def delete(self, session_token: str) -> None:
        """
        Delete a session from the database.

        Args:
            session_token: Session token to delete
        """
        self.conn.execute("DELETE FROM sessions WHERE session_token=?", (session_token,))
        self.conn.commit()

    def load_all(self) -> dict[str, float]:
        """
        Load all non-expired sessions from database into memory.

        Returns:
            Dict mapping session_token to expiry_timestamp
        """
        now = time.time()
        cur = self.conn.execute(
            "SELECT session_token, expiry_timestamp FROM sessions WHERE expiry_timestamp > ?", (now,)
        )
        return {row[0]: row[1] for row in cur.fetchall()}

    def cleanup_expired(self) -> int:
        """
        Delete all expired sessions from database.

        Returns:
            Number of sessions deleted
        """
        now = time.time()
        cur = self.conn.execute("DELETE FROM sessions WHERE expiry_timestamp <= ?", (now,))
        self.conn.commit()
        return cur.rowcount
