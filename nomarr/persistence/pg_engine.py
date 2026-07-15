"""PostgreSQL async engine factory, session factory, and session generator.

PostgreSQL async engine factory for Nomarr.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_pg_engine(database_url: str) -> AsyncEngine:
    """Create a configured async PostgreSQL engine.

    Args:
        database_url: Full connection string (e.g.
            ``postgresql+asyncpg://user:pass@host:5432/db``).

    Returns:
        Configured AsyncEngine instance.

    """
    return create_async_engine(
        database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args={
            "statement_timeout": 30000,  # 30 seconds
            "command_timeout": 30,  # 30 seconds
        },
    )


def async_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine.

    Args:
        engine: AsyncEngine instance from :func:`create_pg_engine`.

    Returns:
        Async sessionmaker with ``expire_on_commit=False``.

    """
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an :class:`AsyncSession` with automatic cleanup.

    Uses :func:`asyncio.shield` on close to prevent connection leaks
    under :exc:`asyncio.CancelledError`.

    Args:
        session_factory: Pre-configured async sessionmaker (from
            :func:`async_session_factory`).

    Yields:
        AsyncSession bound to the engine.

    """
    import asyncio

    async with session_factory() as session:
        try:
            yield session
        finally:
            await asyncio.shield(session.close())
