"""Shared fixtures for sabotage tests.

Provides session-scoped PostgreSQL container, Alembic migrations, Database instance,
and seed data factory. Mirrors tests/characterization/conftest.py fixtures.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic.config import Config as AlembicConfig
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.db import Database

if TYPE_CHECKING:
    from collections.abc import Generator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALEMBIC_INI = Path(__file__).parent.parent.parent / "alembic.ini"

# Postgres image with pgvector support
POSTGRES_IMAGE = "pgvector/pgvector:pg17"
POSTGRES_USER = "nomarr"
POSTGRES_PASSWORD = "nomarr"
POSTGRES_DB = "nomarr_test"


# ---------------------------------------------------------------------------
# Session-scoped fixtures: container + database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container with pgvector support."""
    with PostgresContainer(
        image=POSTGRES_IMAGE,
        username=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname=POSTGRES_DB,
        port=5432,
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def test_db_url(postgres_container) -> str:
    """Build the SQLAlchemy URL for the test database."""
    pg = postgres_container
    return (
        f"postgresql+psycopg2://{pg.username}:{pg.password}"
        f"@{pg.get_container_host_ip()}:{pg.get_exposed_port(pg.port)}/{pg.dbname}"
    )


@pytest.fixture(scope="session")
def run_alembic_migrations(test_db_url) -> Generator[str, None, None]:
    """Run Alembic migrations against the test database."""
    alembic_cfg = AlembicConfig(str(ALEMBIC_INI))
    alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(alembic_cfg, "head")
    yield test_db_url


@pytest.fixture(scope="session")
def db(run_alembic_migrations) -> Generator[Database, None, None]:
    """Create a Database instance connected to the test database."""
    database = Database(url=run_alembic_migrations, echo=False, pool_size=2, max_overflow=5)
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Function-scoped fixtures: seed data
# ---------------------------------------------------------------------------


@pytest.fixture()
def seed_data(db):
    """Insert seed data into the test database.

    Creates:
    - 2 libraries
    - 3 files (2 in library 1, 1 in library 2)
    - 5 tags
    - 1 scan record for library 1

    Returns a dict with the created IDs for use in tests.
    """
    # Clean up any existing data first (idempotent)
    _cleanup_seed_data(db)

    created: dict[str, list[int]] = {
        "libraries": [],
        "files": [],
        "tags": [],
        "scans": [],
    }

    # Create 2 libraries
    with db.library.transaction():
        lib1_id = db.library.add_library(
            {
                "name": "TestLib1",
                "path": "/tmp/test1",
                "library_type": "music",
            }
        )
    with db.library.transaction():
        lib2_id = db.library.add_library(
            {
                "name": "TestLib2",
                "path": "/tmp/test2",
                "library_type": "music",
            }
        )
    created["libraries"] = [lib1_id, lib2_id]

    # Create 3 files (2 in lib1, 1 in lib2)
    now_ms_val = now_ms()
    with db.library.transaction():
        file1_id = db.library.add_file_to_library(
            lib1_id,
            {
                "path": "/tmp/test1/song1.flac",
                "normalized_path": "/tmp/test1/song1.flac",
                "file_size": 1024000,
                "modified_time": now_ms_val.value,
                "duration_seconds": 180.5,
                "needs_tagging": 0,
                "is_valid": 1,
                "tagged": 0,
            },
        )
    with db.library.transaction():
        file2_id = db.library.add_file_to_library(
            lib1_id,
            {
                "path": "/tmp/test1/song2.mp3",
                "normalized_path": "/tmp/test1/song2.mp3",
                "file_size": 512000,
                "modified_time": now_ms_val.value,
                "duration_seconds": 240.0,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 0,
            },
        )
    with db.library.transaction():
        file3_id = db.library.add_file_to_library(
            lib2_id,
            {
                "path": "/tmp/test2/song3.flac",
                "normalized_path": "/tmp/test2/song3.flac",
                "file_size": 2048000,
                "modified_time": now_ms_val.value,
                "duration_seconds": 300.0,
                "needs_tagging": 0,
                "is_valid": 1,
                "tagged": 1,
            },
        )
    created["files"] = [file1_id, file2_id, file3_id]

    # Create 5 tags
    with db.library.transaction():
        tag1_id = db.library.find_or_create_tag("nom:mood-strict", "happy", "nom")
    with db.library.transaction():
        tag2_id = db.library.find_or_create_tag("nom:mood-strict", "sad", "nom")
    with db.library.transaction():
        tag3_id = db.library.find_or_create_tag("nom:genre", "rock", "nom")
    with db.library.transaction():
        tag4_id = db.library.find_or_create_tag("nom:genre", "jazz", "nom")
    with db.library.transaction():
        tag5_id = db.library.find_or_create_tag("nom:tempo", "fast", "nom")
    created["tags"] = [tag1_id, tag2_id, tag3_id, tag4_id, tag5_id]

    # Assign tags to files
    with db.library.transaction():
        db.library.replace_file_tags(
            file1_id,
            [
                {"tag_id": tag1_id, "confidence": 0.95, "source": "ml"},
                {"tag_id": tag3_id, "confidence": 0.88, "source": "ml"},
            ],
        )
    with db.library.transaction():
        db.library.replace_file_tags(
            file2_id,
            [
                {"tag_id": tag2_id, "confidence": 0.72, "source": "ml"},
            ],
        )

    # Create 1 scan record for library 1
    with db.library.transaction():
        scan1_id = db.library.add_scan(
            lib1_id,
            {
                "scan_type": "full",
                "status": "completed",
                "started_at": now_ms_val.value - 60000,
                "finished_at": now_ms_val.value,
                "files_found": 2,
                "files_processed": 2,
                "error": None,
            },
        )
    created["scans"] = [scan1_id]

    yield created

    # Cleanup after test
    _cleanup_seed_data(db)


def _cleanup_seed_data(db: Database) -> None:
    """Remove all seed data from the database."""
    try:
        # Delete all tags (this also deletes file_tags via CASCADE)
        all_tags = db.library.list_tags(limit=10000)
        if all_tags:
            tag_ids = [t["id"] for t in all_tags]
            with db.library.transaction():
                db.library.delete_tags_by_ids(tag_ids)

        # Delete all libraries (cascades to files and scans)
        all_libs = db.library.list_libraries()
        for lib in all_libs:
            with db.library.transaction():
                db.library.remove_library(lib["id"])
    except Exception:
        # If cleanup fails, continue (test database will be recreated)
        pass
