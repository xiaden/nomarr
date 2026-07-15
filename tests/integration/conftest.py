"""Shared fixtures for integration tests.

Duplicates the ephemeral PostgreSQL fixtures from the database unit-test
conftest so that integration tests under ``tests/integration/`` can use
``pg_session`` without requiring ``tests/`` to be a Python package.
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# ── PostgreSQL fixtures for integration tests ───────────────────

_PG_IMAGE = os.environ.get("PGVECTOR_IMAGE", "pgvector/pgvector:pg17")


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped ephemeral PostgreSQL container via testcontainers.

    Starts a ``pgvector/pgvector:pg17`` container, creates all tables
    (including ``embeddings`` with halfvec) via ``Base.metadata.create_all``,
    and yields a sync ``Engine``.  The container is torn down when the
    session ends.
    """
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(_PG_IMAGE) as pg:
        # Construct sync engine URL from the container
        sync_url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://", 1)
        from sqlalchemy import create_engine

        engine = create_engine(sync_url, echo=False)
        from nomarr.persistence.models.base import Base

        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest_asyncio.fixture
async def pg_async_engine(pg_engine):
    """Create an async engine from the session-scoped sync engine URL.

    Shares the same ephemeral PostgreSQL container — no extra container
    needed.
    """
    from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

    async_url = str(pg_engine.url).replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = _create_async_engine(async_url, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_async_engine):
    """Provide a transactional async session that rolls back after each test.

    Uses the async engine from the testcontainers PG container.  All tables
    (including ``embeddings`` with halfvec) exist — no exclusions.
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
