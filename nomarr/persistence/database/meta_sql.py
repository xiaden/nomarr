"""Meta key-value store operations."""

import sqlite3


class MetaOperations:
    """Operations for the meta key-value store table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, key: str) -> str | None:
        """Get a metadata value by key."""
        cur = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def set(self, key: str, value: str) -> None:
        """Set a metadata key-value pair."""
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value))
        self.conn.commit()

    def delete(self, key: str) -> None:
        """Delete a metadata key-value pair."""
        self.conn.execute("DELETE FROM meta WHERE key=?", (key,))
        self.conn.commit()

    def get_by_prefix(self, prefix: str) -> dict[str, str]:
        """
        Get all metadata keys matching a prefix.

        Args:
            prefix: Key prefix to match (e.g., 'config_')

        Returns:
            Dict of {key: value} for all matching keys
        """
        cur = self.conn.execute("SELECT key, value FROM meta WHERE key LIKE ?", (f"{prefix}%",))
        return {row[0]: row[1] for row in cur.fetchall()}

    def delete_by_prefix(self, prefix: str) -> None:
        """
        Delete all metadata keys matching a prefix.

        Args:
            prefix: Key prefix to match (e.g., 'worker:')
        """
        self.conn.execute("DELETE FROM meta WHERE key LIKE ?", (f"{prefix}%",))
        self.conn.commit()

    def delete_ephemeral_runtime_keys(self) -> None:
        """Delete ephemeral worker and job metadata keys from previous runs."""
        self.conn.execute("DELETE FROM meta WHERE key LIKE 'worker:%' OR key LIKE 'job:%'")
        self.conn.commit()
