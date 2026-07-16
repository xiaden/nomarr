"""Shared fixtures for integration tests.

Duplicates the ephemeral SQLite fixtures from the database unit-test
conftest so that integration tests under ``tests/integration/`` can use
``pg_session`` without requiring ``tests/`` to be a Python package.
"""

import atexit
import os
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

# ── SQLite fixtures for integration tests ───────────────────

# Temp file shared between sync (DDL) and async (query) engines
# because SQLite :memory: databases are per-connection.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db", prefix="nomarr_int_test_")
os.close(_DB_FD)
_SYNC_URL = f"sqlite:///{_DB_PATH}"
_ASYNC_URL = f"sqlite+aiosqlite:///{_DB_PATH}"
atexit.register(os.unlink, _DB_PATH)


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped ephemeral SQLite database.

    Creates a temp-file SQLite database, creates all compatible tables
    via ``Base.metadata.create_all``, and yields a sync ``Engine``.
    The temp file is cleaned up on process exit.
    """
    engine = create_engine(_SYNC_URL, echo=False)

    # Import all model modules so Base.metadata is fully populated
    import nomarr.persistence.models as _models  # noqa: F401 — registers tables
    from nomarr.persistence.models.base import Base

    # Filter out tables with PostgreSQL-specific column types that
    # cannot be compiled for SQLite (e.g. HALFVEC, PG_ARRAY).
    safe_tables = [t for t in Base.metadata.sorted_tables if t.name != "embeddings"]
    Base.metadata.create_all(engine, tables=safe_tables)

    yield engine
    engine.dispose()


@pytest_asyncio.fixture
async def pg_async_engine(pg_engine):
    """Create an async engine sharing the same temp-file SQLite database.

    Depends on ``pg_engine`` for table creation ordering.
    """
    engine = _create_async_engine(_ASYNC_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_async_engine):
    """Provide a transactional async session that rolls back after each test.

    Uses the async engine from the SQLite temp-file database.  All compatible
    tables exist — the ``embeddings`` table is excluded because it requires
    PostgreSQL-specific types.
    """
    engine = pg_async_engine
    async with engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()
        session = AsyncSession(bind=conn)
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()
