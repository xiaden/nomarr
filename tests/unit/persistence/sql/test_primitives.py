"""Unit tests for SQL Core primitives against an ephemeral SQLite instance.

Each primitive function in ``nomarr.persistence.sql.primitives`` is tested
against a SQLite in-memory database using a simple SQLAlchemy Core table.

This module uses ``pytest.mark.serial`` to avoid SQLite lock contention
when the full suite runs in parallel — each test creates and drops
temporary tables on a shared SQLite file.
"""

from __future__ import annotations

import contextlib
import os
import tempfile

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, UniqueConstraint, create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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


# Monkey-patch JSONB → JSON for SQLite (same as persistence/database/conftest.py)
def _compile_jsonb_as_json(self, type_, **kw):
    return self.visit_JSON(type_, **kw)


SQLiteTypeCompiler.visit_JSONB = _compile_jsonb_as_json  # type: ignore[attr-defined]


@pytest.fixture
def pg_engine():
    """Function-scoped isolated SQLite engine — avoids lock contention."""
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="nomarr_test_primitives_")
    os.close(fd)
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, echo=False)

    # Create safe tables (skip pgvector-only tables like embeddings)
    import nomarr.persistence.models as _models  # noqa: F401
    from nomarr.persistence.models.base import Base

    safe_tables = [t for t in Base.metadata.sorted_tables if t.name != "embeddings"]
    Base.metadata.create_all(engine, tables=safe_tables)

    yield engine
    engine.dispose()
    with contextlib.suppress(OSError):
        os.unlink(db_path)


@pytest.fixture
def engine(pg_engine):
    """Reuse the isolated function-scoped engine."""
    yield pg_engine


@pytest.fixture
def metadata_and_engine(engine):
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
    with engine.begin() as conn:
        md.create_all(conn)
    yield engine, md
    with engine.begin() as conn:
        md.drop_all(conn)


@pytest.fixture
def session(metadata_and_engine):
    """Provide a transactional sync session that rolls back after each test."""
    engine, _ = metadata_and_engine
    with engine.connect() as conn:
        conn.begin()
        conn.begin_nested()
        session = Session(bind=conn)
        try:
            yield session
        finally:
            session.close()
            conn.rollback()


@pytest.fixture
def test_table(metadata_and_engine) -> Table:
    """Return the test_items Table object."""
    _, md = metadata_and_engine
    return md.tables["test_items"]


# --- select_by_key ---


def test_select_by_key_returns_row(session: Session, test_table: Table):
    """select_by_key returns the matching row when key exists."""
    insert_one(test_table, {"name": "alpha", "value": "v1"}, session=session)
    row = select_by_key(test_table, 1, session=session)
    assert row is not None
    assert row.name == "alpha"
    assert row.value == "v1"


def test_select_by_key_returns_none_for_missing(session: Session, test_table: Table):
    """select_by_key returns None when no row matches."""
    row = select_by_key(test_table, 99999, session=session)
    assert row is None


# --- select_many_by_keys ---


def test_select_many_by_keys_empty_input(session: Session, test_table: Table):
    """select_many_by_keys returns [] for empty keys list."""
    result = select_many_by_keys(test_table, [], session=session)
    assert result == []


def test_select_many_by_keys_partial_matches(session: Session, test_table: Table):
    """select_many_by_keys returns only found rows, silently omitting missing keys."""
    insert_one(test_table, {"name": "beta", "value": "v2"}, session=session)
    insert_one(test_table, {"name": "gamma", "value": "v3"}, session=session)
    # Insert returns rows with auto-incremented ids; fetch them to get actual ids
    all_rows = select_many_by_keys(
        test_table,
        [1, 2, 3, 99999],
        session=session,
    )
    # We should get at most 3 rows (ids 1,2,3 if they exist), 99999 silently omitted
    assert len(all_rows) >= 2  # At least beta and gamma
    returned_ids = {r.id for r in all_rows}
    assert 99999 not in returned_ids


# --- insert_one ---


def test_insert_one_returns_row(session: Session, test_table: Table):
    """insert_one inserts and returns the row."""
    row = insert_one(test_table, {"name": "delta", "value": "v4"}, session=session)
    assert row is not None
    assert row.name == "delta"
    assert row.value == "v4"
    assert row.id is not None


