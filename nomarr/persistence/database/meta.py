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
