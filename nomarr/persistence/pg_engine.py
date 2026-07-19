"""PostgreSQL sync engine factory, session factory, and session generator.

PostgreSQL sync engine factory for Nomarr.
"""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_pg_engine(
    database_url: str,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
) -> Engine:
    """Create a configured sync PostgreSQL engine.

    Args:
        database_url: Full connection string (e.g.
            ``postgresql+psycopg2://user:pass@host:5432/db``).
        echo: If ``True``, log all SQL statements (default: ``False``).
        pool_size: Connection pool size (default: 5).
        max_overflow: Max overflow connections beyond pool_size (default: 10).

    Returns:
        Configured Engine instance.

    """
    return create_engine(
        database_url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        connect_args={
            "options": "-c statement_timeout=30000",
        },
    )


def session_factory(
    engine: Engine,
) -> sessionmaker[Session]:
    """Create a sync session factory bound to the given engine.

    Args:
        engine: Engine instance from :func:`create_pg_engine`.

    Returns:
        Sync sessionmaker with ``expire_on_commit=False``.

    """
    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )


def get_session(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    """Yield a :class:`Session` with automatic cleanup.

    Args:
        session_factory: Pre-configured sessionmaker (from
            :func:`session_factory`).

    Yields:
        Session bound to the engine.

    """
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
