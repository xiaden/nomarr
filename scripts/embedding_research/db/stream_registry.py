"""Low-level DuckDB row helpers for the frozen-stream registries (Plan B Phase 1).

The two registry tables (``stream_registry`` / ``head_stream_registry``) deliberately
carry NO ``PRIMARY KEY`` / ``UNIQUE`` constraint (DuckDB ART/WAL policy in the DD), so
application-level duplicate checks are mandatory and are implemented here as the
public ``raise_if_stream_duplicate`` / ``raise_if_head_duplicate`` guards plus the
transactional ``replace_row`` (delete-then-insert) primitive that Phase 2 publication
uses to repoint a logical ``(song_id, backbone)`` at a newer verified artifact while
never leaving a duplicate row behind.

All helpers are table-generic: callers pass the table name and the column-order tuple
(from ``streams.records``), so the stream and head stores share one SQL surface.  Writes
always use explicit named columns (DDL/record column order is identical here, but named
columns keep the insert robust to any future reordering).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.embedding_research.streams.records import (
    HEAD_STREAM_TABLE,
    STREAM_TABLE,
    DuplicateStreamError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "delete_row",
    "identity_exists",
    "insert_row",
    "list_rows",
    "raise_if_head_duplicate",
    "raise_if_stream_duplicate",
    "replace_row",
    "select_row",
    "update_status",
]

_IDENTITY_WHERE = "song_id = ? AND backbone = ?"


def _column_csv(columns: Sequence[str]) -> str:
    return ", ".join(columns)


def select_row(con, table: str, columns: Sequence[str], song_id: str, backbone: str):
    """Return the registry row for one logical identity in *columns* order, else None."""
    return con.execute(
        f"SELECT {_column_csv(columns)} FROM {table} WHERE {_IDENTITY_WHERE} LIMIT 1",
        [song_id, backbone],
    ).fetchone()


def identity_exists(con, table: str, song_id: str, backbone: str) -> bool:
    """True when a row already exists for the logical identity."""
    return (
        con.execute(f"SELECT 1 FROM {table} WHERE {_IDENTITY_WHERE} LIMIT 1", [song_id, backbone]).fetchone()
        is not None
    )


def raise_if_stream_duplicate(con, song_id: str, backbone: str) -> None:
    """Raise :class:`DuplicateStreamError` if a ``stream_registry`` row already exists."""
    if identity_exists(con, STREAM_TABLE, song_id, backbone):
        raise DuplicateStreamError(
            f"stream_registry already has a row for ({song_id!r}, {backbone!r}); "
            "re-register with replace (delete-then-insert) instead of a plain insert"
        )


def raise_if_head_duplicate(con, song_id: str, backbone: str) -> None:
    """Raise :class:`DuplicateStreamError` if a ``head_stream_registry`` row already exists."""
    if identity_exists(con, HEAD_STREAM_TABLE, song_id, backbone):
        raise DuplicateStreamError(
            f"head_stream_registry already has a row for ({song_id!r}, {backbone!r}); "
            "re-register with replace (delete-then-insert) instead of a plain insert"
        )


def insert_row(con, table: str, columns: Sequence[str], values: Sequence[object]) -> None:
    """Insert one row using explicit named columns (values in *columns* order).

    No database uniqueness is enforced, so callers must have run the app-level
    duplicate guard first (the store's ``register`` does this).
    """
    placeholders = ", ".join("?" for _ in columns)
    con.execute(
        f"INSERT INTO {table} ({_column_csv(columns)}) VALUES ({placeholders})",
        list(values),
    )


def replace_row(con, table: str, columns: Sequence[str], values: Sequence[object]) -> None:
    """Atomically replace the logical identity: delete any existing row, then insert.

    Runs delete + insert inside one DuckDB transaction so no duplicate row survives a
    re-publication even if a later statement fails.  This is the primitive Phase 2
    durable publication uses to repoint ``(song_id, backbone)`` at a newer artifact.
    """
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            f"DELETE FROM {table} WHERE {_IDENTITY_WHERE}",
            [values[columns.index("song_id")], values[columns.index("backbone")]],
        )
        insert_row(con, table, columns, values)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def delete_row(con, table: str, song_id: str, backbone: str) -> bool:
    """Delete the row for one logical identity; returns True if a row was removed."""
    matched = con.execute(
        f"DELETE FROM {table} WHERE {_IDENTITY_WHERE} RETURNING song_id", [song_id, backbone]
    ).fetchone()
    return matched is not None


def list_rows(con, table: str, columns: Sequence[str]) -> list[tuple]:
    """Return every registry row in *columns* order."""
    rows = con.execute(f"SELECT {_column_csv(columns)} FROM {table}").fetchall()
    return [tuple(r) for r in rows]


def update_status(con, table: str, song_id: str, backbone: str, status: str, updated_at: int) -> bool:
    """Set a row's status and bump ``updated_at``; returns True if a row matched."""
    matched = con.execute(
        f"UPDATE {table} SET status = ?, updated_at = ? WHERE {_IDENTITY_WHERE} RETURNING song_id",
        [status, updated_at, song_id, backbone],
    ).fetchone()
    return matched is not None
