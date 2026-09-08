"""Real-PostgreSQL fixtures for the tag-curation persistence lifecycle tests.

These tests prove that public tag identity is the natural, complete
``(namespace, name, value)`` TagRef (never the storage primary key), and that
this identity stays stable across pagination, fresh Database/connection
sessions (simulated restart/reload), concurrent writers, and atomic
duplicate-safe relinking — all against a *real migrated PostgreSQL*.

This subdirectory is part of the ``tests/characterization/`` tree so it is
executed by the ``database-tests`` CI job (``pytest tests/characterization/
tests/sabotage/... -m requires_database``). Each test is marked
``requires_database`` plus a ``unit``/``integration`` type marker.

It deliberately has its **own** session-scoped PostgreSQL (and runs its own
Alembic migrations) instead of reusing the sibling ``tests/characterization/
conftest.py`` container, so this suite is fully data-isolated from the sibling
ML snapshot/write tests that share that other conftest's database. No parent
conftest fixture is requested here, so the parent session container is never
started for this suite.

Local (no-Docker) development: set ``NOMARR_TEST_DB_URL`` to a
``postgresql+psycopg2://`` URL of a live, migrated PostgreSQL 17 database and
run ``pytest tests/characterization/tag_curation_lifecycle -m requires_database``.
testcontainers (Docker) is used only as the CI fallback when that variable is
unset.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic.config import Config as AlembicConfig

from alembic import command
from nomarr.persistence.db import Database

if TYPE_CHECKING:
    from collections.abc import Generator

_DB_URL_ENV = "NOMARR_TEST_DB_URL"


def _migrate(url: str) -> None:
    """Apply Alembic ``head`` so all natural-key constraints exist."""
    cfg = AlembicConfig(str(Path("alembic.ini")))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def _wipe(db: Database) -> None:
    """Reset song/tag/library state so every test starts from an empty schema.

    Mirrors the characterization ``_cleanup_seed_data`` teardown order (children
    before parents, then orphaned-tag cleanup) so no FK or residue survives a
    test run.
    """
    db.app.truncate_song_state_edges()
    db.library.admin_truncate_song_tag_assignments()
    db.library.admin_truncate_tags()
    db.library.truncate_songs()
    for lib in list(db.library.list_libraries()):
        db.library.remove_library(lib)
    db.library.admin_cleanup_orphaned_tags()


@pytest.fixture(scope="session")
def curation_db_url() -> Generator[str, None, None]:
    """Connection URL for a real, migrated PostgreSQL used by this suite."""
    override = os.environ.get(_DB_URL_ENV)
    if override:
        yield override
        return
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(
        image="pgvector/pgvector:pg17",
        username="nomarr",
        password="nomarr",
        dbname="nomarr_curation",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(pg.port)
        yield f"postgresql+psycopg2://{pg.username}:{pg.password}@{host}:{port}/{pg.dbname}"


@pytest.fixture(scope="session")
def curation_db(curation_db_url: str) -> Generator[Database, None, None]:
    """Session Database facade on the migrated PostgreSQL."""
    _migrate(curation_db_url)
    db = Database(url=curation_db_url)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _curation_clean(curation_db: Database) -> Generator[None, None, None]:
    """Empty the schema before and after each test in this directory."""
    _wipe(curation_db)
    yield
    _wipe(curation_db)
