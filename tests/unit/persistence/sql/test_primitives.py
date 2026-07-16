"""Unit tests for SQL Core primitives against an ephemeral SQLite instance.

Each primitive function in ``nomarr.persistence.sql.primitives`` is tested
against a SQLite in-memory database using a simple SQLAlchemy Core table.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession

from nomarr.persistence.exceptions import DuplicateKeyError
from nomarr.persistence.sql.primitives import (
    batch_upsert,
    delete_by_key,
    insert_one,
    is_table_empty,
    select_by_key,
    select_many_by_keys,
    update_by_field,
    upsert_by_field,
)
from persistence.database.conftest import pg_async_engine, pg_engine  # noqa: F401 — shared fixtures


@pytest_asyncio.fixture
async def async_engine(pg_async_engine):  # noqa: F811
    """Reuse the shared async engine from the database conftest."""
    yield pg_async_engine


@pytest_asyncio.fixture
async def metadata_and_engine(async_engine):
    """Define test table schema and create tables on the in-memory database."""
    md = MetaData()
    Table(
        "test_items",
        md,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(100), nullable=False),
        Column("value", Text),
        UniqueConstraint("name", name="uq_test_items_name"),
    )
    # SQLite in-memory: use connect+run_sync instead of begin (avoids
    # nested-transaction issues with aiosqlite).
    async with async_engine.connect() as conn:
        await conn.run_sync(md.create_all)
        await conn.commit()
    yield async_engine, md
    async with async_engine.connect() as conn:
        await conn.run_sync(md.drop_all)
        await conn.commit()


@pytest_asyncio.fixture
async def session(metadata_and_engine):
    """Provide a transactional async session that rolls back after each test."""
    engine, _ = metadata_and_engine
    async with engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()
        session = AsyncSession(bind=conn)
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


@pytest.fixture
def test_table(metadata_and_engine) -> Table:
    """Return the test_items Table object."""
    _, md = metadata_and_engine
    return md.tables["test_items"]


# --- select_by_key ---


async def test_select_by_key_returns_row(session: AsyncSession, test_table: Table):
    """select_by_key returns the matching row when key exists."""
    await insert_one(test_table, {"name": "alpha", "value": "v1"}, session=session)
    row = await select_by_key(test_table, 1, session=session)
    assert row is not None
    assert row.name == "alpha"
    assert row.value == "v1"


async def test_select_by_key_returns_none_for_missing(session: AsyncSession, test_table: Table):
    """select_by_key returns None when no row matches."""
    row = await select_by_key(test_table, 99999, session=session)
    assert row is None


# --- select_many_by_keys ---


async def test_select_many_by_keys_empty_input(session: AsyncSession, test_table: Table):
    """select_many_by_keys returns [] for empty keys list."""
    result = await select_many_by_keys(test_table, [], session=session)
    assert result == []


async def test_select_many_by_keys_partial_matches(session: AsyncSession, test_table: Table):
    """select_many_by_keys returns only found rows, silently omitting missing keys."""
    await insert_one(test_table, {"name": "beta", "value": "v2"}, session=session)
    await insert_one(test_table, {"name": "gamma", "value": "v3"}, session=session)
    # Insert returns rows with auto-incremented ids; fetch them to get actual ids
    all_rows = await select_many_by_keys(
        test_table,
        [1, 2, 3, 99999],
        session=session,
    )
    # We should get at most 3 rows (ids 1,2,3 if they exist), 99999 silently omitted
    assert len(all_rows) >= 2  # At least beta and gamma
    returned_ids = {r.id for r in all_rows}
    assert 99999 not in returned_ids


# --- insert_one ---


async def test_insert_one_returns_row(session: AsyncSession, test_table: Table):
    """insert_one inserts and returns the row."""
    row = await insert_one(test_table, {"name": "delta", "value": "v4"}, session=session)
    assert row is not None
    assert row.name == "delta"
    assert row.value == "v4"
    assert row.id is not None


async def test_insert_one_raises_on_duplicate(session: AsyncSession, test_table: Table):
    """insert_one raises DuplicateKeyError on constraint violation."""
    await insert_one(test_table, {"name": "epsilon", "value": "v5"}, session=session)
    with pytest.raises(DuplicateKeyError):
        await insert_one(test_table, {"name": "epsilon", "value": "v5_dup"}, session=session)


# --- upsert_by_field ---


async def test_upsert_by_field_inserts_when_no_match(session: AsyncSession, test_table: Table):
    """upsert_by_field inserts when no existing row matches."""
    row = await upsert_by_field(
        test_table,
        "name",
        "zeta_new",
        {"name": "zeta_new", "value": "inserted"},
        session=session,
    )
    assert row is not None
    assert row.name == "zeta_new"
    assert row.value == "inserted"


async def test_upsert_by_field_updates_when_match_exists(session: AsyncSession, test_table: Table):
    """upsert_by_field updates when a matching row already exists."""
    await insert_one(test_table, {"name": "eta", "value": "original"}, session=session)
    row = await upsert_by_field(
        test_table,
        "name",
        "eta",
        {"name": "eta", "value": "updated"},
        session=session,
    )
    assert row is not None
    assert row.name == "eta"
    assert row.value == "updated"


# --- update_by_field ---


async def test_update_by_field_returns_updated_row(session: AsyncSession, test_table: Table):
    """update_by_field updates and returns the row."""
    await insert_one(test_table, {"name": "theta", "value": "before"}, session=session)
    row = await update_by_field(
        test_table,
        "name",
        "theta",
        {"value": "after"},
        session=session,
    )
    assert row is not None
    assert row.value == "after"


async def test_update_by_field_returns_none_when_no_match(session: AsyncSession, test_table: Table):
    """update_by_field returns None when no row matches."""
    row = await update_by_field(
        test_table,
        "name",
        "nonexistent_item_xyz",
        {"value": "nope"},
        session=session,
    )
    assert row is None


# --- delete_by_key ---


async def test_delete_by_key_deletes_without_error(session: AsyncSession, test_table: Table):
    """delete_by_key deletes without error."""
    row = await insert_one(test_table, {"name": "iota", "value": "to_delete"}, session=session)
    await delete_by_key(test_table, row.id, session=session)
    # Verify it's gone
    result = await select_by_key(test_table, row.id, session=session)
    assert result is None


async def test_delete_by_key_no_error_when_missing(session: AsyncSession, test_table: Table):
    """delete_by_key does not error when key is missing."""
    # Should not raise
    await delete_by_key(test_table, 999999, session=session)


# --- batch_upsert ---


async def test_batch_upsert_empty_list(session: AsyncSession, test_table: Table):
    """batch_upsert returns [] for empty input."""
    result = await batch_upsert(test_table, [], ["name"], session=session)
    assert result == []


async def test_batch_upsert_inserts_and_updates(session: AsyncSession, test_table: Table):
    """batch_upsert upserts all rows and returns them."""
    # Insert one row first
    await insert_one(test_table, {"name": "kappa", "value": "original"}, session=session)

    # Batch upsert: kappa should update, lambda should insert
    data_list = [
        {"name": "kappa", "value": "updated"},
        {"name": "lambda", "value": "new"},
    ]
    rows = await batch_upsert(test_table, data_list, ["name"], session=session)
    assert len(rows) == 2
    returned_names = {r.name for r in rows}
    assert "kappa" in returned_names
    assert "lambda" in returned_names
    # Verify kappa was updated
    kappa_row = next(r for r in rows if r.name == "kappa")
    assert kappa_row.value == "updated"


# --- is_table_empty ---


async def test_is_table_empty_true_on_fresh_table(async_engine):
    """is_table_empty returns True on a fresh (empty) table."""
    # Use a separate table that we know is empty
    md = MetaData()
    fresh_table = Table(
        "test_fresh_empty",
        md,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(100)),
    )
    async with async_engine.connect() as conn:
        await conn.run_sync(md.create_all)
        await conn.commit()

    try:
        async with AsyncSession(async_engine) as sess:
            result = await is_table_empty(fresh_table, session=sess)
            assert result is True
    finally:
        async with async_engine.connect() as conn:
            await conn.run_sync(md.drop_all)
            await conn.commit()


async def test_is_table_empty_false_after_insert(session: AsyncSession, test_table: Table):
    """is_table_empty returns False after inserting a row."""
    await insert_one(test_table, {"name": "mu", "value": "v"}, session=session)
    result = await is_table_empty(test_table, session=session)
    assert result is False
