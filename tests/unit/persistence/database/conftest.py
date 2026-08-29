"""Shared SQLite fixtures for repository tests using in-memory SQLite.

Provides ``pg_engine`` (session-scoped) and ``pg_session``
(transactional rollback) fixtures.
"""

import atexit
import os
import tempfile

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import Session

# ── JSONB → JSON type mapping for SQLite ────────────────────
# SQLAlchemy models use PostgreSQL JSONB columns which SQLite's dialect
# cannot compile (no visit_JSONB). We monkey-patch the SQLite type compiler
# so JSONB is rendered as JSON — safe because SQLite stores JSON as text
# regardless of which JSON variant is declared.


def _compile_jsonb_as_json(self, type_, **kw):
    return self.visit_JSON(type_, **kw)


SQLiteTypeCompiler.visit_JSONB = _compile_jsonb_as_json  # type: ignore[attr-defined]

# ── SQLite fixtures for Part C repository tests ─────────────

# Temp file shared between sync (DDL) and async (query) engines
# because SQLite :memory: databases are per-connection.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db", prefix="nomarr_test_db_")
os.close(_DB_FD)
_SYNC_URL = f"sqlite:///{_DB_PATH}"
atexit.register(os.unlink, _DB_PATH)


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped ephemeral SQLite database.

    Creates a temp-file SQLite database, creates all compatible tables
    via ``Base.metadata.create_all``, and yields a sync ``Engine``.
    The temp file is cleaned up on process exit.
    """
    engine = create_engine(_SYNC_URL, echo=False)

    @event.listens_for(engine, "connect")
    def _register_sqlite_greatest(dbapi_connection, _connection_record) -> None:
        """Expose ``greatest`` on SQLite, mirroring PostgreSQL semantics.

        Production code uses ``func.greatest`` to order by the latest
        scan/tag activity before applying a row cap. SQLite has no built-in
        ``greatest`` function, so register a shim backed by the builtin
        ``max`` so the ordering regression tests run against the same query.
        PostgreSQL's own ``greatest`` ignores NULLs; the call sites pass both
        args through ``func.coalesce(..., 0)``, making ``max`` equivalent.
        """
        dbapi_connection.create_function("greatest", -1, max)

    # Import all model modules so Base.metadata is fully populated
    import nomarr.persistence.models as _models  # noqa: F401 — registers tables
    from nomarr.persistence.models.base import Base

    # Filter out tables with PostgreSQL-specific column types that
    # cannot be compiled for SQLite (e.g. HALFVEC, PG_ARRAY).
    safe_tables = [t for t in Base.metadata.sorted_tables if t.name != "embeddings"]
    Base.metadata.create_all(engine, tables=safe_tables)

    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    """Provide a transactional sync session that rolls back after each test.

    Uses the sync engine from the SQLite temp-file database.  All compatible
    tables exist — the ``embeddings`` table is excluded because it requires
    PostgreSQL-specific types.
    """
    engine = pg_engine
    conn = engine.connect()
    conn.begin()
    conn.begin_nested()
    session = Session(bind=conn)
    try:
        yield session
    finally:
        session.close()
        conn.rollback()
        conn.close()
