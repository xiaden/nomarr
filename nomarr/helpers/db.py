"""
Database helper functions for common SQLite operations.

These helpers work around SQLite quirks (like unreliable cursor.rowcount)
and provide consistent patterns for common operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.data.db import Database

if TYPE_CHECKING:
    pass


def count_and_delete(db: Database, table: str, where_clause: str = "", params: tuple = ()) -> int:
    """
    Count matching rows, then delete them.
    Works around SQLite's unreliable cursor.rowcount for DELETE.

    Args:
        db: Database instance
        table: Table name
        where_clause: Optional WHERE clause (without "WHERE" keyword)
        params: Parameter values for WHERE clause

    Returns:
        Number of rows deleted

    Example:
        count_and_delete(db, "queue", "status = ?", ("error",))
    """
    where_sql = f"WHERE {where_clause}" if where_clause else ""

    # Count first
    count_query = f"SELECT COUNT(*) FROM {table} {where_sql}"
    cur = db.conn.execute(count_query, params)
    row = cur.fetchone()
    count = row[0] if row else 0

    # Then delete
    delete_query = f"DELETE FROM {table} {where_sql}"
    db.conn.execute(delete_query, params)
    db.conn.commit()

    return count


def count_and_update(db: Database, table: str, set_clause: str, where_clause: str = "", params: tuple = ()) -> int:
    """
    Count matching rows, then update them.
    Works around SQLite's unreliable cursor.rowcount for UPDATE.

    Args:
        db: Database instance
        table: Table name
        set_clause: SET clause (without "SET" keyword)
        where_clause: Optional WHERE clause (without "WHERE" keyword)
        params: Parameter values for SET and WHERE clauses (SET params first, then WHERE params)

    Returns:
        Number of rows updated

    Example:
        count_and_update(db, "queue", "status = ?", "status = ?", ("pending", "error"))
    """
    where_sql = f"WHERE {where_clause}" if where_clause else ""

    # Count first
    # For WHERE params, we need to extract them (they come after SET params)
    # This is tricky - let's assume WHERE params are at the end
    where_param_count = where_clause.count("?")
    where_params = params[-where_param_count:] if where_param_count > 0 else ()

    count_query = f"SELECT COUNT(*) FROM {table} {where_sql}"
    cur = db.conn.execute(count_query, where_params)
    row = cur.fetchone()
    count = row[0] if row else 0

    # Then update
    update_query = f"UPDATE {table} SET {set_clause} {where_sql}"
    db.conn.execute(update_query, params)
    db.conn.commit()

    return count


def get_queue_stats(db: Database) -> dict[str, int]:
    """
    Get queue statistics (counts by status).

    Returns:
        Dict with keys: pending, running, completed, errors
    """
    cur = db.conn.execute("SELECT status, COUNT(*) FROM tag_queue GROUP BY status")
    counts = {row[0]: row[1] for row in cur.fetchall()}
    return {
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "completed": counts.get("done", 0),
        "errors": counts.get("error", 0),
    }


def safe_count(db: Database, query: str, params: tuple = ()) -> int:
    """
    Safely execute a COUNT query and return the result.
    Handles None/empty results gracefully.

    Args:
        db: Database instance
        query: SELECT COUNT(*) query
        params: Query parameters

    Returns:
        Count result (0 if None)
    """
    cur = db.conn.execute(query, params)
    row = cur.fetchone()
    return row[0] if row else 0