def test_insert_one_raises_on_duplicate(session: Session, test_table: Table):
    """insert_one raises IntegrityError on constraint violation.

    Primitives propagate raw SQLAlchemy exceptions (Phase 3).  The
    translation to ``DuplicateEntityError`` happens at the repository
    level via ``map_persistence_exceptions()`` using PostgreSQL pgcodes,
    which SQLite does not provide.  Tested separately in
    ``test_exception_mapping.py``.
    """
    insert_one(test_table, {"name": "epsilon", "value": "v5"}, session=session)
    with pytest.raises(IntegrityError):
        insert_one(test_table, {"name": "epsilon", "value": "v5_dup"}, session=session)


# --- upsert_by_field ---


def test_upsert_by_field_inserts_when_no_match(session: Session, test_table: Table):
    """upsert_by_field inserts when no existing row matches."""
    row = upsert_by_field(
        test_table,
        "name",
        "zeta_new",
        {"name": "zeta_new", "value": "inserted"},
        session=session,
    )
    assert row is not None
    assert row.name == "zeta_new"
    assert row.value == "inserted"


def test_upsert_by_field_updates_when_match_exists(session: Session, test_table: Table):
    """upsert_by_field updates when a matching row already exists."""
    insert_one(test_table, {"name": "eta", "value": "original"}, session=session)
    row = upsert_by_field(
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


def test_update_by_field_returns_updated_row(session: Session, test_table: Table):
    """update_by_field updates and returns the row."""
    insert_one(test_table, {"name": "theta", "value": "before"}, session=session)
    row = update_by_field(
        test_table,
        "name",
        "theta",
        {"value": "after"},
        session=session,
    )
    assert row is not None
    assert row.value == "after"


def test_update_by_field_returns_none_when_no_match(session: Session, test_table: Table):
    """update_by_field returns None when no row matches."""
    row = update_by_field(
        test_table,
        "name",
        "nonexistent_item_xyz",
        {"value": "nope"},
        session=session,
    )
    assert row is None


# --- delete_by_key ---


def test_delete_by_key_deletes_without_error(session: Session, test_table: Table):
    """delete_by_key deletes without error."""
    row = insert_one(test_table, {"name": "iota", "value": "to_delete"}, session=session)
    delete_by_key(test_table, row.id, session=session)
    # Verify it's gone
    result = select_by_key(test_table, row.id, session=session)
    assert result is None


def test_delete_by_key_no_error_when_missing(session: Session, test_table: Table):
    """delete_by_key does not error when key is missing."""
    # Should not raise
    delete_by_key(test_table, 999999, session=session)


# --- batch_upsert ---


def test_batch_upsert_empty_list(session: Session, test_table: Table):
    """batch_upsert returns [] for empty input."""
    result = batch_upsert(test_table, [], ["name"], session=session)
    assert result == []


def test_batch_upsert_inserts_and_updates(session: Session, test_table: Table):
    """batch_upsert upserts all rows and returns them."""
    # Insert one row first
    insert_one(test_table, {"name": "kappa", "value": "original"}, session=session)

    # Batch upsert: kappa should update, lambda should insert
    data_list = [
        {"name": "kappa", "value": "updated"},
        {"name": "lambda", "value": "new"},
    ]
    rows = batch_upsert(test_table, data_list, ["name"], session=session)
    assert len(rows) == 2
    returned_names = {r.name for r in rows}
    assert "kappa" in returned_names
    assert "lambda" in returned_names
    # Verify kappa was updated
    kappa_row = next(r for r in rows if r.name == "kappa")
    assert kappa_row.value == "updated"


# --- is_table_empty ---


def test_is_table_empty_true_on_fresh_table(engine):
    """is_table_empty returns True on a fresh (empty) table."""
    # Use a separate table that we know is empty
    md = MetaData()
    fresh_table = Table(
        "test_fresh_empty",
        md,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(100)),
    )
    with engine.begin() as conn:
        md.create_all(conn)

    try:
        with Session(engine) as sess:
            result = is_table_empty(fresh_table, session=sess)
            assert result is True
    finally:
        with engine.begin() as conn:
            md.drop_all(conn)


def test_is_table_empty_false_after_insert(session: Session, test_table: Table):
    """is_table_empty returns False after inserting a row."""
    insert_one(test_table, {"name": "mu", "value": "v"}, session=session)
    result = is_table_empty(test_table, session=session)
    assert result is False
