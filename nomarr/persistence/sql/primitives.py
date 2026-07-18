"""SQL Core primitive functions for CRUD operations.

These are the Tier 1 building blocks that every Tier 2 repository calls
for basic select, insert, upsert, update, delete, batch upsert, and
emptiness checks.  All functions accept a SQLAlchemy ``Table`` object
and an ``AsyncSession``; they never import ORM models.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Table, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def select_by_key(
    table: Table,
    key_val: Any,
    *,
    session: AsyncSession,
    key_col: str = "id",
) -> Row | None:
    """Fetch a single row by primary-key (or alternate key) value.

    Returns ``None`` when no row matches.
    """
    stmt = select(table).where(table.c[key_col] == key_val)
    result = await session.execute(stmt)
    return result.fetchone()


async def select_many_by_keys(
    table: Table,
    keys: list,
    *,
    session: AsyncSession,
    key_col: str = "id",
) -> list[Row]:
    """Fetch all rows whose key column value is in *keys*.

    Short-circuits with ``[]`` when *keys* is empty.  Missing keys are
    silently omitted from the result.
    """
    if not keys:
        return []
    stmt = select(table).where(table.c[key_col].in_(keys))
    result = await session.execute(stmt)
    return list(result.all())


async def insert_one(
    table: Table,
    data: dict,
    *,
    session: AsyncSession,
) -> Row:
    """Insert a single row and return it via ``RETURNING``.

    Raises raw SQLAlchemy exceptions on failure; translation to domain
    exceptions happens at the repository level via
    ``map_persistence_exceptions()``.
    """
    stmt = insert(table).values(**data).returning(table)
    result = await session.execute(stmt)
    row = result.fetchone()
    assert row is not None  # RETURNING always yields a row on success
    return row


async def upsert_by_field(
    table: Table,
    field: str,
    match_val: Any,
    data: dict,
    *,
    session: AsyncSession,
) -> Row:
    """Insert or update a row keyed on *field*.

    Uses PostgreSQL ``ON CONFLICT (field) DO UPDATE``.  The ``set_`` dict
    excludes the conflict field to avoid a no-op self-assignment.
    """
    set_clause = {k: v for k, v in data.items() if k != field}
    stmt = (
        pg_insert(table)
        .values(**data)
        .on_conflict_do_update(
            index_elements=[field],
            set_=set_clause,
        )
        .returning(table)
    )
    result = await session.execute(stmt)
    row = result.fetchone()
    assert row is not None
    return row


async def update_by_field(
    table: Table,
    field: str,
    match_val: Any,
    data: dict,
    *,
    session: AsyncSession,
) -> Row | None:
    """Update rows where *field* equals *match_val*, returning the updated row.

    Returns ``None`` when no row matches.
    """
    stmt = update(table).where(table.c[field] == match_val).values(**data).returning(table)
    result = await session.execute(stmt)
    return result.fetchone()


async def delete_by_key(
    table: Table,
    key_val: Any,
    *,
    session: AsyncSession,
    key_col: str = "id",
) -> None:
    """Delete the row whose key column equals *key_val*.

    No error is raised when the key does not exist.
    """
    stmt = delete(table).where(table.c[key_col] == key_val)
    await session.execute(stmt)


async def batch_upsert(
    table: Table,
    data_list: list[dict],
    conflict_fields: list[str],
    *,
    session: AsyncSession,
) -> list[Row]:
    """Batch insert-or-update using PostgreSQL ``ON CONFLICT … DO UPDATE``.

    Short-circuits with ``[]`` when *data_list* is empty.  The ``set_``
    clause references the special ``excluded`` pseudo-table so that
    conflicting rows receive the incoming values.  The caller manages
    the transaction boundary via *session*.
    """
    if not data_list:
        return []
    insert_stmt = pg_insert(table).values(data_list)
    set_clause = {col: insert_stmt.excluded[col] for col in data_list[0] if col not in conflict_fields}
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=conflict_fields,
        set_=set_clause,
    ).returning(table)
    result = await session.execute(stmt)
    return list(result.all())


async def is_table_empty(
    table: Table,
    *,
    session: AsyncSession,
) -> bool:
    """Return ``True`` when *table* contains zero rows."""
    stmt = select(func.count()).select_from(table)
    result = await session.execute(stmt)
    count = result.scalar()
    return count == 0
